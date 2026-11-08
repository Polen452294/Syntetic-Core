"""Additional environment conditions, bounded by the verified worker contract."""

import random
from typing import Literal

from syntetic_core._engine.browser_experiments import NativeMediaPreset
from syntetic_core._engine.browser_runtime import RuntimeCapability
from syntetic_core._engine.personas import (
    BrowserPersona,
    ChromiumExperience,
    FoldableDisplay,
    GeolocationConfig,
    NativeDesktopIdentity,
    SensorMotion,
    VisitState,
)

# Language and timezone are chosen by the existing geography/pool policy.
# These centres only provide a compatible local test location and bounded jitter.
LOCATION_CENTRES = {
    "Europe/Moscow": (55.7558, 37.6173),
    "America/New_York": (40.7128, -74.0060),
    "America/Los_Angeles": (34.0522, -118.2437),
    "Europe/London": (51.5074, -0.1278),
    "Europe/Berlin": (52.5200, 13.4050),
    "Europe/Paris": (48.8566, 2.3522),
    "Europe/Madrid": (40.4168, -3.7038),
    "Europe/Rome": (41.9028, 12.4964),
    "Europe/Warsaw": (52.2297, 21.0122),
    "America/Sao_Paulo": (-23.5505, -46.6333),
    "Asia/Tokyo": (35.6762, 139.6503),
    "Australia/Sydney": (-33.8688, 151.2093),
}


def randomize_location(persona: BrowserPersona, rng: random.Random) -> None:
    centre = LOCATION_CENTRES.get(persona.timezone_id)
    if centre is None:
        persona.geolocation = None
        if persona.visit_state is not None:
            persona.visit_state.grant_geolocation = False
        return
    persona.geolocation = GeolocationConfig(
        latitude=round(centre[0] + rng.uniform(-0.015, 0.015), 6),
        longitude=round(centre[1] + rng.uniform(-0.015, 0.015), 6),
        accuracy=rng.choice((20, 50, 100, 500)),
    )


def extend_environment(
    persona: BrowserPersona, capability: RuntimeCapability, rng: random.Random
) -> None:
    parameters = capability.parameters
    if persona.runtime.backend == "camoufox" and "native_media" in parameters:
        persona.native_media = NativeMediaPreset(
            devices=rng.choice(("library", "laptop", "conference", "none")),
            voices=rng.choice(("library", "local", "none")),
        )
    if "geolocation" in parameters:
        randomize_location(persona, rng)
    if "visit_state" in parameters:
        persona.visit_state = VisitState(
            visitor="new",
            cache="cold",
            grant_geolocation=persona.geolocation is not None and rng.random() < 0.5,
        )
    if persona.chromium is not None:
        if "chromium_experience" in parameters:
            persona.chromium.experience = ChromiumExperience(
                text_scale=rng.choice((1, 1, 1.1, 1.25)),
                save_data=rng.random() < 0.15,
                cpu_slowdown=rng.choice((1, 1, 1.5, 2)),
            )
            if persona.phone is not None and persona.phone.form_factor == "foldable":
                orientation: Literal["vertical", "horizontal"] = (
                    "vertical" if persona.phone.orientation == "portrait" else "horizontal"
                )
                dimension = "width" if orientation == "vertical" else "height"
                persona.chromium.experience.foldable = FoldableDisplay(
                    posture=rng.choice(("continuous", "folded")),
                    orientation=orientation,
                    offset=persona.device.viewport[dimension] // 2,
                )
        if "sensor_motion" in parameters and persona.chromium.sensors is not None:
            persona.chromium.motion = SensorMotion(
                amplitude=round(rng.uniform(1, 3), 2),
                period_seconds=rng.choice((6, 8, 10)),
                frequency=5,
            )
    if persona.runtime.backend == "camoufox" and "native_desktop" in parameters:
        assert capability.window_insets is not None
        inset = capability.window_insets
        device = persona.device
        top = rng.choice((24, 28)) if persona.runtime.target_os == "macos" else 0
        bottom = (
            rng.choice((40, 48))
            if persona.runtime.target_os == "windows"
            else rng.choice((32, 48, 64))
        )
        avail_height = device.screen["height"] - top - bottom
        width = min(device.viewport["width"], device.screen["width"] - inset.width)
        height = min(device.viewport["height"], avail_height - inset.height)
        device.viewport = {"width": width, "height": height}
        persona.native_desktop = NativeDesktopIdentity(
            avail_top=top,
            avail_width=device.screen["width"],
            avail_height=avail_height,
            outer_width=width + inset.width,
            outer_height=height + inset.height,
            config_height_offset=inset.config_height_offset,
            do_not_track=rng.random() < 0.25,
            global_privacy_control=rng.random() < 0.15,
        )
    from syntetic_core._engine.device_emulation import randomize_device_emulation

    randomize_device_emulation(persona, capability, rng)
