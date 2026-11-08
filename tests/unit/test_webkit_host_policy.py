import random
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from syntetic_core._engine import capabilities
from syntetic_core._engine.browser.factory import BrowserContextFactory
from syntetic_core._engine.browser.webkit_native import validate_webkit_native
from syntetic_core._engine.browser_runtime import RuntimeCompatibilityError, require_compatible
from syntetic_core._engine.config import Settings
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.persona_randomization import randomize_persona
from syntetic_core._engine.personas import BrowserPersona
from syntetic_core._engine.phone_personas import randomize_phone
from syntetic_core._engine.webkit_policy import WEBKIT_NATIVE_CAPABILITY, verified_webkit_worker
from tests.runtime_contract import manifest


def ios():
    return randomize_phone(BrowserPersona(id="1"), "ios", random.Random(1))


@pytest.mark.parametrize("system", ["windows", "linux", "macos"])
@pytest.mark.parametrize("verified", [False, True])
def test_controller_and_generator_require_native_webkit_and_supported_host(system, verified):
    worker = manifest()
    worker["operating_system"] = system
    runtime = next(r for r in worker["runtimes"] if r["engine"] == "webkit")
    if not verified:
        runtime["parameters"].remove(WEBKIT_NATIVE_CAPABILITY)
    permitted = system != "windows" and verified
    assert verified_webkit_worker(worker) == permitted
    if permitted:
        require_compatible(ios(), worker)
        assert (
            randomize_persona(
                BrowserPersona(id="1"),
                ["playwright"],
                device_family="ios",
                worker_capabilities=worker,
            ).phone.family
            == "ios"
        )
    else:
        with pytest.raises(RuntimeCompatibilityError, match="runtime.webkit"):
            require_compatible(ios(), worker)
        with pytest.raises(RuntimeCompatibilityError, match="device_family"):
            randomize_persona(
                BrowserPersona(id="1"),
                ["playwright"],
                device_family="ios",
                worker_capabilities=worker,
            )


def test_unverified_workers_never_generate_ios_and_windows_uses_android_for_mobile():
    with pytest.raises(RuntimeCompatibilityError, match="device_family"):
        randomize_persona(BrowserPersona(id="1"), ["playwright"], device_family="ios")
    worker = manifest()
    worker["operating_system"] = "windows"
    for worker_manifest in (None, worker):
        for seed in range(30):
            profile = randomize_persona(
                BrowserPersona(id="1"),
                ["playwright"],
                device_weights={"android": 60, "ios": 40},
                worker_capabilities=worker_manifest,
                rng=random.Random(seed),
            )
            assert profile.phone.family == "android" and profile.browser_engine == "chromium"


async def test_windows_factory_rejects_saved_webkit_before_touching_profile(monkeypatch, tmp_path):
    monkeypatch.setattr("syntetic_core._engine.browser.factory.platform.system", lambda: "Windows")
    path = tmp_path / "1" / "browser-data"
    with pytest.raises(ProfileValidationError, match="runtime.webkit_host"):
        async with BrowserContextFactory(Settings(_env_file=None)).open(ios(), path):
            pytest.fail("A Windows WebKit context was yielded")
    assert not path.parent.exists()


async def test_native_probe_rejects_windows_before_opening_any_page(monkeypatch):
    monkeypatch.setattr(
        "syntetic_core._engine.browser.webkit_native.platform.system", lambda: "Windows"
    )
    with pytest.raises(ProfileValidationError, match="runtime.webkit_host"):
        await validate_webkit_native(None)


@pytest.mark.parametrize("failure", ["missing_codec", "permission_error", "timeout"])
async def test_native_probe_fails_closed_and_closes_its_page(monkeypatch, failure):
    monkeypatch.setattr(
        "syntetic_core._engine.browser.webkit_native.platform.system", lambda: "Linux"
    )
    page = SimpleNamespace(
        route=AsyncMock(),
        goto=AsyncMock(),
        close=AsyncMock(),
        evaluate=AsyncMock(return_value={"web_audio": True, "video_decode": False}),
    )
    if failure == "permission_error":
        page.evaluate.side_effect = RuntimeError("native API unavailable")
    elif failure == "timeout":
        page.evaluate.side_effect = TimeoutError()
    context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    with pytest.raises(ProfileValidationError, match="runtime.webkit_full_native"):
        await validate_webkit_native(context)
    page.close.assert_awaited_once()


@pytest.mark.parametrize("valid", [True, False])
async def test_native_probe_borrows_convenience_page_without_closing_it(monkeypatch, valid):
    monkeypatch.setattr(
        "syntetic_core._engine.browser.webkit_native.platform.system", lambda: "Linux"
    )
    checks = dict.fromkeys(
        ("web_audio", "media_devices", "speech", "audio_decode", "video_decode", "aac"),
        valid,
    )
    page = SimpleNamespace(
        goto=AsyncMock(),
        close=AsyncMock(),
        evaluate=AsyncMock(return_value=checks),
        is_closed=lambda: False,
    )
    context = SimpleNamespace(new_page=AsyncMock(side_effect=AssertionError("owned context")))
    if valid:
        assert (await validate_webkit_native(context, page=page))["passed"]
    else:
        with pytest.raises(ProfileValidationError, match="missing native subsystems"):
            await validate_webkit_native(context, page=page)
    context.new_page.assert_not_awaited()
    page.close.assert_not_awaited()
    assert page.goto.await_args.args == ("about:blank",)


async def test_windows_discovery_never_attempts_webkit_even_with_all_browsers_installed(
    monkeypatch,
):
    monkeypatch.setattr(capabilities.platform, "system", lambda: "Windows")
    monkeypatch.setattr(capabilities.platform, "machine", lambda: "AMD64")
    attempts = []

    class Factory:
        def __init__(self, settings):
            pass

        @asynccontextmanager
        async def open(self, persona, *args, **kwargs):
            attempts.append(persona.browser_engine)
            raise RuntimeError("Deliberate smoke failure")
            yield

    monkeypatch.setattr(capabilities, "BrowserContextFactory", Factory)
    worker = await capabilities.discover_capabilities(Settings(_env_file=None))
    assert attempts == ["chromium", "firefox"]
    runtime = next(r for r in worker["runtimes"] if r["engine"] == "webkit")
    assert not runtime["installed"] and runtime["smoke_test"] == "unavailable"
    assert "phone_ios" not in runtime["parameters"]
    assert any("Windows is disabled" in text for text in runtime["limitations"])
