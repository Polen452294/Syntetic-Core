"""Bound generated identities to compatible model/OS/hardware recipes.

These recipes constrain reported browser properties, not the physical execution host.
Versioned opt-in keeps existing immutable profiles and older workers compatible.
"""

import hashlib
import math
import random
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import (
    BrowserPersona,
    DeviceCoherence,
    EmulatedMediaDevice,
    EmulatedWebGL,
)

if TYPE_CHECKING:
    from syntetic_core._engine.browser_runtime import RuntimeCapability


@dataclass(frozen=True)
class DesktopRecipe:
    id: str
    os: str
    architecture: Literal["x86", "arm"]
    cores: int
    vendor: str
    renderer: str
    max_width: int = 7680
    max_height: int = 4320


DESKTOP_RECIPES = tuple(
    DesktopRecipe(
        f"{system}-{gpu}-{cores}",
        system,
        "x86",
        cores,
        vendor,
        renderer,
        4096 if gpu == "uhd630" else 7680,
        2304 if gpu == "uhd630" else 4320,
    )
    for system, gpu, vendor, renderer, counts in (
        (
            "windows",
            "uhd630",
            "Google Inc. (Intel)",
            "ANGLE (Intel, Intel(R) UHD Graphics 630, D3D11)",
            (4, 8, 12, 16),
        ),
        (
            "windows",
            "rtx3060",
            "Google Inc. (NVIDIA)",
            "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060, D3D11)",
            (12, 16),
        ),
        (
            "windows",
            "rx6600",
            "Google Inc. (AMD)",
            "ANGLE (AMD, AMD Radeon RX 6600, D3D11)",
            (12, 16),
        ),
        (
            "linux",
            "uhd630",
            "Google Inc. (Intel)",
            "ANGLE (Intel, Mesa Intel(R) UHD Graphics 630, OpenGL 4.6)",
            (4, 8, 12, 16),
        ),
        (
            "linux",
            "rx6600",
            "Google Inc. (AMD)",
            "ANGLE (AMD, AMD Radeon RX 6600, OpenGL 4.6)",
            (12, 16),
        ),
    )
    for cores in counts
) + (
    DesktopRecipe(
        "macos-m1-8",
        "macos",
        "arm",
        8,
        "Google Inc. (Apple)",
        "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)",
        6016,
        3384,
    ),
    DesktopRecipe(
        "macos-m2-8",
        "macos",
        "arm",
        8,
        "Google Inc. (Apple)",
        "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)",
        6016,
        3384,
    ),
)
DESKTOP_BY_ID = {recipe.id: recipe for recipe in DESKTOP_RECIPES}

# Exact supported Android models, never a catch-all for an unrecognised model.
# The A55 uses Exynos 1480/Xclipse 530, while Fold6 and Fold7 use different Adreno GPUs.
ANDROID_GPUS = {
    "Pixel 5": ("Qualcomm", "Adreno (TM) 620"),
    "Pixel 5a": ("Qualcomm", "Adreno (TM) 620"),
    "Pixel 6": ("ARM", "Mali-G78"),
    "Pixel 6 Pro": ("ARM", "Mali-G78"),
    "Pixel 6a": ("ARM", "Mali-G78"),
    "Pixel 7": ("ARM", "Mali-G710"),
    "Pixel 7 Pro": ("ARM", "Mali-G710"),
    "Pixel 7a": ("ARM", "Mali-G710"),
    "Pixel 8": ("ARM", "Mali-G715"),
    "Pixel 8 Pro": ("ARM", "Mali-G715"),
    "Pixel 8a": ("ARM", "Mali-G715"),
    "Pixel 9": ("ARM", "Mali-G715"),
    "Pixel 9 Pro": ("ARM", "Mali-G715"),
    "Pixel 9 Pro XL": ("ARM", "Mali-G715"),
    "Pixel 9a": ("ARM", "Mali-G715"),
    "Pixel 10": ("Imagination Technologies", "PowerVR DXT"),
    "Pixel 10 Pro": ("Imagination Technologies", "PowerVR DXT"),
    "Pixel 10 Pro XL": ("Imagination Technologies", "PowerVR DXT"),
    "SM-S921U": ("Qualcomm", "Adreno (TM) 750"),
    "SM-A556B": ("Samsung", "Xclipse 530"),
    "SM-F956U": ("Qualcomm", "Adreno (TM) 750"),
    "SM-F966U": ("Qualcomm", "Adreno (TM) 830"),
}
M1_IPADS = frozenset({"iPad Pro 11 (M1)", "iPad Pro 12.9 (M1)", "iPad Air 5"})


