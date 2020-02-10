import random

from collections import defaultdict

import trio

from named1 import __version__, debug, providers, rediscache
from named1.dnserror import WontResolve
from named1.nameclient import NameClient
from named1.serve53 import serve53

async def cacher_task(receiver):
    with trio.move_on_after(10):
        async with receiver:
            async for res in receiver:
                await rediscache.cache(res)
        return
    print("RedisCacher timed out!")

async def resolve_task(sender, resolver, dnsquery, done, success):
    async with sender:
        stats_queries[resolver.name] += 1
        start_time = trio.current_time()
        try:
            # This can be longer running than interactive requests
            with trio.move_on_after(5):
                sender.send_nowait(await resolver.resolve(**dnsquery))
                success()
                stats_count[resolver.name] += 1
                duration = min(1.0, trio.current_time() - start_time)
                stats_time[resolver.name] = 0.9 * (stats_time[resolver.name] or duration) + 0.1 * duration
            return
        except trio.BrokenResourceError:  # We are late, receiver is dead
            pass
        except WontResolve:  # Resolver can't handle it
            return
        finally:
            done.set()  # Signal that we are no longer working
    stats_time[resolver.name] = 0.0
    stats_timeouts[resolver.name] += 1


async def resolve_happy(resolvers, dnsquery, nursery, sender):
    async with sender, trio.open_nursery() as happy_eyeballs:
        success = happy_eyeballs.cancel_scope.cancel
        for r in resolvers:
            done = trio.Event()
            nursery.start_soon(resolve_task, sender.clone(), r, dnsquery, done, success)
            with trio.move_on_after(0.005 if r.name == "RedisCache" else 0.1):
                await done.wait()

stat_res = None
stats_requests = 0
stats_names = []
stats_fastest = defaultdict(int)
stats_count = defaultdict(int)
stats_time = defaultdict(float)
stats_queries = defaultdict(int)
stats_timeouts = defaultdict(int)

async def stats_task():
    spinner = "⣾⣽⣻⢿⡿⣟⣯⣷"
    spin = 0
    while True:
        spin = (spin + 1) % len(spinner)
        queries = sum(stats_queries.values())
        resolved = sum(stats_count.values())
        ret = f"\0337\033[1;1H\033[1m{spinner[spin]}  "
        ret +=f"Resolved: {resolved}/{stats_requests}  "
        if stat_res:
            client = stat_res.get("NameClient", "⋯")
            try:
                req = str(stat_res["Question"][0]["name"])
            except:
                req = str(stat_res["name"])
            ret +=f"\033[32m[{client}] {req[:50]}\033[K"
        ret += "\033[0m\n\nProvider       Resolved    Fastest / %   Avg.  Queries Timeouts"
        for k in stats_names:
            c = stats_count[k]
            t = f"{1000 * stats_time[k]:4.0f}ms" if stats_time[k] else "   -  "
            p = f"{stats_fastest[k] / queries:5.0%}" if queries else "   - "
            ret += f"\n\033[0;32m{k:15}  \033[1m{c:6d}   {stats_fastest[k]:6d} {p} {t} {stats_queries[k]:8d} {stats_timeouts[k]:8d}\033[K"
        print(ret, end="\033[K\033[0m\0338", flush=True)
        await trio.sleep(0.1)

async def main():
    async def resolve(**dnsquery):
        global stats_requests, stats_names, stat_res
        nonlocal nursery
        stats_requests += 1
        stat_res = dnsquery
        resolvers = [rediscache, *sorted(nclients, key=lambda nc: stats_time[nc.name] or 1)]
        stats_names = [r.name for r in resolvers]
        # RedisCache and Cloudflare cannot answer type ANY requests
        type_any = dnsquery['type'] == 255
        if type_any:
            resolvers = [r for r in resolvers if r.name not in ("RedisCache", "cloudflare")]
        sender, receiver = trio.open_memory_channel(len(nclients))
        async with sender, receiver:
            # Staggered startups of resolving tasks on each suitable provider
            nursery.start_soon(resolve_happy, resolvers, dnsquery, nursery, sender.clone())
            fastest = None
            # Timeout for answering downstream requests
            with trio.move_on_after(5 if type_any else 0.95):
                fastest = await receiver.receive()
                sender.send_nowait(fastest)  # Put the fastest back for cacher
            # Cache any received answers
            nursery.start_soon(cacher_task, receiver.clone())
        if fastest:
            statkey = fastest["NameClient"]
            stat_res = fastest
            stats_fastest[statkey] += 1
            return fastest
        raise trio.TooSlowError

    # Main program runs servers and client connections
    if debug:
        print("\033[?1049h\033[10r\033[10H", end="")
        print(f"Named1 {__version__} debug mode enabled")
    else:
        print(f"Named1 {__version__} starting in normal mode (python -d for debug)")
    nclients = [NameClient(name, servers) for name, servers in providers.items()]
    try:
        async with trio.open_nursery() as nursery:
            if debug:
                nursery.start_soon(stats_task)
            await nursery.start(serve53, ("0.0.0.0", 53), resolve)
            await nursery.start(serve53, ("::", 53), resolve)
            for nclient in nclients: nursery.start_soon(nclient.execute)
    except KeyboardInterrupt:
        if debug: raise  # Traceback plz!
    finally:
        if debug:
            print("\033[?1049l", end="")
        print("Exiting Named1")

trio.run(main)
