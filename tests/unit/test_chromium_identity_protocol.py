import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from syntetic_core._engine.browser.chromium import ChromiumIdentitySession
from syntetic_core._engine.errors import ProfileValidationError
from tests.unit.test_device_coherence import phone_profile


async def test_early_identity_failure_closes_controller_without_removing_absent_listener(
    tmp_path, monkeypatch
):
    from syntetic_core._engine.browser import chromium
    from syntetic_core._engine.personas import BrowserPersona

    (tmp_path / "DevToolsActivePort").write_text(
        "12345\n/devtools/browser/11111111-1111-1111-1111-111111111111\n"
    )
    verification = SimpleNamespace(
        send=AsyncMock(side_effect=RuntimeError("verification failed")), detach=AsyncMock()
    )
    context = SimpleNamespace(
        browser=None,
        pages=[object()],
        new_cdp_session=AsyncMock(return_value=verification),
        remove_listener=Mock(side_effect=KeyError("listener was never registered")),
    )
    controller = SimpleNamespace(receive=AsyncMock(), close=AsyncMock())

    @asynccontextmanager
    async def connect(*args, **kwargs):
        yield object()

    monkeypatch.setattr(chromium, "connect", connect)
    monkeypatch.setattr(chromium, "ChromiumIdentitySession", Mock(return_value=controller))
    with pytest.raises(RuntimeError, match="verification failed"):
        async with chromium.chromium_identity(
            context,
            BrowserPersona(id="1"),
            tmp_path,
            native_brands={},
            network_override={"platform": "Linux", "userAgentMetadata": {}},
        ):
            pytest.fail("Unverified identity was yielded")
    await controller.receiver
    context.remove_listener.assert_not_called()
    controller.close.assert_awaited_once()


async def test_failed_identity_override_closes_browser_instead_of_releasing_target() -> None:
    context = SimpleNamespace(close=AsyncMock())
    controller = ChromiumIdentitySession(AsyncMock(), {"platform": "Win32"}, context)
    controller.send = AsyncMock(side_effect=ProfileValidationError("unsupported"))
    await controller.configure({"sessionId": "new-page", "targetInfo": {"type": "page"}})
    context.close.assert_awaited_once()
    assert "Runtime.runIfWaitingForDebugger" not in [
        call.args[0] for call in controller.send.await_args_list
    ]
    with pytest.raises(ProfileValidationError, match="could not be maintained"):
        controller.check()


async def test_cancelled_protocol_command_does_not_leave_a_pending_response() -> None:
    sent = asyncio.Event()

    async def send(message: str) -> None:
        sent.set()

    controller = ChromiumIdentitySession(
        SimpleNamespace(send=send), {}, SimpleNamespace(close=AsyncMock())
    )
    task = asyncio.create_task(controller.send("Target.getTargets", {}))
    await sent.wait()
    assert controller.pending
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not controller.pending


@pytest.mark.parametrize("target", ["page", "iframe", "worker", "service_worker", "shared_worker"])
async def test_mobile_cpu_override_precedes_resuming_every_target(target) -> None:
    controller = ChromiumIdentitySession(
        AsyncMock(),
        {"platform": "Linux armv8l", "userAgentMetadata": {"mobile": True}},
        SimpleNamespace(close=AsyncMock()),
        hardware_concurrency=8,
    )
    controller.send = AsyncMock(return_value={})
    await controller.configure({"sessionId": "target", "targetInfo": {"type": target}})
    methods = [call.args[0] for call in controller.send.await_args_list]
    assert methods.index("Emulation.setHardwareConcurrencyOverride") < methods.index(
        "Runtime.runIfWaitingForDebugger"
    )
    controller.send.assert_any_await(
        "Emulation.setHardwareConcurrencyOverride", {"hardwareConcurrency": 8}, "target"
    )


