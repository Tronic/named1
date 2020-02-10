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

async def resolve_task(sender, name, query, start_delay):
    async with sender:
        if start_delay:
            await trio.sleep(start_delay)
        try:
            # This can be longer running than interactive requests
            with trio.move_on_after(5):
                sender.send_nowait(await query)
                return
        except trio.BrokenResourceError: pass  # We are late, no-one's listening
        except WontResolve: return  # Resolver can't handle it
    stats_timeouts[name] += 1

stats_count = defaultdict(int)
stats_time = defaultdict(float)
stats_timeouts = defaultdict(int)

async def stats_task():
    spinner = "⣾⣽⣻⢿⡿⣟⣯⣷"
    spin = 0
    while True:
        spin = (spin + 1) % len(spinner)
        requests = sum(stats_count.values())
        ret = f"\0337\033[2;1H\033[1m{spinner[spin]}  "
        if requests > 0:
            ret +=f"Requests: {requests}  "
            for k in sorted(stats_count.keys()):
                c = stats_count[k]
                t = stats_time[k] / c
                ret += f"   {c / requests:.0%}/{1000 * t:.0f}ms {k}"
                if stats_timeouts[k]:
                    ret += f" ({stats_timeouts[k]} timeouts)"
        else:
            ret += "No requests served"
        print(ret, end="\033[K\033[0m\0338", flush=True)
        await trio.sleep(0.1)

async def main():
    async def resolve(**dnsquery):
        global stats_cachemiss
        nonlocal nursery
        start_time = trio.current_time()
        type_any = dnsquery['type'] == 255
        sender, receiver = trio.open_memory_channel(len(nclients))
        async with sender, receiver:
            random.shuffle(nclients)
            resolvers = [rediscache, *nclients]
            # RedisCache and Cloudflare cannot answer ANY requests
            if type_any:
                resolvers = [r for r in resolvers if r.name not in ("RedisCache", "cloudflare")]
            # Start a resolving task on each suitable provider
            delay = 0.0
            for r in resolvers:
                if type_any and nclient.name == "cloudflare": continue  # Cloudflare won't answer type ANY
                nursery.start_soon(resolve_task, sender.clone(), r.name, r.resolve(**dnsquery), delay)
                delay += 0.01
            fastest = None
            # Timeout for answering downstream requests
            with trio.move_on_after(5 if type_any else 0.95):
                fastest = await receiver.receive()
                sender.send_nowait(fastest)  # Put the fastest back for cacher
            # Cache any received answers
            nursery.start_soon(cacher_task, receiver.clone())
            statkey = fastest["NameClient"] if fastest else "Timeout"
            stats_count[statkey] += 1
            stats_time[statkey] += trio.current_time() - start_time
            if fastest: return fastest
            raise trio.TooSlowError

    # Main program runs servers and client connections
    if debug:
        print("\033[?1049h\033[3r\033[3H", end="")
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
