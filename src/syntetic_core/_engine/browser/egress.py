"""Allowlisted SOCKS5 tunnels. HTTP and TLS bytes belong entirely to the browser."""

import asyncio
import base64
import ipaddress
import json
import logging
import socket
import ssl
from contextlib import suppress
from http.client import HTTPResponse
from io import BytesIO
from time import monotonic
from types import TracebackType
from urllib.parse import urlsplit

from syntetic_core._engine.browser.network_conditions import NetworkPacer
from syntetic_core._engine.config import Settings
from syntetic_core._engine.errors import DomainError
from syntetic_core._engine.proxies import ProxyConfig
from syntetic_core._engine.targets import authorize_url

logger = logging.getLogger(__name__)

Stream = tuple[asyncio.StreamReader, asyncio.StreamWriter]


class TargetProxy:
    def __init__(
        self,
        settings: Settings,
        upstream: ProxyConfig | None = None,
        *,
        explicit_hosts_only: bool = False,
        trace_id: str | None = None,
    ) -> None:
        # Incubation owns its allowlist; stale global/automatic hosts must not leak in.
        incubation_hosts = (settings.incubation_config or {}).get("authorized_hosts")
        self.settings = (
            settings.model_copy(update={"allowed_target_hosts": incubation_hosts})
            if incubation_hosts is not None
            else settings
        )
        from syntetic_core._engine.tracing import trace_id as current_trace

        self.trace_id = trace_id or current_trace.get()
        self.last_ip: str | None = None
        self.upstream = upstream
        self.explicit_hosts_only = explicit_hosts_only or bool(settings.incubation_config)
        self.listener: socket.socket | None = None
        self.accept_task: asyncio.Task[None] | None = None
        self.tasks: set[asyncio.Task[None]] = set()
        self.writers: set[asyncio.StreamWriter] = set()
        self.closing = False
        self.traffic = {"bytes_sent": 0, "bytes_received": 0}
        self.pacer = NetworkPacer()

    async def __aenter__(self) -> "TargetProxy":
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.listener.bind(("127.0.0.1", 0))
            self.listener.listen(128)
            self.listener.setblocking(False)
            self.accept_task = asyncio.create_task(self._accept())
        except BaseException:
            self.listener.close()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        assert self.listener is not None and self.accept_task is not None
        self.closing = True
        self.accept_task.cancel()
        await asyncio.gather(self.accept_task, return_exceptions=True)
        self.listener.close()
        for writer in self.writers:
            writer.close()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.difference_update(tasks)

    def playwright(self) -> dict[str, str]:
        assert self.listener is not None
        port = self.listener.getsockname()[1]
        # Never let the browser's implicit loopback bypass evade the allowlist.
        return {"server": f"socks5://127.0.0.1:{port}", "bypass": "<-loopback>"}

    async def observe_ip(self, url: str) -> str:
        """Probe through the same native upstream tunnel, including SOCKS remote DNS."""
        authorize_url(url, self.settings)
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("An HTTP(S) IP probe is required")
        host = parts.hostname.encode("idna").decode("ascii")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            ip = ipaddress.ip_address(host)
            address = (b"\x01" if ip.version == 4 else b"\x04") + ip.packed
        except ValueError:
            encoded = host.encode("ascii")
            address = b"\x03" + bytes([len(encoded)]) + encoded
        async with asyncio.timeout(self.settings.network_probe_timeout):
            reader, writer = await self._connect(host, port, address + port.to_bytes(2, "big"))
            try:
                if parts.scheme == "https":
                    await writer.start_tls(ssl.create_default_context(), server_hostname=host)
                authority = f"[{host}]" if ":" in host else host
                path = parts.path or "/"
                if parts.query:
                    path += "?" + parts.query
                writer.write(
                    (
                        f"GET {path} HTTP/1.1\r\nHost: {authority}:{port}\r\n"
                        "Connection: close\r\nAccept: application/json\r\n"
                        "X-Automation-Test: True\r\n\r\n"
                    ).encode("ascii")
                )
                await writer.drain()
                body = bytearray()
                while chunk := await reader.read(8192):
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise ValueError("IP probe response exceeds limit")
            finally:
                await self._close(writer)

        # Use the standard parser for status, Content-Length and chunked framing.
        class ProbeSocket:
            def makefile(self, mode: str) -> BytesIO:
                return BytesIO(body)

        with HTTPResponse(ProbeSocket()) as response:  # type: ignore[arg-type]
            response.begin()
            if response.status != 200:
                raise ValueError("IP probe failed")
            observed = ipaddress.ip_address(json.loads(response.read())["ip"])
        if not observed.is_global:
            raise ValueError("IP probe did not return a public exit IP")
        logger.info(
            "proxy_preflight_passed",
            extra={
                "trace_id": self.trace_id,
                "context": {
                    "proxy_id": self.upstream.id if self.upstream else None,
                    "ip": str(observed),
                    "ip_changed": self.last_ip is not None and self.last_ip != str(observed),
                },
            },
        )
        self.last_ip = str(observed)
        return str(observed)

    async def _accept(self) -> None:
        assert self.listener is not None
        loop = asyncio.get_running_loop()
        while not self.closing:
            client, _ = await loop.sock_accept(self.listener)
            if len(self.tasks) >= 256:
                client.close()
                continue
            task = asyncio.create_task(self._client(client))
            self.tasks.add(task)

            # Close even if cancellation occurs before the coroutine starts.
            def close_client(_: asyncio.Task[None], client: socket.socket = client) -> None:
                client.close()

            task.add_done_callback(close_client)
            task.add_done_callback(self.tasks.discard)

    async def _client(self, client: socket.socket) -> None:
        # Owning the accepted socket also guarantees closure on Windows 3.12,
        # where a peer RST can interrupt Proactor transport/server bookkeeping.
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.open_connection(sock=client, limit=16384)
            self.writers.add(writer)
            await self._handle(reader, writer)
        except OSError:
            pass
        finally:
            if writer is not None:
                self.writers.discard(writer)
            client.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        remote: asyncio.StreamWriter | None = None
        connected = False
        started = monotonic()
        host = None
        try:
            async with asyncio.timeout(self.settings.navigation_timeout + 1):
                version, count = await reader.readexactly(2)
                methods = await reader.readexactly(count)
                if version != 5 or 0 not in methods:
                    writer.write(b"\x05\xff")
                    await writer.drain()
                    return
                writer.write(b"\x05\x00")
                await writer.drain()
                version, command, reserved, kind = await reader.readexactly(4)
                if (version, command, reserved) != (5, 1, 0):
                    raise ValueError("Only SOCKS5 CONNECT is supported")
                host, address = await self._address(reader, kind)
                port_bytes = await reader.readexactly(2)
                port = int.from_bytes(port_bytes, "big")
                authority = f"[{host}]" if ":" in host else host
                try:
                    authorize_url(f"http://{authority}:{port}", self.settings)
                except DomainError:
                    if self.explicit_hosts_only or not self.settings.allow_public_resources:
                        raise
                if (
                    self.settings.allow_public_resources or self.settings.incubation_config
                ) and host not in self.settings.trusted_local_target_hosts:
                    records = await asyncio.get_running_loop().getaddrinfo(
                        host,
                        port,
                        type=socket.SOCK_STREAM,
                    )
                    addresses = [ipaddress.ip_address(record[4][0]) for record in records]
                    if not addresses or any(not value.is_global for value in addresses):
                        raise DomainError("Private resource address is not allowed")
                    # Pin the checked address for direct and upstream connections.
                    target = next(
                        (value for value in addresses if value.version == 4), addresses[0]
                    )
                    host = str(target)
                    address = (b"\x01" if target.version == 4 else b"\x04") + target.packed
                if self.pacer.condition.offline:
                    raise ConnectionResetError("Planned test network outage")
                if self.pacer.condition.latency_ms:
                    await asyncio.sleep(self.pacer.condition.latency_ms / 1000)
                peer, remote = await self._connect(host, port, address + port_bytes)
                writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
                await writer.drain()
                connected = True
                logger.info(
                    "socks_handshake_completed",
                    extra={
                        "trace_id": self.trace_id,
                        "context": {
                            "host": host,
                            "port": port,
                            "duration_ms": round((monotonic() - started) * 1000),
                            "proxy_id": self.upstream.id if self.upstream else None,
                        },
                    },
                )
            await self._relay(reader, writer, peer, remote)
        except (
            DomainError,
            OSError,
            ValueError,
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ) as exc:
            logger.warning(
                "target_guard_blocked"
                if isinstance(exc, DomainError)
                else "socks_handshake_failed",
                extra={
                    "trace_id": self.trace_id,
                    "context": {
                        "host": host,
                        "error_type": type(exc).__name__,
                        "duration_ms": round((monotonic() - started) * 1000),
                    },
                },
            )
            if not connected:
                writer.write(b"\x05\x02\x00\x01" + b"\x00" * 6)
                with suppress(OSError):
                    await writer.drain()
        finally:
            try:
                await self._close(remote)
            finally:
                await self._close(writer)

    @staticmethod
    async def _address(reader: asyncio.StreamReader, kind: int) -> tuple[str, bytes]:
        if kind == 3:
            size = await reader.readexactly(1)
            value = await reader.readexactly(size[0])
            host = value.decode("ascii")
            # Domain bytes must not introduce URL syntax into the authorization check.
            if (
                not host
                or any(c in host for c in "/:@?#[]\\%")
                or any(ord(c) <= 32 or ord(c) == 127 for c in host)
            ):
                raise ValueError("Invalid SOCKS hostname")
            return host, b"\x03" + size + value
        if kind not in {1, 4}:
            raise ValueError("Invalid SOCKS address type")
        value = await reader.readexactly(4 if kind == 1 else 16)
        return str(ipaddress.ip_address(value)), bytes([kind]) + value

    async def _connect(self, host: str, port: int, address: bytes) -> Stream:
        if self.upstream is None:
            return await asyncio.open_connection(host, port)
        proxy = urlsplit(self.upstream.server)
        reader, writer = await asyncio.open_connection(
            proxy.hostname,
            proxy.port,
            ssl=ssl.create_default_context() if proxy.scheme == "https" else None,
            limit=16384,
        )
        try:
            if proxy.scheme == "socks5":
                writer.write(b"\x05\x01\x00")
                await writer.drain()
                if await reader.readexactly(2) != b"\x05\x00":
                    raise ValueError("Upstream SOCKS negotiation failed")
                writer.write(b"\x05\x01\x00" + address)
                await writer.drain()
                version, status, reserved, kind = await reader.readexactly(4)
                if (version, status, reserved) != (5, 0, 0):
                    raise ValueError("Upstream SOCKS connection failed")
                await self._address(reader, kind)
                await reader.readexactly(2)
            else:
                authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
                headers = f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
                if self.upstream.username is not None or self.upstream.password is not None:
                    username = self.upstream.username
                    password = self.upstream.password
                    credentials = (
                        f"{username.get_secret_value() if username else ''}:"
                        f"{password.get_secret_value() if password else ''}"
                    )
                    token = base64.b64encode(credentials.encode()).decode("ascii")
                    headers += f"Proxy-Authorization: Basic {token}\r\n"
                writer.write((headers + "\r\n").encode("ascii"))
                await writer.drain()
                response = await reader.readuntil(b"\r\n\r\n")
                status_line = response.split(b"\r\n", 1)[0].split(b" ")
                if (
                    len(status_line) < 2
                    or status_line[0] not in {b"HTTP/1.0", b"HTTP/1.1"}
                    or status_line[1] != b"200"
                ):
                    raise ValueError("Upstream CONNECT failed")
            return reader, writer
        except BaseException:
            await self._close(writer)
            raise

    async def _relay(
        self,
        client: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        peer: asyncio.StreamReader,
        peer_writer: asyncio.StreamWriter,
    ) -> None:
        async def copy(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter, counter: str
        ) -> None:
            while data := await reader.read(16384):
                started = monotonic()
                await self.pacer.wait(len(data), counter)
                writer.write(data)
                self.traffic[counter] += len(data)
                await writer.drain()
                from syntetic_core._engine.sre import add, observe

                direction = "outgoing" if counter == "bytes_sent" else "incoming"
                add(f"egress_{direction}_bytes_total", len(data))
                observe(f"egress_{direction}_frame", monotonic() - started)
            if writer.can_write_eof():
                writer.write_eof()
                await writer.drain()
            else:
                writer.close()

        tasks = [
            asyncio.create_task(copy(client, peer_writer, "bytes_sent")),
            asyncio.create_task(copy(peer, client_writer, "bytes_received")),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    async def _close(writer: asyncio.StreamWriter | None) -> None:
        if writer is not None:
            writer.close()
            with suppress(OSError, TimeoutError):
                async with asyncio.timeout(1):
                    await writer.wait_closed()
