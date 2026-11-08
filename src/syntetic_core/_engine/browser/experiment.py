"""An observable timeline, anchored to the first visit to the scenario origin."""

import asyncio
from time import monotonic, time
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page

from syntetic_core._engine.browser.environment import observe_page_environment
from syntetic_core._engine.browser.factory import BrowserContextFactory
from syntetic_core._engine.browser_experiments import (
    DisplayCondition,
    ExperimentEvent,
    HistoryCondition,
    LocationCondition,
    NetworkCondition,
    StorageCondition,
)
from syntetic_core._engine.config import Settings
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona
from syntetic_core._engine.scenarios.engine import EventSink
from syntetic_core._engine.targets import authorize_url


def origin(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.netloc


class VisitExperiment:
    def __init__(
        self,
        context: BrowserContext,
        persona: BrowserPersona,
        base_url: str,
        settings: Settings,
        factory: BrowserContextFactory,
        events: EventSink,
        expected: dict[str, Any],
        lock: asyncio.Lock,
    ) -> None:
        self.context, self.persona, self.base_url = context, persona, base_url
        self.settings, self.factory, self.events = settings, factory, events
        self.expected, self.lock = expected, lock
        self.task: asyncio.Task[None] | None = None
        self.failure: Exception | None = None
        self.applied = 0
        self.started: float | None = None
        self.stopping = False
        self.navigation = asyncio.Event()
        self.watched: list[Page] = []
        self.display_sessions: dict[Page, Any] = {}
        self.last_display: DisplayCondition | None = None
        self.display_pages: set[Page] = set()
        self.failed = asyncio.Event()

    def navigated(self, *_args: Any) -> None:
        self.navigation.set()

    def watch(self, page: Page) -> None:
        self.watched.append(page)
        page.on("framenavigated", self.navigated)
        self.navigation.set()

    def start(self) -> None:
        if self.persona.experiment is not None:
            self.context.on("page", self.watch)
            for page in self.context.pages:
                self.watch(page)
            self.task = asyncio.create_task(self.run())

    def target_page(self) -> Page | None:
        return next(
            (
                p
                for p in reversed(self.context.pages)
                if not p.is_closed() and origin(p.url) == origin(self.base_url)
            ),
            None,
        )

    async def run(self) -> None:
        assert self.persona.experiment is not None
        try:
            while True:
                self.navigation.clear()
                page = self.target_page()
                if page is not None:
                    break
                await self.navigation.wait()
            await page.wait_for_load_state("domcontentloaded")
            self.started = monotonic()
            for index, event in enumerate(self.persona.experiment.events):
                await asyncio.sleep(max(0, self.started + event.after_ms / 1000 - monotonic()))
                async with self.lock:
                    page = self.target_page()
                    if page is None:
                        raise ProfileValidationError("Experiment lost its scenario-origin page")
                    authorize_url(page.url, self.settings)
                    await self.apply(event, page)
                    self.applied += 1
                    await self.events.emit(
                        "experiment_event_applied",
                        metadata={
                            "index": index,
                            "kind": event.kind,
                            "planned_ms": event.after_ms,
                            "elapsed_ms": round((monotonic() - self.started) * 1000),
                        },
                    )
        except Exception as exc:
            self.failure = exc
            self.failed.set()
            await self.events.emit(
                "experiment_event_failed",
                metadata={
                    "index": self.applied,
                    "error_type": type(exc).__name__,
                },
            )

    async def apply(self, event: ExperimentEvent, page: Page) -> None:
        if isinstance(event, NetworkCondition):
            assert self.factory.target_proxy is not None
            self.factory.target_proxy.pacer.set(event)
            await self.context.set_offline(event.offline)
        elif isinstance(event, LocationCondition):
            await self.context.set_geolocation(
                {
                    "latitude": event.latitude,
                    "longitude": event.longitude,
                    "accuracy": event.accuracy,
                }
            )
        elif isinstance(event, StorageCondition):
            cookies = await self.context.cookies(self.base_url)
            for cookie in cookies:
                if cookie["name"] in event.remove_cookies or cookie["name"] in event.expire_cookies:
                    await self.context.clear_cookies(
                        name=cookie["name"], domain=cookie["domain"], path=cookie["path"]
                    )
            if event.expire_cookies:
                await self.context.add_cookies(
                    [
                        {
                            "name": name,
                            "value": value,
                            "url": self.base_url,
                            "expires": time() - 86400,
                        }
                        for name, value in event.expire_cookies.items()
                    ]
                )
            await page.evaluate(
                ("mw:" if self.persona.runtime.backend == "camoufox" else "")
                + "keys => { for (const key of keys) localStorage.removeItem(key); }",
                event.remove_local_storage,
            )
        elif isinstance(event, HistoryCondition):
            operation = {"back": page.go_back, "forward": page.go_forward, "reload": page.reload}[
                event.direction
            ]
            await operation(
                wait_until="domcontentloaded", timeout=self.settings.navigation_timeout * 1000
            )
            authorize_url(page.url, self.settings)
        elif isinstance(event, DisplayCondition):
            self.last_display = event
            await self.display(page, event)

    async def display(
        self, page: Page, event: DisplayCondition, *, targets: list[Page] | None = None
    ) -> None:
        if self.persona.runtime.backend == "camoufox":
            raise ProfileValidationError("Dynamic Camoufox geometry is not verified")
        if self.persona.browser_engine != "chromium" and (
            event.safe_area
            or (event.keyboard and event.keyboard.mode == "native")
            or event.posture
            or event.page_scale != 1
        ):
            raise ProfileValidationError("This display condition requires Chromium")
        pages = targets or [p for p in self.context.pages if not p.is_closed()]
        height = event.height
        if event.keyboard is not None and event.keyboard.mode == "viewport":
            height = max(200, event.height - event.keyboard.height)
        for target in pages:
            await target.set_viewport_size({"width": event.width, "height": height})
            if self.persona.browser_engine == "chromium":
                session = self.display_sessions.get(target)
                if session is None:
                    session = await self.context.new_cdp_session(target)
                try:
                    metrics: dict[str, Any] = {
                        "width": event.width,
                        "height": height,
                        "screenWidth": event.width,
                        "screenHeight": event.height,
                        "deviceScaleFactor": self.persona.device.device_scale_factor,
                        "mobile": self.persona.device.mobile,
                        "screenOrientation": {
                            "type": event.orientation + "Primary",
                            "angle": 0 if event.orientation == "portrait" else 90,
                        },
                    }
                    if event.posture:
                        fold = (
                            self.persona.chromium.experience.foldable
                            if self.persona.chromium and self.persona.chromium.experience
                            else None
                        )
                        if fold is None:
                            raise ProfileValidationError(
                                "Posture change requires a foldable profile"
                            )
                        metrics["devicePosture"] = {"type": event.posture}
                        if event.posture == "folded":
                            metrics["displayFeature"] = {
                                "orientation": "vertical"
                                if event.orientation == "portrait"
                                else "horizontal",
                                "offset": (
                                    event.width if event.orientation == "portrait" else event.height
                                )
                                // 2,
                                "maskLength": fold.mask_length,
                            }
                        if self.factory.chromium_controller:
                            self.factory.chromium_controller.live_posture = event.posture
                    await session.send("Emulation.setDeviceMetricsOverride", metrics)
                    await session.send(
                        "Emulation.setPageScaleFactor", {"pageScaleFactor": event.page_scale}
                    )
                    if event.safe_area is not None:
                        await session.send(
                            "Emulation.setSafeAreaInsetsOverride",
                            {"insets": event.safe_area.model_dump()},
                        )
                    if event.keyboard is not None and event.keyboard.mode == "native":
                        await session.send(
                            "Emulation.setVirtualKeyboardGeometryOverride",
                            {"keyboardRect": event.keyboard.model_dump(exclude={"mode"})},
                        )
                    if event.posture:
                        await target.evaluate("navigator.devicePosture?.type")
                        await asyncio.sleep(0.08)
                        await session.send(
                            "Emulation.setDevicePostureOverride",
                            {"posture": {"type": event.posture}},
                        )
                finally:
                    # Emulation is scoped to this CDP agent. Detaching would reset
                    # scale/insets before the scenario observes them. The browser
                    # context owns and closes these agents during normal cleanup.
                    self.display_sessions[target] = session
            self.display_pages.add(target)
        actual = await observe_page_environment(page)
        # Accept only changes explicitly requested by this display event.
        for field in ("viewport", "screen"):
            self.expected[field] = actual[field]
        if not self.persona.device.mobile and actual["viewport"] != {
            "width": event.width,
            "height": height,
        }:
            raise ProfileValidationError("Requested viewport was not applied")

    async def synchronize(self, page: Page) -> None:
        if self.last_display is not None and page not in self.display_pages:
            await self.display(page, self.last_display, targets=[page])

    async def guard(self, scenario: Any) -> None:
        task = asyncio.create_task(scenario)
        failure = asyncio.create_task(self.failed.wait())
        try:
            await asyncio.wait([task, failure], return_when=asyncio.FIRST_COMPLETED)
            if self.failure is not None:
                raise self.failure
            await task
        finally:
            for pending in (task, failure):
                pending.cancel()
            await asyncio.gather(task, failure, return_exceptions=True)

    async def close(self, *, require_complete: bool = True) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.context.remove_listener("page", self.watch)
            for page in self.watched:
                page.remove_listener("framenavigated", self.navigated)
        # Restore network before final diagnostics and native browser cleanup.
        if self.factory.target_proxy is not None:
            self.factory.target_proxy.pacer.set(NetworkCondition())
        await self.context.set_offline(False)
        if self.failure is not None:
            raise self.failure
        count = len(self.persona.experiment.events) if self.persona.experiment else 0
        if require_complete and self.applied != count:
            raise ProfileValidationError("Scenario ended before its experiment timeline completed")
