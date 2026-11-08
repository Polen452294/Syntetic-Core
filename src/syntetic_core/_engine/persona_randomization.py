"""Choose a coherent fingerprint once, when creating a new persistent profile."""

import random
from collections.abc import Sequence
from typing import Literal, NamedTuple
from uuid import uuid4

from syntetic_core._engine.browser_runtime import (
    CapabilityManifest,
    RuntimeCompatibilityError,
    require_compatible,
)
from syntetic_core._engine.personas import (
    BrowserPersona,
    ChromiumIdentity,
    DeviceConfig,
    DeviceFamily,
    DisplayPreferences,
    NativeAudioIdentity,
    StationarySensors,
)
from syntetic_core._engine.webkit_policy import verified_webkit_worker

RuntimeBackend = Literal["camoufox", "playwright"]
RuntimeOS = Literal["windows", "macos", "linux"]
TARGET_OPERATING_SYSTEMS: tuple[RuntimeOS, ...] = ("windows", "macos", "linux")
TARGET_OS_WEIGHTS: dict[RuntimeOS, float] = {"windows": 79, "macos": 16, "linux": 5}

# Select language and timezone together rather than generating unrelated values.
LOCALE_TIMEZONES = (
    ("ru-RU", "Europe/Moscow"),
    ("en-US", "America/New_York"),
    ("en-US", "America/Los_Angeles"),
    ("en-GB", "Europe/London"),
    ("de-DE", "Europe/Berlin"),
    ("fr-FR", "Europe/Paris"),
    ("es-ES", "Europe/Madrid"),
    ("it-IT", "Europe/Rome"),
    ("pl-PL", "Europe/Warsaw"),
    ("pt-BR", "America/Sao_Paulo"),
    ("ja-JP", "Asia/Tokyo"),
    ("en-AU", "Australia/Sydney"),
)


class DesktopPreset(NamedTuple):
    screen_width: int
    screen_height: int
    viewport_width: int
    viewport_height: int
    dpr: float

    def device(self) -> DeviceConfig:
        return DeviceConfig(
            screen={"width": self.screen_width, "height": self.screen_height},
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            device_scale_factor=self.dpr,
        )


# Sizes are CSS pixels; high-DPI laptop displays therefore have smaller logical screens.
# Phone/touch identities use their own coherent catalogue in phone_personas.py.
_LEGACY_PRESETS = (
    DesktopPreset(1366, 768, 1280, 680, 1),
    DesktopPreset(1536, 864, 1360, 768, 1.25),
    DesktopPreset(1920, 1080, 1600, 900, 1),
    DesktopPreset(1920, 1080, 1440, 900, 1.5),
    DesktopPreset(2560, 1440, 1920, 1080, 1),
    DesktopPreset(1280, 800, 1200, 700, 2),
    DesktopPreset(1440, 900, 1280, 800, 2),
)