def phone_recipe_id(model: str) -> str:
    return "phone-" + re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def supported_recipe_ids(engine: str) -> list[str]:
    """Recipe vocabulary implemented by this runtime version."""
    from syntetic_core._engine.phone_personas import PRESETS_BY_MODEL

    if engine == "firefox":
        return [
            f"native-{system}-{cores}"
            for system in ("windows", "linux", "macos")
            for cores in ((8, 12, 16) if system == "macos" else (4, 8, 12, 16))
        ]
    phones = [
        phone_recipe_id(model)
        for model, presets in PRESETS_BY_MODEL.items()
        if (engine == "webkit" and presets[0].phone.family == "ios")
        or (engine == "chromium" and model in ANDROID_GPUS)
    ]
    return sorted(phones + (list(DESKTOP_BY_ID) if engine == "chromium" else []))


def phone_gpu(model: str) -> tuple[str, str]:
    from syntetic_core._engine.phone_personas import PRESETS_BY_MODEL

    presets = PRESETS_BY_MODEL.get(model)
    if not presets:
        raise ProfileValidationError("coherence.phone: unknown device model")
    if presets[0].phone.family == "ios":
        return "Apple Inc.", "Apple GPU"
    try:
        return ANDROID_GPUS[model]
    except KeyError:
        raise ProfileValidationError("coherence.phone: model has no verified GPU mapping") from None


def phone_cpu_choices(model: str) -> tuple[int, ...]:
    from syntetic_core._engine.phone_personas import PRESETS_BY_MODEL

    presets = PRESETS_BY_MODEL.get(model)
    if not presets:
        raise ProfileValidationError("coherence.phone: unknown device model")
    if presets[0].phone.family == "android":
        # Reported browser parallelism; not a claim about physical core count (e.g. Tensor G3).
        return (8,)
    return (4, 8) if model in M1_IPADS else (4, 6)


def device_memory_choices(persona: BrowserPersona, browser_version: str = "") -> tuple[int, ...]:
    """Reported GiB, rounded/capped by the engine rather than physical RAM."""
    if persona.phone is not None:
        return (4,) if persona.phone.model in {"Pixel 5a", "Pixel 6a"} else (8,)
    key = persona.coherence.recipe_id if persona.coherence else ""
    renderer = (
        persona.emulation.webgl.renderer.lower()
        if (persona.emulation is not None and persona.emulation.webgl is not None)
        else ""
    )
    choices: tuple[int, ...]
    if persona.runtime.target_os == "macos":
        choices = (8, 16)
    elif any(gpu in key + renderer for gpu in ("rtx3060", "rx6600", "rtx 3060", "rx 6600")):
        choices = (8, 16, 32)
    else:
        choices = (4, 8, 16)
    version = re.match(r"(\d+)\.", browser_version)
    if version and int(version[1]) < 147:
        return tuple(value for value in choices if value <= 8)
    return choices


def mobile_media(persona: BrowserPersona, headset: bool) -> list[EmulatedMediaDevice]:
    assert persona.emulation is not None
    seed = persona.emulation.seed
    devices: list[tuple[Literal["audioinput", "videoinput", "audiooutput"], str, str]] = [
        ("audioinput", "Built-in Microphone", "built-in"),
        ("videoinput", "Front Camera", "front-camera"),
        ("videoinput", "Back Camera", "back-camera"),
        ("audiooutput", "Built-in Speaker", "built-in"),
    ]
    if headset:
        devices += [
            ("audioinput", "Bluetooth Headset Microphone", "headset"),
            ("audiooutput", "Bluetooth Headset", "headset"),
        ]

    def identifier(label: str) -> str:
        return hashlib.sha256(f"{persona.fingerprint_id}:{seed}:{label}".encode()).hexdigest()

    return [
        EmulatedMediaDevice(
            kind=kind, label=label, device_id=identifier(label), group_id=identifier(group)
        )
        for kind, label, group in devices
    ]


