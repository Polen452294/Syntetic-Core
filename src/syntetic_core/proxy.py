"""Provider-neutral IP rotation, confirmed through the actual proxy tunnel."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from syntetic_core._engine.browser.egress import TargetProxy
from syntetic_core._engine.config import Settings
from syntetic_core._engine.errors import ProxyUnavailableError
from syntetic_core._engine.profile_lock import ProfileLock
from syntetic_core._engine.proxies import ProxyConfig
from syntetic_core._engine.targets import authorize_url


class RotationProvider(Protocol):
    """Implement one provider request; the core owns locking and IP verification."""

    async def rotate(self, proxy: ProxyConfig) -> None: ...


class HttpRotationProvider(BaseModel):
    """Configurable HTTP adapter; success is never inferred from a provider's IP field."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    url: SecretStr = Field(repr=False)
    method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"
    headers: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    json_body: dict[str, Any] | None = Field(default=None, repr=False)
    timeout_seconds: float = Field(default=15, gt=0, le=120, allow_inf_nan=False)
    success_field: str | None = None
    success_value: str | int | bool = True

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: SecretStr) -> SecretStr:
        parts = urlsplit(value.get_secret_value())
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.fragment
        ):
            raise ValueError("Rotation API requires HTTPS without userinfo or fragment")
        _ = parts.port
        return value

    async def rotate(self, proxy: ProxyConfig) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, trust_env=False, follow_redirects=False
            ) as client:
                async with client.stream(
                    self.method,
                    self.url.get_secret_value(),
                    headers={key: value.get_secret_value() for key, value in self.headers.items()},
                    json=self.json_body,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        raise ValueError("Provider rejected rotation")
                    if self.success_field:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 65536:
                                raise ValueError("Provider response too large")
                        import json

                        result: Any = json.loads(body)
                        for part in self.success_field.split("."):
                            result = result[part]
                        if (
                            type(result) is not type(self.success_value)
                            or result != self.success_value
                        ):
                            raise ValueError("Provider did not confirm success")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ProxyUnavailableError("IP rotation API failed") from None


@dataclass(frozen=True)
class RotationResult:
    proxy_id: str
    previous_ip: str
    current_ip: str


def channel_lock(root: Path, proxy: ProxyConfig, channel_id: str | None = None) -> ProfileLock:
    """Same endpoint or explicitly shared modem uses one cross-process local fence."""
    key = channel_id or proxy.endpoint_key()
    digest = hashlib.sha256(key.encode()).hexdigest()
    return ProfileLock(root / ".network" / digest / "browser-data", settings=Settings())


async def observe_ip(settings: Settings, proxy: ProxyConfig, probe_url: str) -> str:
    authorize_url(probe_url, settings)
    try:
        value = await TargetProxy(settings, proxy).observe_ip(probe_url)
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise ValueError("Probe did not return a public IP")
        return str(address)
    except (ValueError, OSError, TimeoutError, httpx.HTTPError):
        raise ProxyUnavailableError("Proxy IP verification failed") from None


async def rotate_and_verify(
    settings: Settings,
    proxy: ProxyConfig,
    provider: RotationProvider,
    probe_url: str,
    *,
    timeout_seconds: float = 60,
    poll_seconds: float = 2,
) -> RotationResult:
    if not 0 < timeout_seconds <= 300 or not 0 < poll_seconds <= 30:
        raise ValueError("Invalid rotation timeout or polling interval")
    try:
        async with asyncio.timeout(timeout_seconds):
            previous = await observe_ip(settings, proxy, probe_url)
            try:
                await provider.rotate(proxy)
            except Exception:
                raise ProxyUnavailableError("IP rotation provider failed") from None
            deadline = monotonic() + timeout_seconds
            while monotonic() < deadline:
                try:
                    current = await observe_ip(settings, proxy, probe_url)
                    if current != previous:
                        return RotationResult(proxy.id, previous, current)
                except ProxyUnavailableError:
                    pass  # A modem may briefly disconnect while rotating.
                await asyncio.sleep(poll_seconds)
    except TimeoutError:
        pass
    raise ProxyUnavailableError("IP rotation was not confirmed before the deadline")
