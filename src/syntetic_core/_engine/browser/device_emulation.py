"""Install explicit document API emulation while preserving native implementations."""

import asyncio
import json
import math
import platform
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from time import time
from typing import Any
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary

from playwright.async_api import BrowserContext, Frame, Page

from syntetic_core._engine.browser.identity import read_json, write_json
from syntetic_core._engine.browser.native_functions import native_script
from syntetic_core._engine.browser.sensors import perlin_value_and_rate, sensor_readings
from syntetic_core._engine.browser.session_hardware import effective_emulation, hardware_identity
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona

_battery_epochs: WeakKeyDictionary[BrowserContext, int] = WeakKeyDictionary()


@dataclass(frozen=True)
class QASensorSample:
    index: int
    timestamp_seconds: float
    linear_acceleration_m_s2: tuple[float, ...]
    angular_velocity_rad_s: tuple[float, ...]
    source: str = "synthetic-qa-perlin-v1"


@dataclass(frozen=True)
class QASensorSource:
    """Explicit test-input sequence; never installs browser hooks or CDP overrides.

    Samples describe independent bounded disturbances, not a reconstructed human pose.
    60 Hz refers to simulation timestamps; callers own real-time playback scheduling.
    """

    seed: int
    acceleration_amplitude: float = 0.03
    angular_velocity_amplitude: float = 0.03

    def __post_init__(self) -> None:
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ValueError("QA seed must be an unsigned 32-bit integer")
        for amplitude in (self.acceleration_amplitude, self.angular_velocity_amplitude):
            if not math.isfinite(amplitude) or not 0 <= amplitude <= 0.05:
                raise ValueError("QA tremor amplitude must be finite and between 0 and 0.05")

    def sample_at(self, index: int) -> QASensorSample:
        if type(index) is not int or not 0 <= index < 86400 * 60:
            raise ValueError("QA sample index must be within one day at 60 Hz")
        timestamp = index / 60
        values = tuple(
            perlin_value_and_rate(timestamp * 1.7 + 0.37, self.seed + axis * 7919)[0]
            for axis in range(6)
        )
        return QASensorSample(
            index,
            timestamp,
            tuple(self.acceleration_amplitude * v for v in values[:3]),
            tuple(self.angular_velocity_amplitude * v for v in values[3:]),
        )

    def samples(self, count: int) -> Iterator[QASensorSample]:
        if type(count) is not int or not 0 <= count <= 86400 * 60:
            raise ValueError("QA sample count must be within one day at 60 Hz")
        for index in range(count):
            yield self.sample_at(index)


@cache
def _source() -> str:
    return Path(__file__).with_suffix(".js").read_text(encoding="utf-8")


def emulation_headers(persona: BrowserPersona) -> dict[str, str]:
    privacy = persona.emulation.privacy if persona.emulation else None
    if privacy is None:
        return {}
    return {
        **({"DNT": "1"} if privacy.do_not_track else {}),
        **({"Sec-GPC": "1"} if privacy.global_privacy_control else {}),
    }


def emulation_script(
    persona: BrowserPersona,
    *,
    battery_epoch_ms: int | None = None,
    worker: bool = False,
    worker_user_agent: str | None = None,
) -> str:
    value = effective_emulation(persona)
    if value is None:
        raise ValueError("Document emulation requires an explicit profile identity")
    config = value.model_dump(mode="json")
    if persona.browser_engine == "chromium" and persona.runtime.target_os:
        config["navigator_platform"] = {
            "windows": "Win32",
            "macos": "MacIntel",
            "linux": "Linux x86_64",
            "android": "Linux armv8l",
        }.get(persona.runtime.target_os)
    if persona.runtime.target_os == "android" or (
        persona.phone is not None and persona.phone.family == "android"
    ):
        config["max_touch_points"] = 5
    if worker:
        # Workers have no document, permissions policy, battery manager or DOM sensors.
        # Share the exact session recipe and WebGL implementation with the document.
        fields = ("seed", "device_memory", "webgl", "navigator_platform")
        config = {key: config[key] for key in fields if key in config}
        config["hardware_concurrency"] = (
            value.hardware_concurrency or persona.hardware_concurrency_override
        )
        if worker_user_agent is not None:
            config["worker_user_agent"] = worker_user_agent
        return native_script(_source()).replace(
            "__DEVICE_EMULATION_CONFIG__", json.dumps(config, ensure_ascii=True)
        )
    if battery_epoch_ms is not None:
        config["battery_epoch_ms"] = battery_epoch_ms
    if value.sensors is not None:
        config["sensor_readings"] = sensor_readings(value.sensors)
    # Grants are evaluated against each document's real origin, including iframes.
    config["grants"] = [permission.model_dump() for permission in persona.permissions]
    if persona.coherence is not None:
        config["voice_language"] = persona.locale.split("-", 1)[0].lower()
        config["voice_platform_matches"] = persona.runtime.target_os == {
            "Windows": "windows",
            "Darwin": "macos",
            "Linux": "linux",
        }.get(platform.system())
    return native_script(_source()).replace(
        "__DEVICE_EMULATION_CONFIG__", json.dumps(config, ensure_ascii=True)
    )


