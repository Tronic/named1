import trio
from trio.socket import socket, AF_INET, SOCK_DGRAM
from dns import message, rrset, flags, rcode
from nameutil import dnscodes
import io
import json

codes = dnscodes()

async def _process(sock, resolve, data, addr):
    try:
        msg = message.from_wire(data)
    except:
        print(f'Serve53 invalid message from {addr}')
        return
    try:
        do = "1" if msg.flags & flags.DO else "0"
        rr = msg.question[0]
        res = await resolve(name=rr.name, type=rr.rdtype, do=do)
        responses = [res]
        msg = message.make_response(msg)
        #if len(responses) < len(msg.question): msg.rcode = rcode.SERVFAIL
        msg.question, msg.answer = [], []
        for r in responses:
            msg.flags |= flags.from_text(" ".join(k for k, v in r.items() if len(k) == 2 and v is True))
            for m, n in ((msg.question, "Question"), (msg.answer, "Answer"), (msg.authority, "Authority"), (msg.additional, "Additional")):
                for a in r.get(n, []):
                    data = [a['data']] if 'data' in a else []
                    m.append(rrset.from_text(a['name'], a.get('TTL'), "IN", a['type'], *data))
                    #print(f"[{res['NameClient']}] {str(m[-1])[:73]:73s}", end="\r", flush=True)
    except RuntimeError as e:
        print(f'Serve53 error {e!r}')
        msg.flags = flags.QR
        msg.set_rcode(rcode.SERVFAIL)
    await sock.sendto(msg.to_wire(), addr)


async def serve53(addr, resolve):
    with socket(AF_INET, SOCK_DGRAM) as sock:
        await sock.bind(addr)
        async with trio.open_nursery() as resolvers:
            while True:
                data, addr = await sock.recvfrom(8192)
                resolvers.start_soon(_process, sock, resolve, data, addr)
