"""Advertise only installed runtimes that passed an actual startup/environment smoke test."""

import asyncio
import platform
import random
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from syntetic_core._engine.browser.factory import BrowserContextFactory
from syntetic_core._engine.browser.sensors import observe_sensors, readings_match
from syntetic_core._engine.browser_runtime import CapabilityManifest, RuntimeCapability
from syntetic_core._engine.config import Settings
from syntetic_core._engine.personas import (
    BrowserPersona,
    ChromiumIdentity,
    DeviceConfig,
    DisplayPreferences,
    NativeAudioIdentity,
    RuntimeConfig,
    StationarySensors,
)
from syntetic_core._engine.phone_personas import randomize_phone
from syntetic_core._engine.webkit_policy import (
    WEBKIT_HOST_LIMITATION,
    WEBKIT_NATIVE_CAPABILITY,
    webkit_host_allowed,
)


def installed_adapters() -> list[str]:
    return ["environment", "network"]


async def discover_capabilities(settings: Settings) -> dict:
    system: Literal["windows", "linux", "macos"] = {
        "Windows": "windows",
        "Linux": "linux",
        "Darwin": "macos",
    }[platform.system()]  # type: ignore[assignment]
    manifest = CapabilityManifest(
        profile_archive_version=1 if settings.profile_archive_enabled else 0,
        profile_storage_shared=settings.profile_storage_shared,
        interaction_policy_version=2,
        visit_settings_version=2,
        analytics_balancer_version=1,
        automatic_runs_version=1,
        cookie_farming_version=2,
        operating_system=system,
        architecture=platform.machine(),
        dependencies={name: version(name) for name in ("playwright", "camoufox", "pydantic")},
        limitations=[
            "Browser channels and stock Firefox are unverified; phones are emulated",
            "ARM64 runtimes require explicit opt-in and successful native capability checks",
            "Native browser transport supports only allowed destinations; QUIC is unavailable",
        ],
    )
    runtimes: list[
        tuple[Literal["playwright", "camoufox"], Literal["chromium", "firefox", "webkit"]]
    ] = [
        ("playwright", "chromium"),
        ("camoufox", "firefox"),
        ("playwright", "webkit"),
    ]
    if settings.fixed_session_configuration:
        runtimes = [("camoufox", "firefox")]
        manifest.limitations = [
            "Fixed Camoufox desktop; headful requires a verified display",
            "ARM64 requires experimental non-production opt-in and installed smoke",
        ]
    for backend, engine in runtimes:
        capability = RuntimeCapability(
            backend=backend,
            engine=engine,
            browser_version="unknown",
            installed=False,
            smoke_test="unavailable",
        )
        if backend == "playwright":
            capability.limitations = [
                "GPU/WebGL, fonts, audio seed, media devices and voices are not randomized "
                "by the standard emulation APIs.",
                "Physical RAM and SIM remain native; Chromium document memory/battery "
                "use the mandatory session policy. Other engines retain their native API surface.",
            ]
            if engine == "webkit":
                capability.limitations.extend(
                    [
                        "Native CPU count emulation is unavailable.",
                        "Native virtual phone sensors are unavailable.",
                        "The iPhone platform/touch compatibility script covers documents, "
                        "not a physical iOS device or every worker API.",
                    ]
                )
        else:
            capability.limitations = [
                "Generated hardware identity does not change the physical host hardware.",
                "This Camoufox build has no native RAM, battery, SIM or sensor overrides; "
                "optional JS sensors are advertised separately.",
            ]
        manifest.runtimes.append(capability)
        if engine == "webkit" and not webkit_host_allowed(system):
            capability.limitations.append(WEBKIT_HOST_LIMITATION)
            continue
        architecture = platform.machine().lower()
        experimental_arm = (
            system == "linux"
            and architecture in {"aarch64", "arm64"}
            and settings.experimental_arm64
        )
        native_apple_arm = system == "macos" and architecture in {"aarch64", "arm64"}
        if (
            architecture
            not in {
                "amd64",
                "x86_64",
            }
            and not experimental_arm
            and not native_apple_arm
        ):
            continue
        smoke_settings = settings.model_copy(
            update={
                "proxy_required": False,
                "proxies": [],
                "network_probe_url": None,
                "persona_validation": "strict",
                "controller_url": None,
                "distributed_workers": False,
                "profile_lock_distributed": False,
                "profile_storage_shared": False,
                "profile_ram_enabled": False,
                "production_mode": False,
            }
        )
        persona = BrowserPersona(
            id="1",
            browser_engine=engine,
            runtime=RuntimeConfig(
                backend=backend,
                headless=settings.browser_headless,
                target_os="macos" if system != "macos" else "windows",
            ),
            display=DisplayPreferences(
                color_scheme="dark", reduced_motion="reduce", contrast="more"
            ),
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            device=DeviceConfig(
                source="custom",
                viewport={"width": 1280, "height": 800},
                screen={"width": 1440, "height": 900},
                device_scale_factor=2,
            ),
        )
        if engine == "webkit":
            persona = randomize_phone(persona, "ios", random.Random(0))
        elif engine == "chromium":
            persona.chromium = ChromiumIdentity(
                platform_version="15.6.0" if persona.runtime.target_os == "macos" else "19.0.0",
                hardware_concurrency=4,
            )
        elif backend == "camoufox" and not settings.fixed_session_configuration:
            persona.native_audio = NativeAudioIdentity(sample_rate=44100, buffer_frames=512)
        if settings.fixed_session_configuration:
            from syntetic_core._engine.personas import NetworkPolicy
            from syntetic_core._engine.session_configuration import session_persona

            persona = session_persona("1")
            # Startup capability checks are local, without the paid upstream proxy.
            persona.proxy_id = None
            persona.network = NetworkPolicy()
        try:
            with tempfile.TemporaryDirectory(prefix="runtime-smoke-") as root:
                factory = BrowserContextFactory(smoke_settings)
                async with asyncio.timeout(settings.browser_start_timeout + 10):
                    async with factory.open(
                        persona,
                        Path(root) / "1/browser-data",
                        block_service_workers=not settings.fixed_session_configuration,
                    ) as context:
                        if (
                            factory.connection.get("transport") != "browser_native"
                            or factory.connection.get("target_guard") is not True
                        ):
                            raise RuntimeError("Native transport guard was not confirmed")
                        observed = factory.connection["runtime"]
                        if observed.get("session_apis", {}).get("version") != 1:
                            raise RuntimeError("Mandatory session API policy was not confirmed")
                        if engine == "webkit":
                            proof = observed.get("webkit_native", {})
                            if (
                                proof.get("version") != 1
                                or proof.get("passed") is not True
                                or proof.get("host") != system
                            ):
                                raise RuntimeError("Native WebKit media was not confirmed")
                        if (
                            observed["locale"] != persona.locale
                            or observed["timezone"] != persona.timezone_id
                            or observed["viewport"] != persona.device.viewport
                            or observed["screen"] != persona.device.screen
                            or observed["device_scale_factor"] != persona.device.device_scale_factor
                            or (
                                persona.hardware_concurrency_override is not None
                                and observed.get("hardware_concurrency")
                                != persona.hardware_concurrency_override
                            )
                        ):
                            continue
                        capability.browser_version = (
                            context.browser.version if context.browser else "unknown"
                        )
                        capability.installed = True
                        capability.smoke_test = "passed"
                        capability.headless = persona.runtime.headless
                        capability.headful = not persona.runtime.headless
                        capability.device_sources = ["desktop", "custom"]
                        capability.parameters = [
                            "locale",
                            "timezone_id",
                            "viewport",
                            "screen",
                            "device_scale_factor",
                            "network",
                            "native_transport",
                            "session_api_policy_v1",
                            "persistent_storage",
                            "target_os",
                            "display_preferences",
                        ]
                        if backend == "playwright":
                            if engine == "chromium":
                                capability.permissions = ["geolocation"]
                                capability.parameters.extend(
                                    ["permissions", "geolocation", "hardware_concurrency"]
                                )
                            elif engine == "webkit":
                                capability.parameters.extend(
                                    ["phone_ios", WEBKIT_NATIVE_CAPABILITY]
                                )
                        elif persona.native_audio is not None:
                            capability.parameters.append("native_audio")
                        capability.diagnostic_adapters = installed_adapters()
                if engine == "chromium" and capability.installed:
                    phone = randomize_phone(persona, "android", random.Random(0))
                    try:
                        async with asyncio.timeout(settings.browser_start_timeout + 10):
                            async with BrowserContextFactory(smoke_settings).open(
                                phone,
                                Path(root) / "android" / "1/browser-data",
                                block_service_workers=True,
                            ):
                                capability.parameters.append("phone_android")
                    except Exception:
                        # Keep the verified desktop runtime when mobile emulation fails.
                        pass
                    if "phone_android" in capability.parameters and phone.chromium is not None:
                        phone.chromium.sensors = StationarySensors(roll=10, pitch=50, yaw=25)
                        try:
                            async with asyncio.timeout(settings.browser_start_timeout + 10):
                                async with BrowserContextFactory(smoke_settings).open(
                                    phone,
                                    Path(root) / "sensors" / "1/browser-data",
                                    block_service_workers=True,
                                ) as context:
                                    page = await context.new_page()
                                    probe_url = "https://localhost/__native_sensor_probe__"
                                    await context.grant_permissions(
                                        ["accelerometer", "gyroscope"], origin="https://localhost"
                                    )
                                    await page.route(
                                        probe_url,
                                        lambda route: route.fulfill(
                                            content_type="text/html",
                                            body="<title>Sensor probe</title>",
                                        ),
                                    )
                                    await page.goto(probe_url)
                                    if readings_match(
                                        phone.chromium.sensors, await observe_sensors(page)
                                    ):
                                        capability.parameters.append("virtual_sensors")
                                        capability.permissions.extend(
                                            ["accelerometer", "gyroscope"]
                                        )
                        except Exception:
                            # Optional sensor support never removes the verified phone runtime.
                            pass
                        if "virtual_sensors" not in capability.parameters:
                            capability.limitations.append("Virtual sensor smoke did not pass.")
        except Exception:
            # Do not serialize launch exceptions: they may contain paths or credentials.
            capability.smoke_test = "failed"
    if not settings.fixed_session_configuration:
        from syntetic_core._engine.environment_capabilities import verify_extensions

        for capability in manifest.runtimes:
            if capability.installed and capability.smoke_test == "passed":
                seed = BrowserPersona(
                    id="1",
                    browser_engine=capability.engine,
                    runtime=RuntimeConfig(
                        backend=capability.backend,
                        headless=settings.browser_headless,
                        target_os="windows",
                    ),
                )
                if capability.engine == "webkit":
                    seed = randomize_phone(seed, "ios", random.Random(0))
                elif capability.engine == "chromium":
                    seed.chromium = ChromiumIdentity(
                        platform_version="19.0.0", hardware_concurrency=4
                    )
                with tempfile.TemporaryDirectory(prefix="environment-smoke-") as directory:
                    await verify_extensions(smoke_settings, seed, capability, Path(directory))
                if capability.engine == "chromium" and not {
                    "emulation_device_memory",
                    "emulation_battery",
                } <= set(capability.parameters):
                    capability.parameters.remove("session_api_policy_v1")
                    capability.smoke_test = "failed"
                    capability.limitations.append(
                        "Mandatory Chromium hardware API smoke did not pass."
                    )
    return manifest.model_dump(mode="json")