def bind_device_recipe(
    persona: BrowserPersona, capability: "RuntimeCapability", rng: random.Random
) -> None:
    if "device_coherence" not in capability.parameters:
        return
    if persona.phone is not None:
        model = persona.phone.model
        if persona.chromium is not None:
            persona.chromium.architecture = "arm"
        if persona.emulation is not None:
            value = persona.emulation
            if value.webgl is not None:
                vendor, renderer = phone_gpu(model)
                value.webgl = EmulatedWebGL(vendor=vendor, renderer=renderer)
            if value.hardware_concurrency is not None:
                value.hardware_concurrency = rng.choice(phone_cpu_choices(model))
            if value.media:
                value.media = mobile_media(persona, any("Headset" in d.label for d in value.media))
        recipe_id = phone_recipe_id(model)
    elif persona.runtime.backend == "camoufox":
        # Feed the SAME count into Camoufox's GPU/coherence sampler and the JS layer.
        cores = rng.choice((8, 12, 16) if persona.runtime.target_os == "macos" else (4, 8, 12, 16))
        if persona.emulation is not None and persona.emulation.hardware_concurrency is not None:
            persona.emulation.hardware_concurrency = cores
        recipe_id = f"native-{persona.runtime.target_os}-{cores}"
    else:
        system = persona.runtime.target_os
        dpr = persona.device.device_scale_factor
        screen = persona.device.screen
        recipes = [
            recipe
            for recipe in DESKTOP_RECIPES
            if recipe.os == system
            and screen["width"] * dpr <= recipe.max_width
            and screen["height"] * dpr <= recipe.max_height
        ]
        if not recipes:
            raise ProfileValidationError("coherence.desktop: no hardware recipe fits this display")
        recipe = rng.choice(recipes)
        if persona.chromium is not None:
            persona.chromium.architecture = recipe.architecture
            if persona.chromium.hardware_concurrency is not None:
                persona.chromium.hardware_concurrency = recipe.cores
        if persona.emulation is not None:
            if persona.emulation.hardware_concurrency is not None:
                persona.emulation.hardware_concurrency = recipe.cores
            if persona.emulation.webgl is not None:
                persona.emulation.webgl = EmulatedWebGL(
                    vendor=recipe.vendor, renderer=recipe.renderer
                )
        recipe_id = recipe.id
    persona.coherence = DeviceCoherence(recipe_id=recipe_id)
    if persona.emulation is not None and persona.emulation.device_memory is not None:
        persona.emulation.device_memory = rng.choice(
            device_memory_choices(persona, capability.browser_version)
        )
    issues = coherence_issues(persona)
    if issues:
        raise ProfileValidationError("; ".join(issues))


