"""Native CDP OS emulation, installed before new targets execute page scripts."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from typing import Any

from playwright.async_api import BrowserContext, CDPSession, Page
from playwright.async_api import Error as PlaywrightError
from websockets.asyncio.client import ClientConnection, connect

from syntetic_core._engine.browser.device_emulation import emulation_headers, emulation_script
from syntetic_core._engine.browser.identity import read_json, write_json
from syntetic_core._engine.browser.playwright_worker_control import OWNER_FLAG
from syntetic_core._engine.browser.sensors import moving_sensor_readings, sensor_readings
from syntetic_core._engine.browser.session_hardware import effective_emulation
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona, StationarySensors

CHROMIUM_DEBUG_ARGS = [
    "--remote-debugging-port=0",
    "--remote-debugging-address=127.0.0.1",
    OWNER_FLAG,
]


def identity_override(persona: BrowserPersona, version: str) -> dict[str, Any]:
    ua_os, platform, hint_platform = {
        "windows": ("Windows NT 10.0; Win64; x64", "Win32", "Windows"),
        "macos": ("Macintosh; Intel Mac OS X 10_15_7", "MacIntel", "macOS"),
        "linux": ("X11; Linux x86_64", "Linux x86_64", "Linux"),
        "android": ("Linux; Android 10; K", "Linux armv8l", "Android"),
    }[str(persona.runtime.target_os)]
    # Use Chromium's reduced UA and the actual installed version in high-entropy hints.
    major = version.split(".", 1)[0]
    mobile = persona.phone is not None and persona.phone.family == "android"
    mobile_token = " Mobile" if mobile else ""
    return {
        "userAgent": (
            f"Mozilla/5.0 ({ua_os}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0{mobile_token} Safari/537.36"
        ),
        "platform": platform,
        "acceptLanguage": persona.locale,
        "userAgentMetadata": {
            "platform": hint_platform,
            "platformVersion": persona.chromium.platform_version if persona.chromium else "",
            "architecture": (
                persona.chromium.architecture
                if persona.chromium is not None and persona.chromium.architecture is not None
                else "arm"
                if mobile
                else "x86"
            ),
            "bitness": "64",
            "model": persona.phone.model if mobile and persona.phone else "",
            "mobile": mobile,
            "wow64": False,
        },
    }


def network_headers(persona: BrowserPersona, extra: dict[str, str]) -> dict[str, str]:
    value = effective_emulation(persona)
    assert value is not None and value.device_memory is not None
    memory = format(value.device_memory, "g")
    headers = {
        name: value
        for name, value in extra.items()
        if name.lower() not in {"device-memory", "sec-ch-device-memory"}
    }
    return {**headers, "Device-Memory": memory, "Sec-CH-Device-Memory": memory}


async def configure_network_identity(
    context: BrowserContext,
    persona: BrowserPersona,
    override: dict[str, Any],
    extra_http_headers: dict[str, str],
) -> None:
    headers = network_headers(persona, extra_http_headers)
    # Context headers also cover future pages and their initial navigation.
    await context.set_extra_http_headers(headers)
    pages = context.pages or [await context.new_page()]
    for page in pages:
        session = await context.new_cdp_session(page)
        # Keep the session attached until context.close(): detach resets overrides.
        await session.send("Network.enable", {})
        await session.send("Network.setUserAgentOverride", override)
        await session.send("Network.setExtraHTTPHeaders", {"headers": headers})


class ChromiumIdentitySession:
    def __init__(
        self,
        socket: ClientConnection,
        override: dict[str, Any],
        context: BrowserContext,
        *,
        hardware_concurrency: int | None = None,
        sensors: StationarySensors | None = None,
        legacy_phone_touch: bool = False,
        persona: BrowserPersona | None = None,
        extra_http_headers: dict[str, str] | None = None,
    ) -> None:
        self.socket = socket
        self.override = override
        self.context = context
        self.hardware_concurrency = hardware_concurrency
        self.sensors = sensors
        self.legacy_phone_touch = legacy_phone_touch
        self.persona = persona
        self.extra_http_headers = (
            network_headers(persona, {**emulation_headers(persona), **(extra_http_headers or {})})
            if persona is not None
            else None
        )
        self.sensor_targets: set[str] = set()
        self.posture_sessions: dict[Page, CDPSession] = {}
        self.live_posture: str | None = None
        self.posture_tasks: dict[Page, asyncio.Task[None]] = {}
        self.motion_task: asyncio.Task[None] | None = None
        self.motion_started = monotonic()
        self.sequence = 0
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.tasks: set[asyncio.Task[None]] = set()
        self.detached: set[str] = set()
        self.failure: Exception | None = None
        self.closing = False
        self.receiver: asyncio.Task[None] | None = None

    async def send(
        self, method: str, params: dict[str, Any], session: str | None = None
    ) -> dict[str, Any]:
        self.sequence += 1
        command = self.sequence
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.pending[command] = future
        message: dict[str, Any] = {"id": command, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        try:
            await self.socket.send(json.dumps(message))
            async with asyncio.timeout(10):
                return await future
        finally:
            self.pending.pop(command, None)

    async def receive(self) -> None:
        try:
            async for raw in self.socket:
                message = json.loads(raw)
                if "id" in message:
                    future = self.pending.get(message["id"])
                    if future is not None and not future.done():
                        if "error" in message:
                            future.set_exception(
                                ProfileValidationError("Chromium rejected identity")
                            )
                        else:
                            future.set_result(message.get("result", {}))
                elif message.get("method") == "Target.attachedToTarget":
                    task = asyncio.create_task(self.configure(message["params"]))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                elif message.get("method") == "Target.detachedFromTarget":
                    self.detached.add(message["params"]["sessionId"])
                    self.sensor_targets.discard(message["params"]["sessionId"])
            if not self.closing:
                self.failure = ProfileValidationError("Chromium identity connection was lost")
        except Exception:
            if not self.closing:
                self.failure = ProfileValidationError("Chromium identity connection failed")
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(
                        ProfileValidationError("Chromium identity connection closed")
                    )
            if self.failure is not None and not self.closing:
                await self.context.close(reason="Chromium identity connection failed")

    async def configure(self, params: dict[str, Any]) -> None:
        session = params["sessionId"]
        try:
            target_type = params["targetInfo"]["type"]
            is_page = target_type in {"page", "iframe"}
            is_worker = target_type in {"worker", "service_worker", "shared_worker"}
            if not is_page and not is_worker:
                await self.send("Runtime.runIfWaitingForDebugger", {}, session)
                return
            commands = self.emulation_commands(is_page)
            bootstrap: list[tuple[str, dict[str, Any]]] = []
            if is_worker and self.persona is not None:
                worker_script = emulation_script(
                    self.persona, worker=True, worker_user_agent=self.override.get("userAgent")
                )
                bootstrap = [
                    ("Runtime.enable", {}),
                    ("Runtime.evaluate", {"expression": worker_script, "returnByValue": True}),
                ]
            deferred_start = target_type == "service_worker" or (
                target_type == "page" and params["targetInfo"].get("url") == ""
            )
            if deferred_start:
                # Empty popup renderers defer emulation replies until initialized.
                # Service worker threads also defer commands until startup is released.
                # Queue overrides first, then release initialization in the same batch.
                commands.extend(
                    bootstrap
                    + [
                        ("Target.setAutoAttach", self.auto_attach(True, children=True)),
                        ("Runtime.runIfWaitingForDebugger", {}),
                    ]
                )
                results = await asyncio.gather(
                    *(self.send(method, values, session) for method, values in commands)
                )
                if any(result.get("exceptionDetails") for result in results):
                    raise ProfileValidationError("Chromium worker device initialization failed")
            else:
                await asyncio.gather(
                    *(self.send(method, values, session) for method, values in commands)
                )
                for method, values in bootstrap:
                    result = await self.send(method, values, session)
                    if result.get("exceptionDetails"):
                        raise ProfileValidationError("Chromium worker device initialization failed")
                await self.send(
                    "Target.setAutoAttach", self.auto_attach(True, children=True), session
                )
                await self.send("Runtime.runIfWaitingForDebugger", {}, session)
            if is_page and self.sensors is not None:
                self.sensor_targets.add(session)
            if (
                self.motion_task is None
                and self.persona is not None
                and self.persona.chromium is not None
                and self.persona.chromium.motion is not None
            ):
                self.motion_task = asyncio.create_task(self.animate_sensors())
        except Exception as error:
            if not self.closing and session not in self.detached:
                self.failure = error
                await self.context.close(reason="Chromium identity override failed")

    def emulation_commands(self, is_page: bool) -> list[tuple[str, dict[str, Any]]]:
        commands: list[tuple[str, dict[str, Any]]] = []
        if self.hardware_concurrency is not None:
            commands.append(
                (
                    "Emulation.setHardwareConcurrencyOverride",
                    {"hardwareConcurrency": self.hardware_concurrency},
                )
            )
        # Worker targets own a Network agent; page-only settings do not cover fetch().
        commands.append(("Network.enable", {}))
        commands.append(("Network.setUserAgentOverride", self.override))
        if self.extra_http_headers is not None:
            commands.append(("Network.setExtraHTTPHeaders", {"headers": self.extra_http_headers}))
        if is_page:
            commands.append(
                ("Emulation.setNavigatorOverrides", {"platform": self.override["platform"]})
            )
            if self.legacy_phone_touch or (
                self.persona is not None
                and self.persona.phone is not None
                and self.persona.phone.family == "android"
            ):
                commands.append(
                    ("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
                )
            if self.sensors is not None:
                readings = sensor_readings(self.sensors)
                commands.extend(
                    ("Emulation.setSensorOverrideEnabled", {"enabled": True, "type": kind})
                    for kind in readings
                )
                commands.extend(
                    ("Emulation.setSensorOverrideReadings", {"type": kind, "reading": reading})
                    for kind, reading in readings.items()
                )
            if (
                self.persona is not None
                and self.persona.chromium is not None
                and self.persona.chromium.experience is not None
            ):
                commands.extend(self.experience_commands())
        return commands

    def experience_commands(self) -> list[tuple[str, dict[str, Any]]]:
        assert self.persona is not None and self.persona.chromium is not None
        experience = self.persona.chromium.experience
        assert experience is not None
        commands: list[tuple[str, dict[str, Any]]] = [
            ("Emulation.setDataSaverOverride", {"dataSaverEnabled": experience.save_data}),
            ("Emulation.setEmulatedOSTextScale", {"scale": experience.text_scale}),
            ("Emulation.setCPUThrottlingRate", {"rate": experience.cpu_slowdown}),
        ]
        fold = experience.foldable
        if fold is not None:
            device = self.persona.device
            commands.append(
                (
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": device.viewport["width"],
                        "height": device.viewport["height"],
                        "screenWidth": device.screen["width"],
                        "screenHeight": device.screen["height"],
                        "deviceScaleFactor": device.device_scale_factor,
                        "mobile": device.mobile,
                        "devicePosture": {"type": fold.posture},
                        **(
                            {
                                "displayFeature": {
                                    "orientation": fold.orientation,
                                    "offset": fold.offset,
                                    "maskLength": fold.mask_length,
                                }
                            }
                            if fold.posture == "folded"
                            else {}
                        ),
                    },
                )
            )
        return commands

    async def configure_experience(self, session: str) -> None:
        await asyncio.gather(
            *(self.send(method, values, session) for method, values in self.experience_commands())
        )

    def watch_posture(self, page: Page) -> None:
        def restore(*_args: Any) -> None:
            previous = self.posture_tasks.pop(page, None)
            if previous is not None:
                previous.cancel()
            task = asyncio.create_task(self.restore_page_posture(page))
            self.posture_tasks[page] = task
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        def forget(*_args: Any) -> None:
            self.posture_sessions.pop(page, None)
            pending = self.posture_tasks.pop(page, None)
            if pending is not None:
                pending.cancel()

        page.on("load", restore)
        page.once("close", forget)

    async def restore_page_posture(self, page: Page) -> None:
        assert self.persona is not None and self.persona.chromium is not None
        experience = self.persona.chromium.experience
        assert experience is not None and experience.foldable is not None
        if page.url == "about:blank":
            return
        try:
            # Bind the document's native provider before overriding it. Chromium
            # otherwise initializes the first DevicePosture object as continuous.
            await page.evaluate("""async () => {
                if (navigator.devicePosture) await new Promise(resolve => setTimeout(resolve, 80));
            }""")
            previous = self.posture_sessions.pop(page, None)
            if previous is not None:
                await previous.detach()
            session = await self.context.new_cdp_session(page)
            self.posture_sessions[page] = session
            await session.send(
                "Emulation.setDevicePostureOverride",
                {"posture": {"type": self.live_posture or experience.foldable.posture}},
            )
        except Exception as error:
            if (
                isinstance(error, PlaywrightError)
                and str(error).startswith("Page.evaluate:")
                and (
                    "Execution context was destroyed" in str(error)
                    or "Cannot find context with specified id" in str(error)
                )
            ):
                # A new navigation replaced the document while its native
                # provider was binding. The next load restores the new provider.
                return
            if not self.closing and not page.is_closed():
                self.failure = error
                await self.context.close(reason="Chromium page posture override failed")

    async def animate_sensors(self) -> None:
        assert self.persona is not None and self.persona.chromium is not None
        motion = self.persona.chromium.motion
        assert motion is not None and self.sensors is not None
        try:
            while not self.closing:
                tick_started = monotonic()
                readings = moving_sensor_readings(
                    self.sensors, motion, monotonic() - self.motion_started
                )
                for session in tuple(self.sensor_targets):
                    try:
                        await asyncio.gather(
                            *(
                                self.send(
                                    "Emulation.setSensorOverrideReadings",
                                    {"type": kind, "reading": value},
                                    session,
                                )
                                for kind, value in readings.items()
                            )
                        )
                    except Exception:
                        if session not in self.detached and not self.closing:
                            raise
                # CDP work is part of the period; do not add it to every interval.
                await asyncio.sleep(max(0, 1 / motion.frequency - (monotonic() - tick_started)))
        except Exception as error:
            if not self.closing:
                self.failure = error
                await self.context.close(reason="Chromium sensor motion failed")

    @staticmethod
    def auto_attach(enabled: bool, *, children: bool = False) -> dict[str, Any]:
        filters = [{"type": "tab", "exclude": True}]
        if children:
            # Browser-level attachment owns these targets; avoid a second startup owner.
            filters.extend(
                {"type": kind, "exclude": True} for kind in ("service_worker", "shared_worker")
            )
        return {
            "autoAttach": enabled,
            "waitForDebuggerOnStart": enabled,
            "flatten": True,
            "filter": [*filters, {}],
        }

    def check(self) -> None:
        if self.failure is not None:
            raise ProfileValidationError("Chromium identity could not be maintained") from None

    async def close(self) -> None:
        self.closing = True
        if self.motion_task is not None:
            self.motion_task.cancel()
            await asyncio.gather(self.motion_task, return_exceptions=True)
        await self.socket.close()
        for task in self.tasks:
            task.cancel()
        if self.receiver is not None:
            self.receiver.cancel()
        await asyncio.gather(
            *self.tasks, *([self.receiver] if self.receiver else []), return_exceptions=True
        )


@asynccontextmanager
async def chromium_identity(
    context: BrowserContext,
    persona: BrowserPersona,
    profile_path: Path,
    *,
    native_brands: dict[str, Any],
    extra_http_headers: dict[str, str] | None = None,
    network_override: dict[str, Any] | None = None,
) -> AsyncIterator[ChromiumIdentitySession]:
    try:
        endpoint_data = await asyncio.to_thread((profile_path / "DevToolsActivePort").read_text)
        port, endpoint = endpoint_data.splitlines()
    except (OSError, ValueError):
        raise ProfileValidationError("Local Chromium endpoint is unavailable") from None
    if (
        not port.isdecimal()
        or not 0 < int(port) < 65536
        or not re.fullmatch(r"/devtools/browser/[a-f0-9-]{36}", endpoint)
    ):
        raise ProfileValidationError("Invalid local Chromium endpoint")
    version = context.browser.version if context.browser else "unknown"
    override = (
        network_override if network_override is not None else identity_override(persona, version)
    )
    override["userAgentMetadata"].update(native_brands)
    identity_path = profile_path.parent / "chromium-identity.json"
    if persona.fingerprint_id:
        identity_path = profile_path.parent / "fingerprints" / f"{persona.fingerprint_id}.json"
    signature = {
        "os": persona.runtime.target_os,
        "device": persona.device.model_dump(),
        "chromium": persona.chromium.model_dump() if persona.chromium else None,
    }
    if persona.phone is not None:
        signature["phone"] = persona.phone.model_dump()
    stored = await asyncio.to_thread(read_json, identity_path)
    if stored and (stored.get("signature") != signature or stored.get("version") != version):
        raise ProfileValidationError("Chromium identity changed; create a new profile")
    emulation = effective_emulation(persona)
    assert emulation is not None
    async with connect(
        f"ws://127.0.0.1:{port}{endpoint}", proxy=None, open_timeout=10, close_timeout=2
    ) as socket:
        controller = ChromiumIdentitySession(
            socket,
            override,
            context,
            hardware_concurrency=(
                emulation.hardware_concurrency or persona.hardware_concurrency_override
            ),
            sensors=persona.chromium.sensors if persona.chromium is not None else None,
            legacy_phone_touch=persona.phone is not None and persona.phone.preset_id is None,
            persona=persona,
            extra_http_headers=extra_http_headers,
        )
        controller.receiver = asyncio.create_task(controller.receive())
        posture_listener_registered = False
        try:
            # Reject stale endpoints and verify this is the locked profile's own process.
            page = context.pages[0] if context.pages else await context.new_page()
            verification = await context.new_cdp_session(page)
            try:
                expected_target = (await verification.send("Target.getTargetInfo"))["targetInfo"]
            finally:
                await verification.detach()
            targets = (await controller.send("Target.getTargets", {}))["targetInfos"]
            if not any(info["targetId"] == expected_target["targetId"] for info in targets):
                raise ProfileValidationError("Chromium endpoint belongs to another profile")
            await controller.send("Target.setAutoAttach", controller.auto_attach(True))
            await controller.send("Target.getTargets", {})
            while controller.tasks:
                await asyncio.gather(*list(controller.tasks))
            controller.check()
            if (
                persona.chromium is not None
                and persona.chromium.experience is not None
                and (persona.chromium.experience.foldable is not None)
            ):
                context.on("page", controller.watch_posture)
                posture_listener_registered = True
                for existing in context.pages:
                    controller.watch_posture(existing)
            await asyncio.to_thread(
                write_json, identity_path, {"signature": signature, "version": version}
            )
            yield controller
        finally:
            try:
                if posture_listener_registered:
                    context.remove_listener("page", controller.watch_posture)
            finally:
                await controller.close()
