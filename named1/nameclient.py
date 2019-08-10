import itertools
import json
import math
import random
import ssl
import time
from urllib.parse import quote

import h2.connection
import trio
import trio.socket as socket
from h2.events import ResponseReceived, DataReceived, StreamEnded, StreamReset, ConnectionTerminated

from named1.dnserror import WontResolve

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
                        task_status.started()
                        nursery.start_soon(self.send_task)
                        await self.recv_task()
                finally:
                    with trio.move_on_after(1) as cleanup:
                        cleanup.shield = True
                        connections.remove(self)
                        self.exited.set()
                        self.duration = time.monotonic() - t
                        if self.reason is None:
                            self.reason = "we canceled" if self.connection.cancel_called else "disconnected"
                        requests = f"answered {self.successes}/{self.attempted}" if self.attempted else "no requests done"
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
        if self.exited.is_set(): raise RuntimeError("NameConnection no longer executing")
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
            # Extend deadline; Cloudflare and Google die after about 200 so don't bother after 100.
            if self.attempted < 100:
                self.connection.deadline += 10 if self.streams else math.inf
        return data

class NameClient:
    def __init__(self, name, servers):
        self.name = name
        self.servers = servers
        self.connections = set()

    async def execute(self):
        ip = itertools.cycle(self.servers['ipv6'] + self.servers['ipv4'])
        async def run_connection(task_status):
            nonlocal ip, cancel_scope
            connection = NameConnection(self.name, next(ip), self.servers['host'], self.servers['path'])
            try:
                await connection.execute(self.connections, task_status=task_status)
            except (OSError, trio.BrokenResourceError, RuntimeError): pass  # TODO: Better handling of various disconnections
            if connection.successes == 0:
                # Scatter reconnection times after disconnection
                await trio.sleep(1 + random.random())
            cancel_scope.cancel()  # Trigger reconnection

        # Try to keep two connections alive at all times
        async with trio.open_nursery() as nursery:
            while True:
                with trio.CancelScope() as cancel_scope:
                    while len(self.connections) < 2:
                        # Returns once NameConnection has added itself to self.connections, or connection fails
                        await nursery.start(run_connection)
                    await trio.sleep_forever()

    async def resolve(self, name, type="A", **kwargs):
        """Try resolving using any available connections. New requests are made
        at short intervals if other servers are available, without interrupting
        prior requests. The first reply is returned and then all remaining
        requests are terminated. Total timeout 0.9 seconds."""
        tried_connections = set()
        sender, receiver = trio.open_memory_channel(1000)
        request_exceptions = []
        async def resolve_task(resolver):
            try: sender.send_nowait(await resolver)
            except RuntimeError as e: request_exceptions.append(e)
        async with trio.open_nursery() as nursery, receiver:
            for delay in (0.2, 1, 2, 4):  # Retry until deadline
                connections = self.connections - tried_connections
                if connections:
                    connection = random.choice(list(connections))
                    tried_connections.add(connection)
                    nursery.start_soon(resolve_task, connection.resolve(name=name, type=type, **kwargs))
                with trio.move_on_after(delay):
                    return await receiver.receive()
        reason = f"requests unanswered {len(tried_connections)}" if tried_connections else "waiting for connection"
        raise WontResolve(f"[{self.name}] {name} timeout {reason}", request_exceptions)

    def resolve_reverse(self, ip):
        from ipaddress import ip_address
        return self.resolve(ip_address(ip).reverse_pointer, "PTR")