def coherence_issues(persona: BrowserPersona) -> list[str]:
    issues = []
    emulation = persona.emulation
    if emulation is not None:
        if persona.browser_engine != "chromium" and (
            emulation.device_memory is not None or emulation.battery is not None
        ):
            issues.append("coherence.hardware: memory and battery require Chromium APIs")
        if persona.coherence is not None and emulation.device_memory is not None:
            if emulation.device_memory not in device_memory_choices(
                persona, persona.runtime.browser_version or ""
            ):
                issues.append("coherence.memory: reported memory differs from device recipe")
        if persona.native_audio is not None and emulation.audio is not None:
            if persona.native_audio != emulation.audio:
                issues.append("coherence.audio: native and document audio parameters differ")
        if persona.native_desktop is not None and emulation.privacy is not None:
            if (
                persona.native_desktop.do_not_track != emulation.privacy.do_not_track
                or persona.native_desktop.global_privacy_control
                != emulation.privacy.global_privacy_control
            ):
                issues.append("coherence.privacy: Navigator and native privacy settings differ")
        if (
            persona.chromium is not None
            and persona.chromium.sensors is not None
            and emulation.sensors is not None
        ):
            issues.append("coherence.sensors: choose the native or document sensor backend")
    counts = [
        value
        for value in (
            persona.phone.hardware_concurrency if persona.phone else None,
            persona.chromium.hardware_concurrency if persona.chromium else None,
            persona.emulation.hardware_concurrency if persona.emulation else None,
        )
        if value is not None
    ]
    if len(set(counts)) > 1:
        issues.append("coherence.cpu: native and document counts differ")
    if persona.phone is not None:
        from syntetic_core._engine.phone_personas import PRESETS_BY_MODEL

        if persona.phone.model in PRESETS_BY_MODEL:
            if any(c > max(phone_cpu_choices(persona.phone.model)) for c in counts):
                issues.append("coherence.cpu: count exceeds the selected mobile model")
            if persona.emulation is not None and persona.emulation.webgl is not None:
                gpu = persona.emulation.webgl
                if (gpu.vendor, gpu.renderer) != phone_gpu(persona.phone.model):
                    issues.append("coherence.webgl: GPU does not fit the selected phone model")
    if persona.coherence is None:
        return issues
    key = persona.coherence.recipe_id
    if persona.phone is not None:
        from syntetic_core._engine.phone_personas import PRESETS_BY_MODEL

        phone = persona.phone
        presets = PRESETS_BY_MODEL.get(phone.model, ())
        preset = next((p for p in presets if p.key == phone.preset_id), None)
        if preset is None or key != phone_recipe_id(phone.model):
            return issues + ["coherence.phone: model/preset/recipe do not match the catalogue"]
        expected = preset.device()
        if (
            phone.family != preset.phone.family
            or phone.form_factor != preset.phone.form_factor
            or phone.os_version != preset.os_version
            or phone.orientation != preset.orientation
            or persona.device.screen != expected.screen
            or persona.device.viewport != expected.viewport
            or persona.device.device_scale_factor != expected.device_scale_factor
            or not persona.device.mobile
            or not persona.device.touch
            or persona.runtime.target_os != phone.family
            or persona.runtime.backend != "playwright"
            or persona.browser_engine != ("chromium" if phone.family == "android" else "webkit")
        ):
            issues.append("coherence.phone: model, OS, engine, screen, DPR or orientation conflict")
        if persona.chromium is not None and persona.chromium.architecture != "arm":
            issues.append("coherence.architecture: mobile Client Hints must use ARM")
        if counts and any(c not in phone_cpu_choices(phone.model) for c in counts):
            issues.append("coherence.cpu: count does not fit the selected phone model")
        if emulation is not None and emulation.webgl is not None:
            if (emulation.webgl.vendor, emulation.webgl.renderer) != phone_gpu(phone.model):
                issues.append("coherence.webgl: GPU does not fit the selected phone model")
        if emulation is not None and emulation.media:
            labels = {d.label for d in emulation.media}
            if not {"Front Camera", "Back Camera"} <= labels or any("USB" in d for d in labels):
                issues.append("coherence.media: mobile identity has a desktop media preset")
    elif persona.runtime.backend == "camoufox":
        allowed = (8, 12, 16) if persona.runtime.target_os == "macos" else (4, 8, 12, 16)
        if key not in {f"native-{persona.runtime.target_os}-{c}" for c in allowed}:
            issues.append("coherence.native: unsupported native OS/CPU recipe")
        elif counts and key != f"native-{persona.runtime.target_os}-{counts[0]}":
            issues.append("coherence.native: CPU count differs from the native recipe")
    else:
        recipe = DESKTOP_BY_ID.get(key)
        if recipe is None:
            return issues + ["coherence.desktop: unknown hardware recipe"]
        if (
            persona.runtime.target_os != recipe.os
            or persona.phone is not None
            or persona.device.mobile
            or persona.device.touch
            or persona.browser_engine != "chromium"
        ):
            issues.append("coherence.desktop: OS, engine or device family differs from recipe")
        if persona.chromium is None or persona.chromium.architecture != recipe.architecture:
            issues.append("coherence.architecture: Client Hints and GPU recipe disagree")
        if any(c != recipe.cores for c in counts):
            issues.append("coherence.cpu: CPU and GPU recipe disagree")
        dpr = persona.device.device_scale_factor
        if recipe.os == "macos" and dpr not in (1, 2):
            issues.append("coherence.screen: macOS display scale must be 1 or 2")
        dimensions = [persona.device.screen.get(axis) for axis in ("width", "height")]
        if not all(type(value) is int and value > 0 for value in dimensions) or (
            not math.isfinite(dpr) or dpr <= 0
        ):
            issues.append("coherence.screen: invalid display geometry")
        elif (
            persona.device.screen["width"] * dpr > recipe.max_width
            or persona.device.screen["height"] * dpr > recipe.max_height
        ):
            issues.append("coherence.screen: physical display exceeds GPU recipe limits")
        if emulation is not None and emulation.webgl is not None:
            if (emulation.webgl.vendor, emulation.webgl.renderer) != (
                recipe.vendor,
                recipe.renderer,
            ):
                issues.append("coherence.webgl: GPU differs from the saved hardware recipe")
    if persona.display is not None:
        if persona.display.forced_colors == "active" and persona.display.contrast != "more":
            issues.append("coherence.display: forced colors require increased contrast")
    if persona.geolocation is not None:
        from syntetic_core._engine.environment_randomization import LOCATION_CENTRES

        centre = LOCATION_CENTRES.get(persona.timezone_id)
        if centre and (
            abs(persona.geolocation.latitude - centre[0]) > 0.015001
            or abs(persona.geolocation.longitude - centre[1]) > 0.015001
        ):
            issues.append("coherence.geolocation: generated coordinates do not match timezone")
    return issues