async def test_empty_popup_initialization_can_resume_before_emulation_replies():
    context = SimpleNamespace(close=AsyncMock())
    controller = ChromiumIdentitySession(
        AsyncMock(), {"platform": "Win32"}, context, hardware_concurrency=16
    )
    initialized = asyncio.Event()
    methods = []

    async def send(method, *_args):
        methods.append(method)
        if method == "Runtime.runIfWaitingForDebugger":
            initialized.set()
        else:
            await initialized.wait()
        return {}

    controller.send = send
    await asyncio.wait_for(
        controller.configure({"sessionId": "popup", "targetInfo": {"type": "page", "url": ""}}),
        0.5,
    )
    assert methods[0] == "Emulation.setHardwareConcurrencyOverride"
    assert methods[-1] == "Runtime.runIfWaitingForDebugger"
    context.close.assert_not_awaited()


async def test_rejected_empty_popup_emulation_closes_context():
    context = SimpleNamespace(close=AsyncMock())
    controller = ChromiumIdentitySession(AsyncMock(), {"platform": "Win32"}, context)

    async def send(method, *_args):
        if method == "Network.setUserAgentOverride":
            raise ProfileValidationError("Unsupported identity")
        return {}

    controller.send = send
    await controller.configure({"sessionId": "popup", "targetInfo": {"type": "page", "url": ""}})
    context.close.assert_awaited_once()
    with pytest.raises(ProfileValidationError, match="could not be maintained"):
        controller.check()


@pytest.mark.parametrize("target", ["worker", "shared_worker", "service_worker"])
async def test_worker_recipe_is_installed_before_resume(target):
    controller = ChromiumIdentitySession(
        AsyncMock(),
        {"platform": "Linux armv8l"},
        SimpleNamespace(close=AsyncMock()),
        persona=phone_profile("SM-A556B"),
    )
    controller.send = AsyncMock(return_value={})
    await controller.configure({"sessionId": "worker", "targetInfo": {"type": target}})
    calls = controller.send.await_args_list
    methods = [call.args[0] for call in calls]
    assert methods.index("Runtime.enable") < methods.index("Runtime.evaluate")
    assert methods.index("Runtime.evaluate") < methods.index("Runtime.runIfWaitingForDebugger")
    expression = next(
        call.args[1]["expression"] for call in calls if call.args[0] == "Runtime.evaluate"
    )
    assert '"hardware_concurrency": 8' in expression
    assert '"device_memory":' in expression
    assert '"sensor_readings":' not in expression


async def test_worker_script_exception_closes_context_without_resuming():
    context = SimpleNamespace(close=AsyncMock())
    controller = ChromiumIdentitySession(
        AsyncMock(),
        {"platform": "Linux armv8l"},
        context,
        persona=phone_profile("SM-A556B"),
    )

    async def send(method, *_args):
        if method == "Runtime.evaluate":
            return {"exceptionDetails": {"text": "script failed"}}
        return {}

    controller.send = AsyncMock(side_effect=send)
    await controller.configure({"sessionId": "worker", "targetInfo": {"type": "worker"}})
    context.close.assert_awaited_once()
    assert "Runtime.runIfWaitingForDebugger" not in [
        call.args[0] for call in controller.send.await_args_list
    ]


@pytest.mark.parametrize("target", ["page", "iframe"])
def test_android_presets_enable_five_touch_points(target):
    controller = ChromiumIdentitySession(
        AsyncMock(),
        {"platform": "Linux armv8l"},
        SimpleNamespace(),
        persona=phone_profile("SM-A556B"),
    )
    assert ("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5}) in (
        controller.emulation_commands(target in {"page", "iframe"})
    )


def test_desktop_does_not_enable_touch():
    controller = ChromiumIdentitySession(AsyncMock(), {"platform": "Win32"}, SimpleNamespace())
    assert not any(
        method == "Emulation.setTouchEmulationEnabled"
        for method, _ in controller.emulation_commands(True)
    )
