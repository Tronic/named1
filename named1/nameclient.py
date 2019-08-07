import trio
import trio.socket as socket
import ssl
import json
import h2.connection
from h2.events import ResponseReceived, DataReceived, StreamEnded, StreamReset, ConnectionTerminated
from urllib.parse import quote
import time
import random
from math import inf
from dnserror import WontResolve
from itertools import cycle

class ConnectionDead(RuntimeError): pass

class NameConnection:
    def __init__(self, name, ip, host, path):
        self.name = name
        self.ip = ip
        self.host = host
        self.path = path
        self.streams = {}
        self.successes = self.attempted = 0
        self.send_some, self.can_send = trio.open_memory_channel(0)
        self.exited = trio.Event()
        # SSL context
        self.ssl = ssl.create_default_context()
        self.ssl.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_COMPRESSION
        self.ssl.set_ciphers("ECDHE+AESGCM")
        self.ssl.verify_mode = ssl.CERT_REQUIRED
        self.ssl.set_alpn_protocols(["h2"])

    async def cancel(self):
        self.connection.cancel()
        await self.exited.wait()

    async def execute(self, connections, task_status=trio.TASK_STATUS_IGNORED):
        with trio.CancelScope() as self.connection:
            self.duration = None
            t = time.monotonic()
            print(f"[{self.name}] Trying {self.ip}", end="\033[K\r", flush=True)
            async with await trio.open_tcp_stream(self.ip, 443) as sock:
                sock = trio.SSLStream(sock, server_hostname=self.host, https_compatible=True, ssl_context=self.ssl)
                await sock.do_handshake()
                cert = sock.getpeercert().get('subject')
                cert = cert and {k: v for t in cert for k, v in t}.get('commonName') or 'not validated'
                self.sock = sock
                self.conn = h2.connection.H2Connection(config=h2.config.H2Configuration(
                    client_side=True, header_encoding="UTF-8"
                ))
                self.conn.initiate_connection()
                print(f"[{self.name}] {self.ip} connected, cert {cert}")
                self.reason = None
                connections.add(self)
                try:
                    async with trio.open_nursery() as nursery:
                        nursery.start_soon(self.send_task)
                        task_status.started()
                        await self.recv_task()
                finally:
                    with trio.move_on_after(1) as cleanup:
                        cleanup.shield = True
                        connections.remove(self)
                        self.exited.set()
                        self.duration = time.monotonic() - t
                        if self.reason is None:
                            self.reason = "canceled by us" if self.connection.cancel_called else "disconnected"
                        requests = f"requests OK {self.successes}/{self.attempted}" if self.attempted else "no requests done"
                        print(f"[{self.name}] {self.ip} {self.reason} after {self.duration:.2f} s, {requests}")
                        for stream in list(self.streams.values()): await stream.aclose()

    async def send_task(self):
        async for _ in self.can_send:
            await self.sock.send_all(self.conn.data_to_send())

    async def recv_task(self):
        while True:
            await self.send_some.send(True)
            data = await self.sock.receive_some(8192)
            if not data:
                self.reason = "socket died"
                raise RuntimeError("Socket died")
            for event in self.conn.receive_data(data):
                #print(event)
                if hasattr(event, 'stream_id') and event.stream_id > 0:
                    try:
                        await self.streams[event.stream_id].send(event)
                    except (KeyError, trio.BrokenResourceError):
                        pass  # The stream is already closed, discard remaining packets
                elif isinstance(event, ConnectionTerminated):
                    self.reason = "ConnectionTerminated"
                    raise RuntimeError("Peer ended the connection")

    async def resolve(self, **req):
        if self.exited.is_set(): raise RuntimeError("H2Proto no longer executing")
        while len(self.streams) > 3:
            await trio.sleep(0.01)
        self.connection.deadline = min(self.connection.deadline, trio.move_on_after(2).deadline)
        self.attempted += 1
        num = self.conn.get_next_available_stream_id()
        sender, receiver = trio.open_memory_channel(0)
        async with receiver:
            self.conn.send_headers(num, headers=(
                (":scheme", "https"),
                (":authority", self.host),
                (":method", "GET"),
                (":path", f"{self.path}?{'&'.join(f'{k}={quote(str(v))}' for k, v in req.items())}"),
                ('accept', 'application/dns-json')
            ), end_stream=True)
            self.streams[num] = sender
            await self.send_some.send(True)
            headers, data, done = [], b'', False
            try:
                async for event in receiver:
                    if isinstance(event, Exception): raise event
                    elif isinstance(event, ResponseReceived): headers += event.headers
                    elif isinstance(event, DataReceived): data += event.data
                    elif isinstance(event, StreamEnded): done = True; break
                    elif isinstance(event, StreamReset): break
            finally:
                del self.streams[num]
        if not done: raise RuntimeError(f"Stream {num} terminated prior to request completion")
        headers = dict(headers)
        status, ctype = headers.get(":status"), headers.get('content-type', '')
        if status != "200": raise RuntimeError(f"HTTP {status}: {data}")
        if not 'javascript' in ctype and not 'json' in ctype: raise RuntimeError("Non-JSON response")
        data = json.loads(data.decode("ASCII"))  # RFC 8427 1.1: ASCII only
        if not isinstance(data, dict): raise RuntimeError("Incorrect JSON format received")
        data["NameClient"] = self.name
        if data:
            self.successes += 1
            self.connection.deadline += 10 if self.streams else inf
        return data

class NameClient:
    def __init__(self, name, servers):
        self.name = name
        self.servers = servers
        self.connections = set()

    async def execute(self):
        ip = cycle(self.servers['ipv6'] + self.servers['ipv4'])
        async with trio.open_nursery() as nursery:
            while True:
                while len(self.connections) < 2:
                    connection = NameConnection(self.name, next(ip), self.servers['host'], self.servers['path'])
                    try:
                        await nursery.start(connection.execute, self.connections)
                    except OSError:  # TCP connect() failed
                        await trio.sleep(random.random())
                await trio.sleep(1)

    async def resolve(self, name, type="A", **kwargs):
        if type in (255, "*", "ANY") and self.name == "cloudflare":
            raise WontResolve("Cloudflare won't answer */ANY requests")
        for _ in range(3):
            connections = list(self.connections)
            if not connections:
                await trio.sleep(1)
                continue
            random.shuffle(connections)
            for connection in connections:
                with trio.move_on_after(0.3):
                    return await connection.resolve(name=name, type=type, **kwargs)
        raise RuntimeError("Request timed out")

    def resolve_reverse(self, ip):
        from ipaddress import ip_address
        return self.resolve(ip_address(ip).reverse_pointer, "PTR")