async def configure_device_emulation(
    context: BrowserContext, persona: BrowserPersona, profile_path: Path
) -> None:
    value = effective_emulation(persona)
    if value is None:
        return
    identity_path = profile_path.parent / "emulation-identity.json"
    signature = {
        "engine": persona.browser_engine,
        "emulation": persona.emulation.model_dump(mode="json") if persona.emulation else None,
        "fingerprint_id": persona.fingerprint_id,
    }
    if persona.coherence is not None:
        signature["coherence"] = persona.coherence.model_dump()
    stored = await asyncio.to_thread(read_json, identity_path)
    if stored and stored != signature:
        raise ProfileValidationError("Document device identity changed; create a new profile")
    hardware_path = profile_path.parent / "session-hardware-identity.json"
    hardware = hardware_identity(persona) if persona.browser_engine == "chromium" else None
    if hardware is not None:
        saved = await asyncio.to_thread(read_json, hardware_path)
        if saved and saved != {key: hardware.get(key) for key in saved}:
            raise ProfileValidationError("Session hardware identity changed; create a new profile")
    epoch = (
        _battery_epochs.setdefault(context, int(time() * 1000))
        if value.battery is not None
        else None
    )
    script = emulation_script(persona, battery_epoch_ms=epoch)
    await context.add_init_script(script)
    native = persona.runtime.backend == "camoufox"
    if native:
        await context.add_init_script("mw:" + script)
    for page in context.pages:
        for frame in page.frames:
            await frame.evaluate(script)
            if native:
                await frame.evaluate("mw:" + script)
    if persona.emulation is not None:
        await asyncio.to_thread(write_json, identity_path, signature)
    if hardware is not None:
        if not saved:
            await asyncio.to_thread(write_json, hardware_path, hardware)


async def grant_native_permissions(context: BrowserContext, persona: BrowserPersona) -> None:
    for permission in persona.permissions:
        values = permission.permissions
        if persona.emulation is not None and persona.emulation.sensors is not None:
            values = [name for name in values if name not in {"accelerometer", "gyroscope"}]
        if values:
            await context.grant_permissions(values, origin=permission.origin)


