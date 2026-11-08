"""Standalone lifecycle over the extracted browser engine."""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from playwright.async_api import BrowserContext, Page, Response

from syntetic_core._engine.actions.behavior import InteractionBehavior, UXActivityDispatcher
from syntetic_core._engine.browser.environment import (
    environment_differences,
    observe_page_environment,
)
from syntetic_core._engine.browser.factory import BrowserContextFactory
from syntetic_core._engine.browser.visit_state import prepare_visit_state
from syntetic_core._engine.browser_runtime import require_compatible
from syntetic_core._engine.capabilities import discover_capabilities
from syntetic_core._engine.config import Settings
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.persona_randomization import randomize_persona
from syntetic_core._engine.personas import BrowserPersona, DeviceFamily
from syntetic_core._engine.profile_lock import ProfileLock
from syntetic_core._engine.profile_storage import atomic_json
from syntetic_core._engine.proxies import ProxyConfig
from syntetic_core._engine.ram_profile import finish_io
from syntetic_core._engine.targets import authorize_url
from syntetic_core.proxy import RotationProvider, RotationResult, channel_lock, rotate_and_verify


def _profile_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("Profile ID must contain 1–64 ASCII letters, digits, _ or -")
    return value


@dataclass
class BrowserSession:
    """The normal Playwright API remains available through context and page."""

    context: BrowserContext
    page: Page
    persona: BrowserPersona
    connection: dict[str, Any]
    behavior: InteractionBehavior
    _settings: Settings
    _factory: BrowserContextFactory

    async def goto(self, url: str) -> Response | None:
        authorize_url(url, self._settings)
        response = await self.page.goto(url, wait_until="domcontentloaded")
        await self.check_environment()
        return response

    async def check_environment(self, page: Page | None = None) -> None:
        actual = await observe_page_environment(
            page or self.page, main_world=self.persona.runtime.backend == "camoufox"
        )
        changed = environment_differences(
            self.connection["runtime"], actual, mobile=self.persona.device.mobile
        )
        if changed:
            raise ProfileValidationError("Observed environment changed: " + ", ".join(changed))
        if self._factory.chromium_controller is not None:
            self._factory.chromium_controller.check()

    async def maintain_presence(self, seconds: float) -> None:
        """Explicit optional UX activity; parsing itself does not require it."""
        dispatcher = UXActivityDispatcher(self.persona.behavior, interactions=self.behavior)
        await dispatcher.maintain_active_presence(self.page, seconds)


