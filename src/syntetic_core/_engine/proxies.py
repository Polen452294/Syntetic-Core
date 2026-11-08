import asyncio
import ipaddress
import json
import re
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from syntetic_core._engine.errors import DomainError, ProxyUnavailableError

if TYPE_CHECKING:
    from syntetic_core._engine.config import Settings


class ProxyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str
    server: str
    username: SecretStr | None = None
    password: SecretStr | None = None
    country: str | None = None
    region: str | None = None
    provider: str | None = None
    asn: int | None = None
    kind: Literal["residential", "mobile", "datacenter", "unknown"] = "unknown"
    # Rotation URLs often contain provider tokens; keep them out of public metadata.
    change_ip_url: str | None = Field(default=None, repr=False)

    @field_validator("change_ip_url")
    @classmethod
    def valid_change_ip_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.fragment
        ):
            raise ValueError("Proxy rotation requires an HTTP or HTTPS URL without userinfo")
        # Validate malformed ports at the configuration boundary.
        _ = parts.port
        return value

    @field_validator("server")
    @classmethod
    def valid_server(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https", "socks5"} or not parts.hostname:
            raise ValueError("Proxy requires an HTTP, HTTPS or SOCKS5 URL")
        if (
            parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise ValueError("Proxy credentials belong in environment secret fields")
        if parts.port is None:
            raise ValueError("Proxy port is required")
        return value

    @model_validator(mode="after")
    def socks_auth(self) -> "ProxyConfig":
        if self.server.startswith("socks5:") and (self.username or self.password):
            raise ValueError("Playwright does not support authenticated SOCKS5 proxies")
        return self

    def playwright(self) -> dict[str, str]:
        result = {"server": self.server}
        for key in ("username", "password"):
            secret = getattr(self, key)
            if secret is not None:
                result[key] = secret.get_secret_value()
        return result

    def metadata(self) -> dict[str, Any]:
        return self.model_dump(exclude={"username", "password", "change_ip_url"})

    def get_secure_payload(self) -> dict[str, Any]:
        """Unmask credentials only for private IPC or an authenticated secret response."""
        return {**self.metadata(), **self.playwright()}

    def endpoint_key(self) -> str:
        """Identify an address/port independently of proxy IDs and credentials."""
        parts = urlsplit(self.server)
        host = (parts.hostname or "").rstrip(".")
        try:
            host = str(ipaddress.ip_address(host))
        except ValueError:
            host = host.encode("idna").decode("ascii").lower()
        physical = f"endpoint:{host}:{parts.port}"
        _, separator, session = self.id.rpartition("~session~")
        if separator and re.fullmatch(r"[a-f0-9]{32}", session):
            physical += f":session:{session}"
        return sha256(physical.encode()).hexdigest()

    def sticky_session(self, token: str) -> "ProxyConfig":
        """Opt-in logical session; provider acceptance still requires preflight."""
        if not re.fullmatch(r"[a-f0-9]{32}", token) or "~session~" in self.id:
            raise ValueError("Invalid sticky session identifier")
        if self.username is None:
            raise ProxyUnavailableError("Sticky username sessions require proxy authentication")
        return self.model_copy(
            update={
                "id": f"{self.id}~session~{token}",
                "username": SecretStr(f"{self.username.get_secret_value()}-session-{token}"),
            }
        )


class ProxyPortPoolConfig(ProxyConfig):
    """One provider account with a contiguous range of independent sticky ports."""

    port_count: int = Field(default=1000, ge=1, le=1000)

    @model_validator(mode="after")
    def valid_range(self) -> "ProxyPortPoolConfig":
        port = urlsplit(self.server).port
        if port is None or port + self.port_count - 1 > 65535:
            raise ValueError("Proxy port range exceeds 65535")
        return self

    def expand(self) -> list[ProxyConfig]:
        parts = urlsplit(self.server)
        assert parts.port is not None and parts.hostname is not None
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        template = self.model_dump(exclude={"id", "server", "port_count"})
        return [
            ProxyConfig(
                **template,
                id=f"{self.id}-{port}",
                server=parts._replace(netloc=f"{host}:{port}").geturl(),
            )
            for port in range(parts.port, parts.port + self.port_count)
        ]


class _ASocksEntry(BaseModel):
    """Export fields are authoritative; template_string is deliberately ignored."""

    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    login: SecretStr = Field(min_length=1)
    password: SecretStr = Field(min_length=1)
    protocol: Literal["http", "https", "socks5"]

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        if any(char.isspace() or char in "/@?#\\[]" for char in value):
            raise ValueError("Invalid proxy host")
        if ":" in value:
            ipaddress.IPv6Address(value)
        return value

    def proxy(
        self,
        suffix: Literal["-ru-moscow", "+RU+Moscow"] = "-ru-moscow",
    ) -> ProxyConfig:
        login = self.login.get_secret_value()
        # Normalize exports that already contain one of our targeting suffixes.
        for previous in ("_country-ru_city-moscow", "-ru-moscow", "+RU+Moscow"):
            if login.endswith(previous):
                login = login.removesuffix(previous)
                break
        login += suffix
        host = f"[{self.host}]" if ":" in self.host else self.host
        server = f"{self.protocol}://{host}:{self.port}"
        identity = sha256(f"{server}\0{login}".encode()).hexdigest()
        return ProxyConfig(
            id=f"asocks-{identity}",
            server=server,
            username=SecretStr(login),
            password=self.password,
            provider="asocks",
            country="RU",
            region="Moscow",
        )


class ProxyManager:
    def __init__(
        self, proxies: list[ProxyConfig], required: bool = False, *, direct: bool = False
    ) -> None:
        self.proxies = {proxy.id: proxy for proxy in proxies}
        if len(self.proxies) != len(proxies):
            raise ProxyUnavailableError("Duplicate proxy IDs")
        self.required = required
        self.direct = direct

        self._refresh_lock = asyncio.Lock()

    async def refresh_asocks_pool(
        self,
        url: str,
        settings: "Settings",
        *,
        targeting_suffix: Literal["-ru-moscow", "+RU+Moscow"] = "-ru-moscow",
    ) -> list[ProxyConfig]:
        """Replace ASocks entries in this manager only after every native probe succeeds.

        Validate the complete export, then probe in bounded batches. A failed
        batch aborts publication, leaving the previous pool intact. Cancellation
        also leaves the pool intact. Persistence belongs to the caller.
        """
        # Local import avoids the Settings -> proxies -> egress -> Settings cycle.
        from syntetic_core._engine.browser.egress import TargetProxy

        probe_url = settings.network_probe_url
        if not probe_url:
            raise ProxyUnavailableError("ASocks refresh requires NETWORK_PROBE_URL")
        async with self._refresh_lock:
            try:
                if targeting_suffix not in {"-ru-moscow", "+RU+Moscow"}:
                    raise ValueError("Unsupported targeting suffix")
                parts = urlsplit(url)
                if (
                    parts.scheme != "https"
                    or not parts.hostname
                    or parts.username
                    or parts.password
                    or parts.fragment
                ):
                    raise ValueError("Invalid export URL")
                _ = parts.port
                async with asyncio.timeout(settings.asocks_pool_timeout):
                    async with httpx.AsyncClient(
                        timeout=settings.asocks_pool_timeout,
                        trust_env=False,
                        follow_redirects=False,
                    ) as client:
                        async with client.stream(
                            "GET",
                            url,
                            headers={"Accept": "application/json"},
                        ) as response:
                            if response.status_code != 200:
                                raise ValueError("Export failed")
                            body = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                body.extend(chunk)
                                if len(body) > settings.asocks_pool_max_bytes:
                                    raise ValueError("Export exceeds size limit")
                    records = json.loads(body)
                    if (
                        not isinstance(records, list)
                        or not records
                        or len(records) > settings.asocks_pool_max_entries
                    ):
                        raise ValueError("Invalid export entries")
                    candidates = [
                        _ASocksEntry.model_validate(row).proxy(targeting_suffix) for row in records
                    ]
                    incoming = {proxy.id: proxy for proxy in candidates}
                    if len(incoming) != len(candidates):
                        raise ValueError("Duplicate export entries")
                    preserved = {
                        key: proxy
                        for key, proxy in self.proxies.items()
                        if proxy.provider != "asocks"
                    }
                    if incoming.keys() & preserved.keys():
                        raise ValueError("Export ID conflicts with configured proxy")

                async def probe(proxy: ProxyConfig) -> None:
                    observed = await TargetProxy(settings, proxy).observe_ip(
                        probe_url,
                    )
                    if not ipaddress.ip_address(observed).is_global:
                        raise ValueError("Probe returned a nonpublic IP")

                for offset in range(0, len(candidates), 16):
                    # Await the whole batch before returning, including on failure.
                    results = await asyncio.gather(
                        *(probe(proxy) for proxy in candidates[offset : offset + 16]),
                        return_exceptions=True,
                    )
                    for result in results:
                        if isinstance(result, BaseException):
                            raise result
                self.proxies = {**preserved, **incoming}
                return candidates
            except (
                ValueError,
                KeyError,
                OSError,
                TimeoutError,
                DomainError,
                httpx.HTTPError,
                httpx.InvalidURL,
            ):
                # Provider payloads and exception strings may contain credentials.
                raise ProxyUnavailableError("ASocks refresh failed; pool unchanged") from None

    def get(self, proxy_id: str | None) -> ProxyConfig | None:
        if self.direct:
            return None
        proxy = self.proxies.get(proxy_id) if proxy_id else None
        if proxy is None and proxy_id:
            base, separator, token = proxy_id.rpartition("~session~")
            if separator and re.fullmatch(r"[a-f0-9]{32}", token) and base in self.proxies:
                proxy = self.proxies[base].sticky_session(token)
        if (proxy_id or self.required) and proxy is None:
            raise ProxyUnavailableError("Configured proxy is missing; direct fallback is forbidden")
        return proxy

    def select(self, persona: Any, state: dict[str, Any], now: float) -> ProxyConfig | None:
        pool = persona.network.proxy_pool
        if not pool:
            return self.get(persona.proxy_id)
        # Validate every pool member: a typo must never silently change routing.
        for proxy_id in pool:
            self.get(proxy_id)
        previous = state.get("proxy_id")
        if (
            previous in pool
            and now - state.get("identity_since", 0) < persona.network.min_identity_seconds
        ):
            return self.get(previous)
        if persona.network.selection == "sticky":
            index = int.from_bytes(sha256(persona.id.encode()).digest()[:8], "big") % len(pool)
        else:
            index = (pool.index(previous) + 1) % len(pool) if previous in pool else 0
        return self.get(pool[index])

    async def check(self, proxy: ProxyConfig) -> None:
        parts = urlsplit(proxy.server)
        try:
            async with asyncio.timeout(5):
                _, writer = await asyncio.open_connection(parts.hostname, parts.port)
                writer.close()
                await writer.wait_closed()
        except (OSError, TimeoutError):
            raise ProxyUnavailableError("Proxy endpoint is unreachable") from None

    async def resolve(self, proxy_id: str | None) -> ProxyConfig | None:
        proxy = self.get(proxy_id)
        if proxy is not None:
            await self.check(proxy)
        return proxy