async def validate_device_emulation(
    target: Page | Frame, persona: BrowserPersona, *, main_world: bool = False
) -> dict[str, Any]:
    value = effective_emulation(persona)
    if value is None:
        return {}
    prefix = "mw:" if main_world else ""
    actual = await target.evaluate(
        prefix
        + """async () => {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl');
        const debug = gl?.getExtension('WEBGL_debug_renderer_info');
        const audio = typeof AudioContext === 'function' ? new AudioContext() : null;
        const battery = __READ_BATTERY__ && typeof navigator.getBattery === 'function'
            ? await navigator.getBattery().catch(() => null) : null;
        try { return {
            secure_context: isSecureContext,
            device_memory: navigator.deviceMemory ?? null,
            battery: battery ? {charging:battery.charging, level:battery.level,
                charging_time:Number.isFinite(battery.chargingTime) ? battery.chargingTime : null,
                discharging_time:Number.isFinite(battery.dischargingTime)
                    ? battery.dischargingTime : null} : null,
            hardware_concurrency: navigator.hardwareConcurrency,
            privacy: {do_not_track: navigator.doNotTrack,
                      global_privacy_control: navigator.globalPrivacyControl},
            webgl: debug ? {vendor: gl.getParameter(debug.UNMASKED_VENDOR_WEBGL),
                           renderer: gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)} : null,
            fonts_restricted: document.fonts.check('12px "Synthetic Unlisted Font"') === false,
            audio: audio ? {sample_rate: audio.sampleRate, output_latency: audio.outputLatency,
                           max_channels: audio.destination.maxChannelCount} : null,
            media: navigator.mediaDevices ? (await navigator.mediaDevices.enumerateDevices())
                .map(d => ({kind:d.kind, label:d.label,
                           device_id:d.deviceId, group_id:d.groupId})) : null,
            voices: typeof speechSynthesis !== 'undefined'
                ? speechSynthesis.getVoices().length : null,
            sensors: ['Accelerometer','GravitySensor','LinearAccelerationSensor',
                      'Gyroscope','RelativeOrientationSensor']
                      .every(n => typeof globalThis[n] === 'function')
        }; } finally { if (audio) await audio.close(); }
    }""".replace("__READ_BATTERY__", json.dumps(value.battery is not None))
    )
    expected: dict[str, Any] = {}
    if value.hardware_concurrency is not None:
        expected["hardware_concurrency"] = value.hardware_concurrency
    if value.device_memory is not None and actual["secure_context"]:
        expected["device_memory"] = value.device_memory
    if value.battery is not None and actual["secure_context"]:
        battery = actual.get("battery")
        if (
            not battery
            or battery["charging"] != value.battery.charging
            or not 0 <= battery["level"] <= 1
        ):
            raise ProfileValidationError("emulation.battery: invalid document battery state")
        context = target.page.context if isinstance(target, Frame) else target.context
        epoch = _battery_epochs.get(context)
        if epoch is not None:
            elapsed = max(0, int((time() * 1000 - epoch) // 60000)) * 60
            rate = (
                value.battery.charge_seconds
                if battery["charging"]
                else value.battery.discharge_seconds
            )
            expected_level = min(
                1,
                max(
                    0,
                    value.battery.level
                    + (elapsed / rate if battery["charging"] else -elapsed / rate),
                ),
            )
            # A timer may still expose the preceding minute at the bucket boundary.
            if abs(battery["level"] - expected_level) > 60 / rate + 1e-9:
                raise ProfileValidationError("emulation.battery: level differs from session state")
        idle, active = (
            ("discharging_time", "charging_time")
            if battery["charging"]
            else ("charging_time", "discharging_time")
        )
        duration = (
            value.battery.charge_seconds
            if battery["charging"]
            else (value.battery.discharge_seconds)
        )
        remaining = (1 - battery["level"]) if battery["charging"] else battery["level"]
        if (
            battery[idle] is not None
            or battery[active] is None
            or abs(battery[active] - remaining * duration) > 1
        ):
            raise ProfileValidationError("emulation.battery: charge and remaining time disagree")
    if value.webgl is not None:
        expected["webgl"] = value.webgl.model_dump()
    if value.fonts is not None:
        expected["fonts_restricted"] = True
    if value.audio is not None:
        expected["audio"] = {
            "sample_rate": value.audio.sample_rate,
            "output_latency": value.audio.output_latency,
            "max_channels": value.audio.max_channels,
        }
    if value.privacy is not None:
        expected["privacy"] = {
            "do_not_track": "1" if value.privacy.do_not_track else None,
            "global_privacy_control": value.privacy.global_privacy_control,
        }
    if value.voices == "none":
        expected["voices"] = 0
    if value.sensors is not None and urlsplit(target.url).scheme in {"http", "https"}:
        expected["sensors"] = True
    for field, wanted in expected.items():
        if actual.get(field) != wanted:
            raise ProfileValidationError(
                f"emulation.{field}: document observation differs from profile"
            )
    return actual
