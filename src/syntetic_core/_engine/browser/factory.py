import asyncio
import logging
import platform
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from time import time
from typing import Any

from playwright.async_api import BrowserContext, Route, async_playwright
from playwright.async_api import Error as PlaywrightError

from syntetic_core._engine.browser.chromium import (
    CHROMIUM_DEBUG_ARGS,
    chromium_identity,
    configure_network_identity,
    identity_override,
)
from syntetic_core._engine.browser.connectivity import (
    observe_network,
    validate_network,
    validate_persona_environment,
    validate_runtime_environment,
)
from syntetic_core._engine.browser.content_filter import (
    chromium_filter_options,
    gecko_profile_options,
    local_vendor_extensions,
    prepare_filter,
    validate_webkit_filter,
    webkit_filter_environment,
)
from syntetic_core._engine.browser.device_emulation import (
    emulation_headers,
    grant_native_permissions,
    validate_device_emulation,
)
from syntetic_core._engine.browser.egress import TargetProxy
from syntetic_core._engine.browser.extended_environment import observe_extended
from syntetic_core._engine.browser.gecko_addons import debugger_port, install_extensions
from syntetic_core._engine.browser.identity import (
    check_storage_engine,
    profile_identity_hashes,
    read_json,
    record_session,
    write_json,
)
from syntetic_core._engine.browser.mobile import configure_ios, ios_user_agent
from syntetic_core._engine.browser.native import camoufox_options
from syntetic_core._engine.browser.network import TrafficPolicy
from syntetic_core._engine.browser.playwright_worker_control import require_worker_control
from syntetic_core._engine.browser.session_apis import configure_session_apis, validate_session_apis
from syntetic_core._engine.browser.session_hardware import effective_emulation, session_emulation
from syntetic_core._engine.browser.visit_state import require_unused_profile
from syntetic_core._engine.browser.webkit_native import validate_webkit_native
from syntetic_core._engine.config import Settings
from syntetic_core._engine.errors import (
    BrowserLaunchError,
    DomainError,
    ProfileLockedError,
    ProfileValidationError,
    ProxyIdentityChangedError,
    ProxyUnavailableError,
)
from syntetic_core._engine.ipc import browser_environment
from syntetic_core._engine.personas import BrowserPersona, DeviceProfileResolver, PersonaValidator
from syntetic_core._engine.profile_lock import ProfileLock
from syntetic_core._engine.proxies import ProxyConfig, ProxyManager
from syntetic_core._engine.targets import authorize_url
from syntetic_core._engine.webkit_policy import WEBKIT_HOST_LIMITATION, webkit_host_allowed

logger = logging.getLogger(__name__)

# Chromium-only worker flags; Firefox/Camoufox use their own native options.
# Keep the software rasterizer for WebGL; mute-audio only silences output.
# --no-sandbox assumes trusted test content and an isolated worker deployment.
CHROMIUM_LAUNCH_ARGS = (
    "--disable-gpu",
    "--disable-background-networking",
    "--disable-sync",
    "--mute-audio",
    "--disable-extensions",
    "--disable-component-update",
    "--disable-dev-shm-usage",
    "--no-sandbox",
)


async def guard_navigation(route: Route, settings: Settings) -> None:
    request = route.request
    if request.is_navigation_request():
        try:
            main_frame = request.frame.parent_frame is None
        except PlaywrightError as error:
            if "before the frame is created" not in str(error):
                raise
            # The first popup request precedes its Frame. Authorize it as a
            # top-level navigation; never let missing frame metadata skip policy.
            main_frame = True
        if main_frame:
            try:
                authorize_url(request.url, settings)
            except DomainError:
                await route.abort("blockedbyclient")
                return
    # Keep context-wide resource filters in the route chain.
    await route.fallback()


