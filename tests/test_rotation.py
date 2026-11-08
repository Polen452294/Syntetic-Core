import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from syntetic_core import (
    CoreSettings,
    HttpRotationProvider,
    ProfileLockedError,
    ProxyConfig,
    SynteticCore,
)
from syntetic_core._engine.errors import ProxyUnavailableError
from syntetic_core.proxy import channel_lock, rotate_and_verify


@pytest.fixture
def proxy():
    return ProxyConfig(id="mobile", server="http://127.0.0.1:28080", kind="mobile")


async def test_rotation_waits_for_changed_tunnel_ip(proxy, monkeypatch):
    import syntetic_core.proxy as module

    observe = AsyncMock(side_effect=["8.8.8.8", "8.8.8.8", "1.1.1.1"])
    monkeypatch.setattr(module, "observe_ip", observe)
    provider = AsyncMock()
    result = await rotate_and_verify(
        CoreSettings(), proxy, provider, "https://probe.test", poll_seconds=0.001
    )
    assert result.previous_ip == "8.8.8.8" and result.current_ip == "1.1.1.1"
    provider.rotate.assert_awaited_once_with(proxy)


async def test_rotation_timeout_never_claims_success(proxy, monkeypatch):
    import syntetic_core.proxy as module

    monkeypatch.setattr(module, "observe_ip", AsyncMock(return_value="8.8.8.8"))
    with pytest.raises(ProxyUnavailableError, match="not confirmed"):
        await rotate_and_verify(
            CoreSettings(),
            proxy,
            AsyncMock(),
            "https://probe.test",
            timeout_seconds=0.02,
            poll_seconds=0.001,
        )


async def test_rotation_cannot_interrupt_active_channel(tmp_path, proxy):
    core = SynteticCore(tmp_path, settings=CoreSettings(proxies=[proxy]))
    lock = channel_lock(tmp_path, proxy)
    lock.acquire()
    provider = AsyncMock()
    try:
        with pytest.raises(ProfileLockedError):
            await core.rotate_ip(proxy.id, provider, probe_url="https://probe.test")
        provider.rotate.assert_not_awaited()
    finally:
        lock.release()


def test_shared_modem_id_joins_different_endpoints(tmp_path, proxy):
    second = proxy.model_copy(update={"id": "second", "server": "http://127.0.0.1:28081"})
    one, two = channel_lock(tmp_path, proxy, "modem-1"), channel_lock(tmp_path, second, "modem-1")
    one.acquire()
    try:
        with pytest.raises(ProfileLockedError):
            two.acquire()
    finally:
        one.release()


async def test_http_adapter_uses_private_credentials_and_checks_body(proxy, monkeypatch):
    import syntetic_core.proxy as module

    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"data": {"ok": True}})

    client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(handle), **kw),
    )
    provider = HttpRotationProvider(
        url=SecretStr("https://provider.test/rotate?token=secret"),
        headers={"Authorization": SecretStr("Bearer secret")},
        success_field="data.ok",
    )
    assert "secret" not in repr(provider)
    await provider.rotate(proxy)
    assert seen[0].headers["Authorization"] == "Bearer secret"


async def test_http_adapter_rejects_redirects_without_following(proxy, monkeypatch):
    import syntetic_core.proxy as module

    client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(302, headers={"Location": "https://other.test/"})
            ),
            **kw,
        ),
    )
    with pytest.raises(ProxyUnavailableError, match="API failed"):
        await HttpRotationProvider(url=SecretStr("https://provider.test/secret")).rotate(proxy)


async def test_provider_cancellation_is_preserved(proxy, monkeypatch):
    import syntetic_core.proxy as module

    monkeypatch.setattr(module, "observe_ip", AsyncMock(return_value="8.8.8.8"))
    provider = AsyncMock()
    provider.rotate.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await rotate_and_verify(CoreSettings(), proxy, provider, "https://probe.test")


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.test/rotate",
        "https://user:password@provider.test/",
        "https://provider.test/#secret",
    ],
)
def test_rotation_url_validation(url):
    with pytest.raises(ValidationError):
        HttpRotationProvider(url=SecretStr(url))