def _desktop_presets() -> tuple[DesktopPreset, ...]:
    # Logical displays paired with their scale, including laptops, desktop monitors,
    # Retina panels and ultrawides. Window sizes vary without inventing display modes.
    displays = (
        (1280, 720, 1),
        (1366, 768, 1),
        (1440, 900, 1),
        (1600, 900, 1),
        (1680, 1050, 1),
        (1920, 1080, 1),
        (1920, 1200, 1),
        (2560, 1080, 1),
        (2560, 1440, 1),
        (2560, 1600, 1),
        (3440, 1440, 1),
        (3840, 2160, 1),
        (1536, 864, 1.25),
        (1536, 960, 1.25),
        (2048, 1152, 1.25),
        (2048, 1280, 1.25),
        (2752, 1152, 1.25),
        (3072, 1728, 1.25),
        (1280, 720, 1.5),
        (1440, 960, 1.5),
        (1707, 960, 1.5),
        (1920, 1080, 1.5),
        (1920, 1200, 1.5),
        (2560, 1440, 1.5),
        (1280, 800, 1.75),
        (1463, 823, 1.75),
        (1600, 1000, 1.75),
        (1280, 800, 2),
        (1440, 900, 2),
        (1470, 956, 2),
        (1512, 982, 2),
        (1600, 1000, 2),
        (1728, 1117, 2),
        (1800, 1169, 2),
        (1920, 1080, 2),
        (1920, 1200, 2),
        (2048, 1152, 2),
        (2560, 1440, 2),
    )
    presets = list(_LEGACY_PRESETS)
    for width, height, dpr in displays:
        for width_ratio, height_ratio in ((1, 1), (0.95, 0.9), (0.9, 0.85), (0.8, 0.8), (0.7, 0.7)):
            viewport_width = min(2560, int(width * width_ratio) // 8 * 8)
            # Camoufox's real toolbar needs 86 CSS px; leave a small margin so
            # its coherence guard never has to shrink the assigned content area.
            viewport_height = max(480, min(1440, int((height - 96) * height_ratio) // 8 * 8))
            presets.append(DesktopPreset(width, height, viewport_width, viewport_height, dpr))
    return tuple(dict.fromkeys(presets))


DESKTOP_PRESETS = _desktop_presets()
CHROMIUM_PLATFORM_VERSIONS = {
    "windows": ("10.0.0", "13.0.0", "15.0.0", "19.0.0"),
    "macos": ("13.7.0", "14.7.0", "15.6.0", "26.0.0"),
    "linux": ("",),
}


def _randomize_behavior(persona: BrowserPersona, rng: random.Random) -> None:
    if not persona.behavior.enabled:
        return
    # Pick a pace first, then vary its bounds: a profile retains its own typing,
    # scrolling and cursor speed, while individual actions still draw fresh timings.
    pace = rng.choice((0.75, 1, 1.3, 1.6))
    persona.behavior.pause_min_ms = round(rng.randint(90, 220) * pace)
    persona.behavior.pause_max_ms = round(rng.randint(550, 1100) * pace)
    persona.behavior.key_min_ms = round(rng.randint(20, 50) * pace)
    persona.behavior.key_max_ms = round(rng.randint(120, 210) * pace)
    persona.behavior.scroll_steps = rng.randint(6, 18)
    persona.behavior.cursor_seconds = round(rng.uniform(0.5, 1.8) * pace, 2)


def initialize_profile_fingerprint(template: BrowserPersona) -> BrowserPersona:
    """Assign an identity once; subsequent visits must retain the same fingerprint."""
    persona = template.model_copy(deep=True)
    if persona.fingerprint_id is None:
        persona.fingerprint_id = uuid4().hex
    persona.config_hash = persona.digest()
    return persona


def randomize_persona(
    template: BrowserPersona,
    runtimes: Sequence[RuntimeBackend],
    *,
    worker_capabilities: dict | None = None,
    rng: random.Random | None = None,
    device_weights: dict[DeviceFamily, int] | None = None,
    device_family: DeviceFamily | None = None,
    ios_emulation: Literal["current", "legacy"] = "current",
) -> BrowserPersona:
    rng = rng if rng is not None else random.SystemRandom()
    persona = initialize_profile_fingerprint(template)
    persona.locale, persona.timezone_id = rng.choice(LOCALE_TIMEZONES)
    persona.device = rng.choice(DESKTOP_PRESETS).device()
    persona.phone = None
    persona.native_audio = None
    persona.native_desktop = None
    persona.native_media = None
    persona.emulation = None
    persona.coherence = None
    persona.geolocation = None
    persona.visit_state = None
    _randomize_behavior(persona, rng)
    weights = device_weights if device_weights is not None else {"desktop": 100}
    families: list[DeviceFamily] = ["desktop", "android", "ios"]
    available_families: list[DeviceFamily] = []
    for family in families:
        if device_family is not None and family != device_family:
            continue
        if device_family is None and weights.get(family, 0) <= 0:
            continue
        if family == "ios" and not verified_webkit_worker(worker_capabilities):
            continue
        if family != "desktop":
            if "playwright" not in runtimes:
                continue
            if worker_capabilities is not None:
                engine = "chromium" if family == "android" else "webkit"
                if not any(
                    runtime.get("backend") == "playwright"
                    and runtime.get("engine") == engine
                    and runtime.get("installed")
                    and runtime.get("smoke_test") == "passed"
                    and f"phone_{family}" in runtime.get("parameters", [])
                    for runtime in worker_capabilities.get("runtimes", [])
                ):
                    continue
        elif worker_capabilities is not None:
            if not any(
                runtime.get("backend") in runtimes
                and runtime.get("engine") in {"chromium", "firefox"}
                and runtime.get("installed")
                and runtime.get("smoke_test") == "passed"
                for runtime in worker_capabilities.get("runtimes", [])
            ):
                continue
        available_families.append(family)
    if not available_families:
        raise RuntimeCompatibilityError(
            "device_family" if device_family else "profile_randomization.runtimes"
        )
    family = (
        available_families[0]
        if len(available_families) == 1
        else rng.choices(
            available_families,
            weights=[weights.get(item, 0) for item in available_families],
            k=1,
        )[0]
    )
    if family != "desktop":
        from syntetic_core._engine.phone_personas import randomize_phone

        runtime_parameters: list[str] = next(
            (
                runtime.get("parameters", [])
                for runtime in (worker_capabilities or {}).get("runtimes", [])
                if runtime.get("engine") == ("webkit" if family == "ios" else "chromium")
                and runtime.get("installed")
                and runtime.get("smoke_test") == "passed"
            ),
            [],
        )
        phone = randomize_phone(
            persona,
            family,
            rng,
            allow_tablets="tablet_ios" in runtime_parameters,
            allow_foldables="foldable" in runtime_parameters,
        )
        phone.display = DisplayPreferences(
            color_scheme="dark" if rng.random() < 0.5 else "light",
            reduced_motion="reduce" if rng.random() < 0.06 else "no-preference",
            contrast="more" if rng.random() < 0.05 else "no-preference",
        )
        if (
            family == "android"
            and phone.chromium is not None
            and (
                worker_capabilities is None
                or "virtual_sensors" in require_compatible(phone, worker_capabilities).parameters
            )
        ):
            phone.chromium.sensors = StationarySensors(
                roll=round(rng.uniform(-15, 15), 3),
                pitch=round(rng.uniform(35, 75), 3),
                yaw=round(rng.uniform(0, 359.999), 3),
            )
        if worker_capabilities is not None:
            from syntetic_core._engine.environment_randomization import extend_environment

            capability = require_compatible(phone, worker_capabilities)
            if family == "ios" and ios_emulation == "legacy":
                # Retain the stock WebKit device preset and native conditions.
                # Do not add the optional document identity or its device recipe.
                capability = capability.model_copy(
                    update={
                        "parameters": [
                            parameter
                            for parameter in capability.parameters
                            if not parameter.startswith("emulation_")
                            and parameter != "device_coherence"
                        ],
                    }
                )
            extend_environment(phone, capability, rng)
            from syntetic_core._engine.device_coherence import bind_device_recipe

            bind_device_recipe(phone, capability, rng)
            require_compatible(phone, worker_capabilities)
        phone.config_hash = phone.digest()
        return phone
    candidates: list[BrowserPersona] = []
    for backend in dict.fromkeys(runtimes):
        candidate = persona.model_copy(deep=True)
        candidate.runtime.backend = backend
        candidate.browser_engine = "firefox" if backend == "camoufox" else "chromium"
        candidate.runtime.target_os = None
        candidate.chromium = None
        candidate.display = None
        target_systems = list(TARGET_OPERATING_SYSTEMS)
        os_supported = True
        display_supported = True
        cpu_supported = True
        audio_supported = True
        if worker_capabilities is not None:
            try:
                capability = require_compatible(candidate, worker_capabilities)
            except RuntimeCompatibilityError:
                continue
            if "target_os" not in capability.parameters:
                os_supported = False
                target_systems = [
                    CapabilityManifest.model_validate(worker_capabilities).operating_system
                ]
            display_supported = "display_preferences" in capability.parameters
            cpu_supported = "hardware_concurrency" in capability.parameters
            audio_supported = "native_audio" in capability.parameters
        if backend == "camoufox" or os_supported:
            candidate.runtime.target_os = rng.choices(
                target_systems, weights=[TARGET_OS_WEIGHTS[os] for os in target_systems], k=1
            )[0]
            if candidate.runtime.target_os == "macos":
                # Use typical Retina laptop geometry for generated Mac profiles.
                retina_presets = [preset for preset in DESKTOP_PRESETS if preset.dpr == 2]
                if retina_presets:
                    candidate.device = rng.choice(retina_presets).device()
            if backend == "playwright":
                candidate.chromium = ChromiumIdentity(
                    platform_version=rng.choice(
                        CHROMIUM_PLATFORM_VERSIONS[candidate.runtime.target_os]
                    ),
                    hardware_concurrency=rng.choice((4, 8, 12, 16)) if cpu_supported else None,
                )
        if backend == "camoufox" and audio_supported:
            candidate.native_audio = NativeAudioIdentity(
                sample_rate=rng.choice((44100, 48000)),
                buffer_frames=rng.choice((256, 512, 1024)),
            )
        if display_supported:
            forced_colors = rng.random() < 0.01
            candidate.display = DisplayPreferences(
                color_scheme="dark" if rng.random() < 0.35 else "light",
                reduced_motion="reduce" if rng.random() < 0.06 else "no-preference",
                contrast="more" if forced_colors or rng.random() < 0.04 else "no-preference",
                forced_colors="active" if forced_colors else "none",
            )
        candidate.config_hash = candidate.digest()
        if worker_capabilities is not None:
            from syntetic_core._engine.environment_randomization import extend_environment

            extend_environment(candidate, capability, rng)
            from syntetic_core._engine.device_coherence import bind_device_recipe

            bind_device_recipe(candidate, capability, rng)
            require_compatible(candidate, worker_capabilities)
            candidate.config_hash = candidate.digest()
        candidates.append(candidate)
    if not candidates:
        raise RuntimeCompatibilityError("profile_randomization.runtimes")
    return rng.choice(candidates)