async def native_client_hint_identity(context: BrowserContext) -> dict[str, Any]:
    """Read this binary's native identity without changing a persistent document.

    Blink fills omitted brands for documents but leaves workers empty. Copy the
    actual defaults explicitly so desktop identities retain their original hints.
    A local file supplies a trustworthy origin without routing, DNS or network I/O.
    """
    if context.browser is None:
        raise ProfileValidationError("Chromium browser is unavailable")
    reference = await context.browser.new_context()
    try:
        page = await reference.new_page()
        with tempfile.TemporaryDirectory(prefix="native-identity-") as directory:
            document = Path(directory) / "identity.html"
            document.write_text("<!doctype html>", encoding="utf-8")
            await page.goto(document.as_uri())
        return await page.evaluate("""async () => {
            const data = await navigator.userAgentData.getHighEntropyValues(
                ['platformVersion','architecture','bitness','model','wow64',
                 'fullVersionList','uaFullVersion']);
            return {userAgent:navigator.userAgent,platform:navigator.platform,
                userAgentMetadata:{brands:data.brands,fullVersionList:data.fullVersionList,
                    fullVersion:data.uaFullVersion,platform:data.platform,
                    platformVersion:data.platformVersion,architecture:data.architecture,
                    bitness:data.bitness,model:data.model,mobile:data.mobile,wow64:data.wow64}};
        }""")
    finally:
        await reference.close()


class BrowserContextFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.proxies = ProxyManager(
            settings.proxies, settings.proxy_required, direct=settings.direct_transport
        )
        self.connection: dict[str, Any] = {}
        self.traffic = {"bytes_sent": 0, "bytes_received": 0}
        self.target_proxy: TargetProxy | None = None
        self.chromium_controller: Any = None

    @asynccontextmanager
    async def open(
        self,
        persona: BrowserPersona,
        profile_path: Path,
        proxy_override: ProxyConfig | None = None,
        *,
        log_context: dict[str, Any] | None = None,
        lease_guard: Callable[[], Awaitable[bool]] | None = None,
        block_service_workers: bool = False,
        organic_search: bool = False,
        base_url: str | None = None,
        traffic_policy: TrafficPolicy | None = None,
    ) -> AsyncIterator[BrowserContext]:
        # A replay supplies the original resolved policy, including CSS filtering
        # from an incubation session, without re-running the incubation workflow.
        traffic_policy = traffic_policy or TrafficPolicy.from_settings(self.settings)
        if organic_search and proxy_override is not None:
            raise ProfileValidationError("Organic search requires the native proxy transport")
        if persona.browser_engine == "webkit" and not webkit_host_allowed(platform.system()):
            raise ProfileValidationError("runtime.webkit_host: " + WEBKIT_HOST_LIMITATION)
        if profile_path.parent.name.isdecimal() and persona.id != profile_path.parent.name:
            raise ProfileValidationError("Persona and storage owner differ")
        lock = ProfileLock(profile_path, settings=self.settings)
        owner = asyncio.current_task()
        loop = asyncio.get_running_loop()

        def lease_lost() -> None:
            if owner is not None:
                loop.call_soon_threadsafe(owner.cancel)

        await lock.acquire_async(lease_lost)
        ram_profile = None
        hardware_token = None
        try:
            if lease_guard is not None and not await lease_guard():
                raise ProfileLockedError("Attempt no longer owns its session")
            from syntetic_core._engine.profile_storage import initialize_store, verify_store

            if self.settings.profile_ram_enabled:
                from syntetic_core._engine.ram_profile import (
                    RamProfile,
                    finish_io,
                    validate_ram_root,
                )

                validate_ram_root(self.settings.profile_ram_root)
                ram_profile = RamProfile(
                    profile_path,
                    self.settings.profile_ram_root,
                    self.settings.profile_ram_max_mb * 1024**2,
                )
                await finish_io(ram_profile.recover)

            identity = self.settings.expected_profile_storage
            if identity is not None:
                if self.settings.initialize_profile_storage:
                    initialize_store(profile_path, identity)
                    self.settings.initialize_profile_storage = False
                await asyncio.to_thread(verify_store, profile_path, identity, persona)
            elif self.settings.production_mode:
                raise ProfileValidationError(
                    "Storage identity required; adopt legacy profiles offline"
                )
            if ram_profile is not None:
                profile_path = await finish_io(ram_profile.prepare)
            if self.settings.direct_transport and persona.browser_engine == "chromium":
                from syntetic_core._engine.personas import DeviceEmulation

                hardware = await asyncio.to_thread(
                    read_json, profile_path.parent / "session-hardware-identity.json"
                )
                value = effective_emulation(persona)
                assert value is not None
                if hardware:
                    if hardware.get("profile") != (persona.fingerprint_id or persona.id):
                        raise ProfileValidationError("Session hardware belongs to another profile")
                    value = DeviceEmulation.model_validate(
                        {
                            **value.model_dump(),
                            **{
                                key: hardware[key]
                                for key in ("device_memory", "battery", "hardware_concurrency")
                                if key in hardware
                            },
                        }
                    )
                value.hardware_concurrency = (
                    value.hardware_concurrency or persona.hardware_concurrency_override or 4
                )
                hardware_token = session_emulation.set(value)
            started = time()
            state_path = profile_path.parent / "runtime-state.json"
            state = await asyncio.to_thread(read_json, state_path)
            if self.settings.prepared_session_profile and state.get("session_count", 0):
                expected_identity = state.get("incubation_identity")
                if expected_identity is None or expected_identity != await asyncio.to_thread(
                    profile_identity_hashes, profile_path
                ):
                    raise ProfileValidationError(
                        "Saved incubation hardware identity is missing or changed"
                    )
            await asyncio.to_thread(
                require_unused_profile,
                persona,
                profile_path,
                state.get("session_count", 0),
                fixed_fresh=self.settings.fixed_session_configuration
                and self.settings.use_fresh_session_profiles
                and not self.settings.prepared_session_profile,
            )
            check_storage_engine(profile_path, persona.browser_engine, state)
            if state.get("backend") and state["backend"] != persona.runtime.backend:
                raise ProfileValidationError("Changing a profile's runtime requires a new profile")
            if "channel" in state and state["channel"] != persona.runtime.channel:
                raise ProfileValidationError(
                    "Changing a profile's browser channel requires a new profile"
                )
            self.proxies.required = self.settings.proxy_required or persona.network.proxy_required
            proxy = self.proxies.select(persona, state, started)
            selected_proxy = (self.settings.incubation_config or {}).get("selected_proxy_id")
            if selected_proxy is not None and not self.settings.direct_transport:
                eligible = persona.network.proxy_pool or (
                    [persona.proxy_id] if persona.proxy_id is not None else []
                )
                if selected_proxy not in eligible:
                    raise ProxyUnavailableError("Incubation proxy is outside the assigned pool")
                proxy = self.proxies.get(selected_proxy)
            identity_proxy_id = proxy.id if proxy else None
            if (
                not self.settings.direct_transport
                and "proxy_id" in state
                and state["proxy_id"] != (proxy.id if proxy else None)
                and selected_proxy is None
                and (
                    self.settings.prepared_session_profile
                    or started - state.get("identity_since", 0)
                    < persona.network.min_identity_seconds
                )
            ):
                raise ProfileValidationError("Proxy changed before the allowed interval")
            if proxy:
                await self.proxies.check(proxy)
            if proxy_override is not None:
                if proxy is not None or persona.network.proxy_pool or self.settings.proxy_required:
                    raise ProxyUnavailableError(
                        "Mitmproxy cannot replace the required persona proxy"
                    )
                proxy = proxy_override
                await self.proxies.check(proxy)
            if persona.browser_engine == "chromium":
                await asyncio.to_thread(require_worker_control)
            async with async_playwright() as playwright, AsyncExitStack() as transports:
                # Every context, including diagnostics and capability checks, uses
                # the same fail-closed native transport. SW policy is independent.
                try:
                    # Host authorization is enforced before CONNECT, without TLS termination.
                    guard = await transports.enter_async_context(
                        TargetProxy(self.settings, proxy, explicit_hosts_only=True)
                    )
                    self.traffic = guard.traffic
                    self.target_proxy = guard
                except OSError:
                    raise ProxyUnavailableError("Target egress guard could not start") from None
                launch_proxy = guard.playwright()
                device = DeviceProfileResolver().resolve(persona.device, playwright.devices)
                result = PersonaValidator().validate(
                    persona,
                    device,
                    "strict",
                    proxy.metadata() if proxy else None,
                )
                if not result.valid:
                    raise ProfileValidationError("; ".join(result.errors))
                for warning in result.warnings:
                    logger.warning(
                        "persona_validation: %s",
                        warning,
                        extra={"persona_id": persona.id, **(log_context or {})},
                    )
                device.pop("default_browser_type", None)
                extension = await asyncio.to_thread(
                    prepare_filter,
                    traffic_policy,
                    persona,
                    profile_path,
                    base_url,
                    incubation=bool(self.settings.incubation_config),
                )
                vendors = (
                    await asyncio.to_thread(local_vendor_extensions)
                    if extension and persona.browser_engine != "webkit"
                    else []
                )
                gecko_preferences = (
                    await asyncio.to_thread(
                        gecko_profile_options,
                        profile_path,
                        [extension, *vendors],
                    )
                    if extension and persona.browser_engine == "firefox"
                    else {}
                )
                gecko_port = debugger_port() if gecko_preferences else None
                cache_preferences = (
                    {
                        "browser.cache.disk.enable": False,
                        "browser.cache.memory.enable": False,
                    }
                    if not self.settings.incubation_config
                    and persona.visit_state
                    and persona.visit_state.cache == "cold"
                    else {}
                )
                try:
                    if persona.runtime.backend == "camoufox":
                        from camoufox.async_api import AsyncNewBrowser

                        preparation = asyncio.create_task(
                            asyncio.to_thread(
                                camoufox_options,
                                persona,
                                profile_path,
                                persona.runtime.headless,
                                proxy,
                                self.settings.camoufox_version,
                                self.settings.camoufox_install_path,
                                [],
                            )
                        )
                        try:
                            options = await asyncio.shield(preparation)
                        except asyncio.CancelledError:
                            # Keep the profile lock until its identity write finishes.
                            await preparation
                            raise
                        options["timeout"] = self.settings.browser_start_timeout * 1000
                        options["env"] = browser_environment(options.get("env"))
                        if persona.display is not None:
                            options.update(persona.display.model_dump())
                        options["proxy"] = launch_proxy
                        headers = emulation_headers(persona)
                        if self.settings.incubation_config:
                            headers = {**headers, "X-Automation-Test": "True"}
                        if headers:
                            options["extra_http_headers"] = headers
                        options.setdefault("firefox_user_prefs", {}).update(
                            {
                                "network.proxy.socks_remote_dns": True,
                                "network.proxy.no_proxies_on": "",
                                "network.proxy.allow_hijacking_localhost": True,
                            }
                        )
                        options["firefox_user_prefs"].update(cache_preferences)
                        options["firefox_user_prefs"].update(gecko_preferences)
                        if gecko_port:
                            options.setdefault("args", []).extend(
                                ["--start-debugger-server", str(gecko_port)],
                            )
                        if block_service_workers:
                            options["service_workers"] = "block"
                        context = await AsyncNewBrowser(
                            playwright, from_options=options, persistent_context=True
                        )
                    else:
                        privacy: dict[str, Any] = {"env": browser_environment()}
                        headers = emulation_headers(persona)
                        if self.settings.incubation_config:
                            headers = {**headers, "X-Automation-Test": "True"}
                        if headers:
                            privacy["extra_http_headers"] = headers
                        if persona.display is not None:
                            privacy.update(persona.display.model_dump())
                        if persona.geolocation:
                            privacy["geolocation"] = persona.geolocation.model_dump()
                        if persona.phone is not None and persona.phone.family == "ios":
                            privacy["user_agent"] = ios_user_agent(persona)
                        if persona.browser_engine == "chromium":
                            privacy["args"] = list(CHROMIUM_LAUNCH_ARGS)
                            privacy["args"].extend(CHROMIUM_DEBUG_ARGS)
                            if persona.runtime.channel:
                                privacy["channel"] = persona.runtime.channel
                            if extension:
                                filter_options = chromium_filter_options(extension, vendors)
                                privacy["args"].extend(filter_options.pop("args"))
                                privacy.update(filter_options)
                            # The local SOCKS guard is also a proxy when no upstream is set.
                            if persona.runtime.webrtc != "default":
                                privacy.setdefault("args", []).append(
                                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"
                                )
                            if persona.runtime.webrtc == "disabled":
                                raise ProfileValidationError(
                                    "Complete WebRTC disabling requires Firefox/Camoufox"
                                )
                        elif persona.browser_engine == "firefox":
                            if gecko_port:
                                privacy["args"] = ["--start-debugger-server", str(gecko_port)]
                            privacy["firefox_user_prefs"] = {
                                **gecko_preferences,
                                **cache_preferences,
                                "media.peerconnection.enabled": persona.runtime.webrtc
                                != "disabled",
                                "media.peerconnection.ice.proxy_only": persona.runtime.webrtc
                                == "proxy_only"
                                and proxy is not None,
                                "network.proxy.socks_remote_dns": True,
                                "network.proxy.no_proxies_on": "",
                                "network.proxy.allow_hijacking_localhost": True,
                            }
                        elif persona.browser_engine == "webkit" and extension:
                            privacy["env"] = await asyncio.to_thread(
                                webkit_filter_environment,
                                extension,
                                privacy["env"],
                            )
                        context = await getattr(
                            playwright, persona.browser_engine
                        ).launch_persistent_context(
                            user_data_dir=str(profile_path),
                            headless=persona.runtime.headless,
                            locale=persona.locale,
                            timezone_id=persona.timezone_id,
                            proxy=launch_proxy,
                            timeout=self.settings.browser_start_timeout * 1000,
                            service_workers="block" if block_service_workers else "allow",
                            **device,
                            **privacy,
                        )
                except (ProfileValidationError, BrowserLaunchError):
                    raise
                except Exception as exc:
                    from syntetic_core._engine.retries import classify_error

                    kind, detail = classify_error(exc)
                    if kind == "ProxyUnavailableError":
                        raise ProxyUnavailableError(detail) from None
                    raise BrowserLaunchError(
                        "Persistent browser context could not be launched"
                    ) from None
                success = False
                identity_accepted = False
                observation: dict[str, Any] = {}
                identity_stack = AsyncExitStack()
                chromium_controller = None
                try:
                    if gecko_port:
                        await install_extensions(gecko_port, profile_path)
                    if extension and persona.browser_engine == "webkit":
                        await asyncio.to_thread(validate_webkit_filter, extension)
                    webkit_native = (
                        await validate_webkit_native(context)
                        if persona.browser_engine == "webkit"
                        else None
                    )
                    await configure_session_apis(context, persona, profile_path)
                    native_brands: dict[str, Any] = {}
                    if persona.browser_engine == "chromium":
                        override = await native_client_hint_identity(context)
                        override["acceptLanguage"] = persona.locale
                        native_brands = {
                            key: override["userAgentMetadata"][key]
                            for key in ("brands", "fullVersionList", "fullVersion")
                        }
                        if persona.runtime.target_os:
                            override = identity_override(
                                persona, context.browser.version if context.browser else "unknown"
                            )
                            override["userAgentMetadata"].update(native_brands)
                        elif device.get("user_agent"):
                            override["userAgent"] = device["user_agent"]
                        await configure_network_identity(context, persona, override, headers)
                    if persona.browser_engine == "chromium":
                        chromium_controller = await identity_stack.enter_async_context(
                            chromium_identity(
                                context,
                                persona,
                                profile_path,
                                native_brands=native_brands,
                                extra_http_headers=headers,
                                network_override=override,
                            )
                        )
                        self.chromium_controller = chromium_controller
                    if persona.phone is not None:
                        if persona.phone.family == "ios":
                            await configure_ios(context, persona, profile_path)
                        # Observe mobile geometry at initial-scale=1; WebKit otherwise
                        # starts about:blank with its 980px legacy layout viewport.
                        page = context.pages[0] if context.pages else await context.new_page()
                        await page.set_content(
                            '<meta name="viewport" content="width=device-width, initial-scale=1">'
                        )
                        if not await page.evaluate("""() =>
                            matchMedia('(pointer: coarse)').matches &&
                            !matchMedia('(hover: hover)').matches
                        """):
                            raise ProfileValidationError(
                                "Phone touch/pointer emulation is unavailable"
                            )
                    if persona.display is not None:
                        # Context options cover frames and future pages in both runtimes.
                        # Existing pages are updated through the same native emulation API.
                        for existing_page in context.pages:
                            await existing_page.emulate_media(**persona.display.model_dump())
                    context.set_default_timeout(self.settings.action_timeout * 1000)
                    context.set_default_navigation_timeout(self.settings.navigation_timeout * 1000)
                    policy = persona.network
                    if policy.needs_probe and not self.settings.network_probe_url:
                        raise ProfileValidationError("Network policy requires NETWORK_PROBE_URL")
                    if self.settings.network_probe_url:
                        async with asyncio.timeout(self.settings.network_probe_timeout):
                            observation = await observe_network(
                                context, self.settings.network_probe_url
                            )
                        validate_network(persona, observation)
                        old_ip = state.get("network", {}).get("ip")
                        if old_ip is None and self.settings.prepared_session_profile:
                            old_ip = (self.settings.incubation_config or {}).get("expected_exit_ip")
                        if (
                            old_ip
                            and observation.get("ip") != old_ip
                            # Mobile egress may deliberately rotate between sessions.
                            # Per-attempt IP checks still enforce continuity once opened.
                            and not (proxy is not None and proxy.kind == "mobile")
                            and (
                                self.settings.prepared_session_profile
                                or started - state.get("identity_since", 0)
                                < policy.min_identity_seconds
                            )
                        ):
                            raise ProxyIdentityChangedError(
                                "Exit IP changed before the allowed interval"
                            )
                    page = context.pages[0] if context.pages else await context.new_page()
                    environment = await page.evaluate("""() => ({
                        user_agent: navigator.userAgent,
                        client_hints: navigator.userAgentData?.toJSON() ?? null,
                        platform: navigator.platform,
                        webdriver: navigator.webdriver,
                        locale: navigator.language,
                        languages: navigator.languages,
                        touch_points: navigator.maxTouchPoints,
                        hardware_concurrency: navigator.hardwareConcurrency,
                        hardware_apis: {
                            device_memory: typeof navigator.deviceMemory === 'number',
                            battery: typeof navigator.getBattery === 'function',
                            accelerometer: typeof Accelerometer === 'function',
                            gyroscope: typeof Gyroscope === 'function',
                            relative_orientation: typeof RelativeOrientationSensor === 'function',
                            sim: 'mozMobileConnections' in navigator
                        },
                        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                        viewport: {width:innerWidth,height:innerHeight},
                        screen: {width:screen.width,height:screen.height},
                        device_scale_factor: devicePixelRatio,
                        color_scheme: matchMedia('(prefers-color-scheme: dark)').matches
                            ? 'dark' : 'light',
                        reduced_motion: matchMedia('(prefers-reduced-motion: reduce)').matches
                            ? 'reduce' : 'no-preference',
                        contrast: matchMedia('(prefers-contrast: more)').matches
                            ? 'more' : 'no-preference',
                        forced_colors: matchMedia('(forced-colors: active)').matches
                            ? 'active' : 'none'
                    })""")
                    if environment["webdriver"] is not False:
                        raise ProfileValidationError(
                            "Every session requires navigator.webdriver=false"
                        )
                    environment["extended"] = await observe_extended(page)
                    if persona.native_audio is not None:
                        environment["native_audio"] = await page.evaluate("""async () => {
                            const audio = new AudioContext();
                            try {
                                return {sample_rate: audio.sampleRate,
                                    output_latency: audio.outputLatency,
                                    max_channels: audio.destination.maxChannelCount};
                            } finally { await audio.close(); }
                        }""")
                    if (
                        not device.get("user_agent")
                        or persona.runtime.backend == "camoufox"
                        or persona.phone is not None
                    ):
                        validate_runtime_environment(
                            persona.browser_engine,
                            environment,
                            context.browser.version if context.browser else "unknown",
                            expected_os=persona.runtime.target_os,
                            phone_form_factor=persona.phone.form_factor if persona.phone else None,
                        )
                    validate_persona_environment(persona, device, environment)
                    await grant_native_permissions(context, persona)
                    if persona.emulation is not None or persona.browser_engine == "chromium":
                        environment["document_emulation"] = await validate_device_emulation(
                            page, persona, main_world=persona.runtime.backend == "camoufox"
                        )
                    if (
                        persona.runtime.browser_version
                        and context.browser
                        and context.browser.version != persona.runtime.browser_version
                    ):
                        raise ProfileValidationError(
                            "runtime.browser_version: installed version differs"
                        )
                    environment["session_apis"] = await validate_session_apis(page, persona)
                    if webkit_native is not None:
                        environment["webkit_native"] = webkit_native
                    self.connection = {
                        "configured_proxy": proxy.metadata() if proxy else None,
                        "observed": observation,
                        "runtime": environment,
                        "session_count": state.get("session_count", 0),
                        "backend": persona.runtime.backend,
                        "browser_version": context.browser.version
                        if context.browser
                        else "unknown",
                        "transport": "mitmproxy" if proxy_override else "browser_native",
                        "target_guard": True,
                        "organic_search": organic_search,
                        "traffic_optimizer": traffic_policy.model_dump(mode="json"),
                    }
                    identity_accepted = True
                    yield context
                    if chromium_controller is not None:
                        chromium_controller.check()
                    success = True
                finally:
                    closed = False
                    try:
                        try:
                            await identity_stack.aclose()
                        finally:
                            async with asyncio.timeout(10):
                                await context.close()
                                closed = True
                    finally:
                        if lock.lost or (lease_guard is not None and not await lease_guard()):
                            raise ProfileLockedError("Profile lease lost during browser cleanup")
                        recorded = record_session(
                            state,
                            engine=persona.browser_engine,
                            backend=persona.runtime.backend,
                            proxy_id=identity_proxy_id,
                            observation=observation,
                            started=started,
                            finished=time(),
                            success=success,
                            identity_accepted=identity_accepted,
                        )
                        recorded["channel"] = persona.runtime.channel
                        if self.settings.prepared_session_profile:
                            recorded["incubation_identity"] = (
                                state["incubation_identity"]
                                if "incubation_identity" in state
                                else await asyncio.to_thread(profile_identity_hashes, profile_path)
                            )
                        await asyncio.to_thread(write_json, state_path, recorded)
                        if closed and self.settings.expected_profile_storage:
                            from syntetic_core._engine.profile_storage import record_closed_store

                            await asyncio.to_thread(
                                record_closed_store,
                                profile_path,
                                persona,
                                self.connection.get("browser_version", "unknown"),
                            )
                        if closed and ram_profile is not None:
                            await finish_io(ram_profile.commit)
        except asyncio.CancelledError:
            if lock.lost:
                raise ProfileLockedError("Profile lease lost; browser session stopped") from None
            raise
        finally:
            try:
                if ram_profile is not None:
                    await finish_io(ram_profile.cleanup)
            finally:
                if hardware_token is not None:
                    session_emulation.reset(hardware_token)
                await asyncio.to_thread(lock.release)
