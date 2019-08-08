import sys

import trio

from named1 import providers
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
            with trio.move_on_after(5):
                sender.send_nowait(await query)
        except trio.BrokenResourceError: pass  # We are late, no-one's listening
        except WontResolve as e:
            if sys.flags.dev_mode: print(e)
        except RuntimeError as e:
            print(f"{query.__qualname__} {e!r}")

async def main():
    nclients = [NameClient(name, servers) for name, servers in providers.items()]
    async def resolve(**dnsquery):
        nonlocal nursery, cacher
        if cacher:
            with trio.move_on_after(0.01):
                try: return await cacher.resolve(**dnsquery)
                except WontResolve: pass
        sender, receiver = trio.open_memory_channel(1000)
        async with sender, receiver:
            for nclient in nclients:
                nursery.start_soon(resolve_task, sender.clone(), nclient.resolve(**dnsquery))
            # Request timeout: slightly under a second so it finishes before downstream re-send
            with trio.fail_after(0.95):
                fastest = await receiver.receive()
            if cacher:
                await sender.send(fastest)  # Put the fastest back for cacher
                nursery.start_soon(cacher_task, receiver.clone(), cacher)
            return fastest
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
        if sys.flags.dev_mode: raise  # Traceback plz!
    finally:
        print("Exiting")

trio.run(main)
