import warnings
warnings.simplefilter("ignore", DeprecationWarning)  # Silence H2 warnings about importing ABCs from collections

import trio
from nameclient import NameClient
from serve53 import serve53
from rediscache import Cacher
from dnserror import WontResolve

providers = {
    "cloudflare": {
        'host': 'cloudflare-dns.com',
        'path': '/dns-query',
        'ipv4': ('1.0.0.1', '1.1.1.1'),
        'ipv6': ('2606:4700:4700::1111', '2606:4700:4700::1001'),
    },
    "google": {
        'host': 'dns.google',
        'path': '/resolve',
        'ipv4': ["8.8.4.4", "8.8.8.8"],
        'ipv6': ['2001:4860:4860::8844', '2001:4860:4860::8888'],
    },
}

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
        except WontResolve: pass  # Quiet decline from resolver
        except RuntimeError as e:
            print(f"{query.__qualname__} {e!r}")

async def main():
    nclients = [NameClient(name, servers) for name, servers in providers.items()]
    cacher = Cacher()
    async def resolve(**dnsquery):
        nonlocal nursery
        with trio.move_on_after(0.01):
            try: return await cacher.resolve(**dnsquery)
            except WontResolve: pass
        sender, receiver = trio.open_memory_channel(1000)
        async with sender, receiver:
            for nclient in nclients:
                nursery.start_soon(resolve_task, sender.clone(), nclient.resolve(**dnsquery))
            fastest = await receiver.receive()
            # Put fastest back, to cache everything (later)
            await sender.send(fastest)
            nursery.start_soon(cacher_task, receiver.clone(), cacher)
            return fastest
    try:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(cacher.execute)
            nursery.start_soon(serve53, ("0.0.0.0", 53), resolve)
            for nclient in nclients: nursery.start_soon(nclient.execute)
    finally:
        print("Exiting")

trio.run(main)
