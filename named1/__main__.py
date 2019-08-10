import trio

from named1 import __version__, debug, providers
from named1.dnserror import WontResolve
from named1.nameclient import NameClient
from named1.rediscache import Cacher
from named1.serve53 import serve53

async def cacher_task(receiver, cacher):
    with trio.move_on_after(10):
        async with receiver:
            async for res in receiver:
                await cacher.cache(res)
        return
    print("RedisCacher timed out!")

async def resolve_task(sender, query):
    async with sender:
        try:
            # This can be longer running than interactive requests
            with trio.move_on_after(5): sender.send_nowait(await query)
        except trio.BrokenResourceError: pass  # We are late, no-one's listening
        except WontResolve: pass  # Resolver can't handle it

async def main():
    async def resolve(**dnsquery):
        nonlocal nursery, cacher
        type_any = dnsquery['type'] == 255
        # Try getting answer from cache
        if cacher and not type_any:
            with trio.move_on_after(0.01):
                try: return await cacher.resolve(**dnsquery)
                except WontResolve: pass
        # External lookup
        sender, receiver = trio.open_memory_channel(len(nclients))
        async with sender, receiver:
            # Start a resolving task on each suitable provider
            for nclient in nclients:
                if type_any and nclient.name == "cloudflare": continue  # Cloudflare won't answer type ANY
                nursery.start_soon(resolve_task, sender.clone(), nclient.resolve(**dnsquery))
            fastest = None
            # Timeout for answering downstream requests
            with trio.move_on_after(5 if type_any else 0.95):
                fastest = await receiver.receive()
                sender.send_nowait(fastest)  # Put the fastest back for cacher
            # Cache any received answers
            if cacher: nursery.start_soon(cacher_task, receiver.clone(), cacher)
            if fastest: return fastest
            raise trio.TooSlowError

    # Main program runs servers and client connections
    print(f"Named1 {__version__}", "debug mode enabled" if debug else "starting in normal mode (python -d for debug)")
    nclients = [NameClient(name, servers) for name, servers in providers.items()]
    try:
        async with trio.open_nursery() as nursery:
            try:
                cacher = None
                with trio.move_on_after(0.1):
                    cacher_ = Cacher()
                    await nursery.start(cacher_.execute)
                    cacher = cacher_
                    print("[RedisCache] DNS caching enabled")
            except OSError as e: print(e)
            if not cacher: print(f"[RedisCache] Cannot connect, caching disabled")
            await nursery.start(serve53, ("0.0.0.0", 53), resolve)
            await nursery.start(serve53, ("::", 53), resolve)
            for nclient in nclients: nursery.start_soon(nclient.execute)
    except KeyboardInterrupt:
        if debug: raise  # Traceback plz!
    finally:
        print("Exiting Named1")

trio.run(main)
