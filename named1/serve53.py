import trio
from dns import edns, message, rrset, flags, rcode
from trio.socket import socket, AF_INET, AF_INET6, SO_REUSEPORT, SOCK_DGRAM, SOL_SOCKET

from named1 import debug

async def _process(sock, resolve, data, addr):
    try:
        msg = message.from_wire(data)
    except:
        print(f'[Serve53] invalid message from {addr}')
        return
    try:
        do = "1" if msg.flags & flags.DO else "0"
        rr = msg.question[0]
        res = await resolve(name=rr.name, type=rr.rdtype, do=do)
        want_nsid = edns.NSID in (o.otype for o in msg.options)
        msg = message.make_response(msg)
        msg.set_rcode(res.get('Status', rcode.NOERROR))
        msg.question, msg.answer = [], []
        msg.flags |= flags.from_text(" ".join(k for k, v in res.items() if len(k) == 2 and v is True))
        for m, n in ((msg.question, "Question"), (msg.answer, "Answer"), (msg.authority, "Authority"), (msg.additional, "Additional")):
            for a in res.get(n, []):
                data = [a['data']] if 'data' in a else []
                m.append(rrset.from_text(a['name'], a.get('TTL'), "IN", a['type'], *data))
                if debug:
                    print(f"\033[32m[{res['NameClient']}] {str(m[-1])[:73]:73s}", end="\r\033[0m", flush=True)
        if want_nsid:
            comment = res.get("Comment")
            nsid = f"named1/{res['NameClient']}{': ' + comment if comment else ''}"
            msg.options.append(edns.GenericOption(edns.NSID, nsid.encode()))
    except trio.TooSlowError: # Don't die on timeout but report back a failure
        msg.flags = flags.QR
        msg.set_rcode(rcode.SERVFAIL)
    await sock.sendto(msg.to_wire(), addr)


async def serve53(addr, resolve, task_status=trio.TASK_STATUS_IGNORED):
    with socket(AF_INET6 if ":" in addr[0] else AF_INET, SOCK_DGRAM) as sock:
        try:
            sock.setsockopt(SOL_SOCKET, SO_REUSEPORT, 1)
            await sock.bind(addr)
            print(f"[Serve53] listening on {addr}")
        except OSError as e:
            if e.errno == 13: reason = "permission denied (run with sudo?)"
            elif e.errno in (48, 49): reason = "already in use (is another DNS server running?)"
            else: reason = str(e)
            print(f"[Serve53] {addr} {reason}")
            return
        finally:
            task_status.started()
        async with trio.open_nursery() as resolvers:
            while True:
                data, addr = await sock.recvfrom(8192)
                resolvers.start_soon(_process, sock, resolve, data, addr)