class SynteticCore:
    def __init__(
        self,
        profile_root: str | Path = "data/profiles",
        *,
        settings: Settings | None = None,
        proxy_channels: dict[str, str] | None = None,
    ) -> None:
        self.root = Path(profile_root).resolve()
        self.settings = (settings or Settings()).model_copy(deep=True)
        self.proxy_channels = dict(proxy_channels or {})
        self._capabilities: dict[str, Any] | None = None
        self._discovery_lock = asyncio.Lock()

    async def capabilities(self, *, refresh: bool = False) -> dict[str, Any]:
        async with self._discovery_lock:
            if refresh or self._capabilities is None:
                self._capabilities = await discover_capabilities(self.settings)
            # Callers cannot promote an unsupported runtime by mutating our cached manifest.
            import copy

            return copy.deepcopy(self._capabilities)

    def load_profile(self, profile_id: str) -> BrowserPersona:
        profile_id = _profile_id(profile_id)
        directory = self.root / profile_id
        if directory.is_symlink():
            raise ProfileValidationError("Profile directories cannot be symlinks")
        persona = BrowserPersona.model_validate_json(
            (directory / "profile.json").read_text("utf-8")
        )
        if (
            persona.id != profile_id
            or not persona.fingerprint_id
            or persona.config_hash != persona.digest()
        ):
            raise ProfileValidationError("Profile identity or checksum mismatch")
        return persona

    async def create_profile(
        self,
        profile_id: str | None = None,
        *,
        family: DeviceFamily = "desktop",
        backend: Literal["playwright", "camoufox"] = "playwright",
        proxy_id: str | None = None,
        locale: str = "ru-RU",
        timezone_id: str = "Europe/Moscow",
        fresh: bool = False,
    ) -> BrowserPersona:
        profile_id = _profile_id(profile_id or uuid4().hex)
        self._proxy(proxy_id)  # Missing requested proxies must fail before creating files.
        manifest = await self.capabilities()
        persona = randomize_persona(
            BrowserPersona(id=profile_id),
            [backend],
            worker_capabilities=manifest,
            device_family=family,
        )
        persona.proxy_id = proxy_id
        if not fresh:
            persona.visit_state = None
        persona.locale, persona.timezone_id = locale, timezone_id
        # Coordinates were generated for the random timezone. Regenerate coherently.
        if persona.geolocation is not None:
            from syntetic_core._engine.environment_randomization import randomize_location

            randomize_location(persona, random.SystemRandom())
        persona.config_hash = persona.digest()
        # Pydantic validation includes the coherence checks after final locale selection.
        persona = BrowserPersona.model_validate(persona.model_dump())
        require_compatible(persona, manifest)
        path = self.root / profile_id
        lock = ProfileLock(path / "browser-data", settings=self.settings)
        await lock.acquire_async()
        try:
            if path.exists():
                raise FileExistsError("Profile already exists; load it or choose another ID")
            await finish_io(atomic_json, path / "profile.json", persona.model_dump(mode="json"))
        finally:
            await asyncio.to_thread(lock.release)
        return persona

    def _proxy(self, proxy_id: str | None) -> ProxyConfig | None:
        from syntetic_core._engine.proxies import ProxyManager

        return ProxyManager(self.settings.proxies, self.settings.proxy_required).get(proxy_id)

    @asynccontextmanager
    async def session(
        self, profile_id: str, *, base_url: str | None = None
    ) -> AsyncIterator[BrowserSession]:
        persona = await asyncio.to_thread(self.load_profile, profile_id)
        require_compatible(persona, await self.capabilities())
        if persona.experiment is not None:
            raise ProfileValidationError(
                "Use the low-level VisitExperiment adapter for explicit timelines"
            )
        if persona.visit_state is not None and base_url is None:
            raise ValueError("Profiles with explicit visit_state require base_url")
        proxy = self._proxy(persona.proxy_id)
        fence = channel_lock(self.root, proxy, self.proxy_channels.get(proxy.id)) if proxy else None
        if fence:
            await fence.acquire_async()
        try:
            settings = self.settings.model_copy(deep=True)
            factory = BrowserContextFactory(settings)
            async with (
                asyncio.timeout(settings.browser_start_timeout) as startup,
                factory.open(
                    persona,
                    self.root / profile_id / "browser-data",
                    base_url=base_url,
                    block_service_workers=True,
                ) as context,
            ):
                startup.reschedule(None)
                if base_url is not None:
                    await prepare_visit_state(
                        context,
                        persona,
                        base_url,
                        settings,
                        factory.connection.get("session_count", 0),
                    )
                page = context.pages[0] if context.pages else await context.new_page()
                behavior = InteractionBehavior(
                    persona.behavior,
                    main_world=persona.runtime.backend == "camoufox",
                    touch=persona.device.touch,
                )
                behavior.native_cursor = persona.runtime.backend == "camoufox"
                yield BrowserSession(
                    context, page, persona, factory.connection, behavior, settings, factory
                )
        finally:
            if fence:
                await asyncio.to_thread(fence.release)

    async def rotate_ip(
        self,
        proxy_id: str,
        provider: RotationProvider,
        *,
        probe_url: str,
        timeout_seconds: float = 60,
        poll_seconds: float = 2,
    ) -> RotationResult:
        proxy = self._proxy(proxy_id)
        assert proxy is not None
        fence = channel_lock(self.root, proxy, self.proxy_channels.get(proxy.id))
        await fence.acquire_async()
        try:
            return await rotate_and_verify(
                self.settings,
                proxy,
                provider,
                probe_url,
                timeout_seconds=timeout_seconds,
                poll_seconds=poll_seconds,
            )
        finally:
            await asyncio.to_thread(fence.release)
