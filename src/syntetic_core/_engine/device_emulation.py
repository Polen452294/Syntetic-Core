"""Generate persistent document API parameters only for verified worker features."""

import hashlib
import random
from typing import Literal

from syntetic_core._engine.browser_runtime import RuntimeCapability
from syntetic_core._engine.device_coherence import (
    device_memory_choices,
    phone_cpu_choices,
    phone_gpu,
)
from syntetic_core._engine.personas import (
    BrowserPersona,
    DeviceEmulation,
    EmulatedBattery,
    EmulatedMediaDevice,
    EmulatedPrivacy,
    EmulatedWebGL,
    NativeAudioIdentity,
    StationarySensors,
)

EMULATION_FIELDS = (
    "webgl",
    "fonts",
    "audio",
    "media",
    "voices",
    "hardware_concurrency",
    "privacy",
    "sensors",
    "device_memory",
    "battery",
)

_GPU = {
    "windows": (
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630, D3D11)"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060, D3D11)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6600, D3D11)"),
    ),
    "macos": (("Apple Inc.", "Apple M1"), ("Apple Inc.", "Apple M2")),
    "linux": (("Intel", "Mesa Intel(R) UHD Graphics 630"), ("AMD", "AMD Radeon RX 6600")),
    "android": (("Qualcomm", "Adreno (TM) 740"), ("ARM", "Mali-G715")),
    "ios": (("Apple Inc.", "Apple GPU"),),
}
_FONTS = {
    "windows": ("Arial", "Times New Roman", "Courier New", "Calibri", "Segoe UI", "Verdana"),
    "macos": ("Arial", "Times New Roman", "Courier New", "Helvetica", "Menlo", "Verdana"),
    "linux": ("DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono", "Liberation Sans", "Noto Sans"),
    "android": ("Roboto", "Noto Sans", "Noto Serif", "Droid Sans Mono"),
    "ios": ("Arial", "Times New Roman", "Courier New", "Helvetica", "Menlo", "Verdana"),
}


def randomize_device_emulation(
    persona: BrowserPersona, capability: RuntimeCapability, rng: random.Random
) -> None:
    supported = set(capability.parameters)
    if not any("emulation_" + field in supported for field in EMULATION_FIELDS):
        return
    value = DeviceEmulation(seed=rng.randint(1, 2**32 - 1))
    system = persona.runtime.target_os or "linux"
    if "emulation_webgl" in supported and persona.runtime.backend != "camoufox":
        vendor, renderer = rng.choice(_GPU[system])
        if persona.phone is not None:
            vendor, renderer = phone_gpu(persona.phone.model)
        value.webgl = EmulatedWebGL(vendor=vendor, renderer=renderer)
    if "emulation_fonts" in supported and persona.runtime.backend != "camoufox":
        fonts = _FONTS[system]
        value.fonts = list(fonts[:3]) + [font for font in fonts[3:] if rng.random() < 0.5]
    if "emulation_audio" in supported and persona.native_audio is None:
        value.audio = NativeAudioIdentity(
            sample_rate=rng.choice((44100, 48000)), buffer_frames=rng.choice((256, 512, 1024))
        )
    if "emulation_media" in supported and persona.native_media is None:
        mode = rng.choice(("none", "laptop", "conference"))
        devices: list[tuple[Literal["audioinput", "videoinput", "audiooutput"], str, str]]
        devices = (
            []
            if mode == "none"
            else [
                ("audioinput", "Built-in Microphone", "built-in"),
                ("videoinput", "Integrated Camera", "camera"),
                ("audiooutput", "Built-in Speakers", "built-in"),
            ]
        )
        if mode == "conference":
            devices += [
                ("audioinput", "USB Headset Microphone", "headset"),
                ("audiooutput", "USB Headset Speakers", "headset"),
            ]

        def identifier(label: str) -> str:
            return hashlib.sha256(
                f"{persona.fingerprint_id}:{value.seed}:{label}".encode()
            ).hexdigest()

        value.media = [
            EmulatedMediaDevice(
                kind=kind, label=label, device_id=identifier(label), group_id=identifier(group)
            )
            for kind, label, group in devices
        ]
    if "emulation_voices" in supported and persona.native_media is None:
        value.voices = rng.choice(("subset", "local", "none"))
    if "emulation_hardware_concurrency" in supported:
        value.hardware_concurrency = (
            rng.choice(phone_cpu_choices(persona.phone.model))
            if persona.phone is not None and persona.phone.family == "ios"
            else persona.hardware_concurrency_override or rng.choice((4, 8, 12, 16))
        )
    if "emulation_privacy" in supported and persona.native_desktop is None:
        value.privacy = EmulatedPrivacy(
            do_not_track=rng.random() < 0.25, global_privacy_control=rng.random() < 0.15
        )
    if "emulation_sensors" in supported and not (
        persona.chromium is not None and persona.chromium.sensors is not None
    ):
        value.sensors = StationarySensors(
            roll=round(rng.uniform(-15, 15), 3),
            pitch=round(rng.uniform(35, 75), 3),
            yaw=round(rng.uniform(0, 359.999), 3),
        )
    if persona.browser_engine == "chromium":
        if "emulation_device_memory" in supported:
            value.device_memory = rng.choice(
                device_memory_choices(persona, capability.browser_version)
            )
        if "emulation_battery" in supported:
            value.battery = EmulatedBattery(
                charging=rng.random() < 0.35,
                level=rng.randint(30, 99) / 100,
                charge_seconds=rng.choice((5400, 7200, 10800)),
                discharge_seconds=rng.choice((14400, 21600, 28800, 43200)),
            )
    persona.emulation = value
