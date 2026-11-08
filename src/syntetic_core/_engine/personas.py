"""Persona metadata layered on the existing DB-backed browser profiles."""

import hashlib
import json
import math
import re
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from syntetic_core._engine.browser_experiments import BrowserExperiment, NativeMediaPreset
from syntetic_core._engine.errors import ProfileValidationError

DeviceFamily = Literal["desktop", "android", "ios"]


class DeviceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["desktop", "mobile", "playwright", "custom"] = "desktop"
    preset: str | None = None
    viewport: dict[str, int] = Field(default_factory=lambda: {"width": 1280, "height": 720})
    screen: dict[str, int] = Field(default_factory=lambda: {"width": 1920, "height": 1080})
    device_scale_factor: float = 1
    mobile: bool = False
    touch: bool = False


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["playwright", "camoufox"] = "playwright"
    channel: Literal["chromium", "chrome", "msedge"] | None = None
    target_os: Literal["windows", "macos", "linux", "android", "ios"] | None = None
    webrtc: Literal["default", "proxy_only", "disabled"] = "proxy_only"
    fonts: list[str] | None = Field(default=None, max_length=100)
    webgl: tuple[str, str] | None = None
    pin_cpu_cores: bool = False
    headless: bool = True
    browser_version: str | None = Field(default=None, max_length=80)
    persistent_storage: Literal[True] = True


class NetworkPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proxy_pool: list[str] = Field(default_factory=list, max_length=1000)
    selection: Literal["sticky", "round_robin"] = "sticky"
    min_identity_seconds: float = Field(default=3600, ge=0, le=604800)
    expected_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    allowed_asns: list[int] = Field(default_factory=list)
    allowed_kinds: list[Literal["residential", "mobile", "datacenter", "unknown"]] = Field(
        default_factory=list
    )
    max_risk_score: float | None = Field(default=None, ge=0, le=100)
    require_probe: bool = False
    proxy_required: bool = False
    require_timezone_match: bool = False
    require_dns_match: bool = False
    expected_ja4: str | None = Field(default=None, min_length=1, max_length=200)
    expected_http2_fingerprint: str | None = Field(default=None, min_length=1, max_length=1000)

    @property
    def needs_probe(self) -> bool:
        return bool(
            self.require_probe
            or self.expected_country
            or self.allowed_asns
            or self.allowed_kinds
            or self.max_risk_score is not None
            or self.require_timezone_match
            or self.require_dns_match
            or self.expected_ja4
            or self.expected_http2_fingerprint
        )

    @field_validator("proxy_pool")
    @classmethod
    def unique_pool(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not item for item in value):
            raise ValueError("Proxy pool requires unique nonempty IDs")
        return value


class BehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    seed: int | None = None
    pause_min_ms: int = Field(default=100, ge=0, le=10000)
    pause_max_ms: int = Field(default=850, ge=0, le=10000)
    # Shape of the lognormal offset above pause_min_ms, before upper truncation.
    # Defaults must not change the serialized JSON/hash of legacy snapshots.
    pause_median_ratio: float = Field(
        default=0.15,
        ge=0.01,
        le=1,
        allow_inf_nan=False,
        exclude_if=lambda value: value == 0.15,
    )
    pause_sigma: float = Field(
        default=1.0,
        ge=0.1,
        le=3,
        allow_inf_nan=False,
        exclude_if=lambda value: value == 1.0,
    )
    key_min_ms: int = Field(default=30, ge=0, le=1000)
    key_max_ms: int = Field(default=190, ge=0, le=1000)
    scroll_steps: int = Field(default=8, ge=1, le=100)
    cursor_seconds: float = Field(default=1.5, gt=0, le=10)
    # Omit new defaults to preserve integrity hashes of existing persona snapshots.
    heartbeat_enabled: bool = Field(default=True, exclude_if=lambda value: value is True)
    heartbeat_min_seconds: float = Field(
        default=4.0, ge=0.05, le=8.0, exclude_if=lambda value: value == 4.0
    )
    heartbeat_max_seconds: float = Field(
        default=8.0, ge=0.05, le=8.0, exclude_if=lambda value: value == 8.0
    )
    heartbeat_checkpoints: bool = Field(default=True, exclude_if=lambda value: value is True)

    @model_validator(mode="after")
    def ordered_ranges(self) -> "BehaviorConfig":
        if (
            self.pause_min_ms > self.pause_max_ms
            or self.key_min_ms > self.key_max_ms
            or self.heartbeat_min_seconds > self.heartbeat_max_seconds
        ):
            raise ValueError("Behavior range minimum exceeds maximum")
        return self


class DisplayPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color_scheme: Literal["light", "dark"] = "light"
    reduced_motion: Literal["no-preference", "reduce"] = "no-preference"
    contrast: Literal["no-preference", "more"] = "no-preference"
    forced_colors: Literal["none", "active"] = "none"


class StationarySensors(BaseModel):
    """A reproducible stationary device pose; readings are derived together."""

    model_config = ConfigDict(extra="forbid")
    roll: float = Field(strict=True, ge=-180, le=180, allow_inf_nan=False)
    pitch: float = Field(strict=True, ge=-90, le=90, allow_inf_nan=False)
    yaw: float = Field(strict=True, ge=0, lt=360, allow_inf_nan=False)


class NativeAudioIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_rate: Literal[44100, 48000]
    # Latency is derived from an audio buffer at the selected sample rate.
    buffer_frames: Literal[256, 512, 1024]
    max_channels: Literal[2] = 2

    @property
    def output_latency(self) -> float:
        return self.buffer_frames / self.sample_rate


class SensorMotion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amplitude: float = Field(default=2, gt=0, le=5, allow_inf_nan=False)
    period_seconds: float = Field(default=8, ge=4, le=30, allow_inf_nan=False)
    frequency: Literal[5, 10, 30, 60] = 5
    # Omit defaults to preserve existing sealed profile signatures.
    tremor_amplitude: float = Field(
        default=0, ge=0, le=0.05, allow_inf_nan=False, exclude_if=lambda v: v == 0
    )
    tremor_seed: int = Field(
        default=1, strict=True, ge=1, le=2**32 - 1, exclude_if=lambda v: v == 1
    )


class FoldableDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    posture: Literal["continuous", "folded"] = "folded"
    orientation: Literal["vertical", "horizontal"] = "vertical"
    offset: int = Field(strict=True, gt=0, le=4000)
    mask_length: int = Field(default=0, strict=True, ge=0, le=40)


class ChromiumExperience(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text_scale: float = Field(default=1, ge=1, le=1.5, allow_inf_nan=False)
    save_data: bool = Field(default=False, strict=True)
    cpu_slowdown: float = Field(default=1, ge=1, le=4, allow_inf_nan=False)
    foldable: FoldableDisplay | None = Field(default=None, exclude_if=lambda v: v is None)


class NativeDesktopIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    avail_left: int = Field(default=0, strict=True, ge=0)
    avail_top: int = Field(default=0, strict=True, ge=0)
    avail_width: int = Field(strict=True, gt=0, le=10000)
    avail_height: int = Field(strict=True, gt=0, le=10000)
    outer_width: int = Field(strict=True, gt=0, le=10000)
    outer_height: int = Field(strict=True, gt=0, le=10000)
    config_height_offset: int = Field(default=0, strict=True, ge=0, le=200)
    do_not_track: bool = Field(strict=True)
    global_privacy_control: bool = Field(strict=True)


class EmulatedWebGL(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor: str = Field(min_length=1, max_length=200)
    renderer: str = Field(min_length=1, max_length=300)


class EmulatedMediaDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["audioinput", "videoinput", "audiooutput"]
    label: str = Field(min_length=1, max_length=120)
    device_id: str = Field(min_length=1, max_length=128)
    group_id: str = Field(min_length=1, max_length=128)


class EmulatedPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    do_not_track: bool = Field(strict=True)
    global_privacy_control: bool = Field(strict=True)


class EmulatedBattery(BaseModel):
    """Initial state and linear charge/discharge rates for a browser session."""

    model_config = ConfigDict(extra="forbid")
    charging: bool = Field(strict=True)
    level: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)
    charge_seconds: int = Field(default=7200, strict=True, ge=60, le=172800)
    discharge_seconds: int = Field(default=21600, strict=True, ge=60, le=604800)


class DeviceEmulation(BaseModel):
    """Profile-owned document API emulation, distinct from native engine capabilities."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    seed: int = Field(strict=True, ge=1, le=2**32 - 1)
    webgl: EmulatedWebGL | None = Field(default=None, exclude_if=lambda v: v is None)
    fonts: list[str] | None = Field(
        default=None, min_length=1, max_length=100, exclude_if=lambda v: v is None
    )
    audio: NativeAudioIdentity | None = Field(default=None, exclude_if=lambda v: v is None)
    media: list[EmulatedMediaDevice] | None = Field(
        default=None, max_length=20, exclude_if=lambda v: v is None
    )
    voices: Literal["subset", "local", "none"] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    hardware_concurrency: int | None = Field(
        default=None, strict=True, ge=1, le=128, exclude_if=lambda v: v is None
    )
    privacy: EmulatedPrivacy | None = Field(default=None, exclude_if=lambda v: v is None)
    sensors: StationarySensors | None = Field(default=None, exclude_if=lambda v: v is None)
    device_memory: float | None = Field(
        default=None, strict=True, gt=0, le=32, exclude_if=lambda v: v is None
    )
    battery: EmulatedBattery | None = Field(default=None, exclude_if=lambda v: v is None)

    @field_validator("device_memory")
    @classmethod
    def valid_device_memory(cls, value: float | None) -> float | None:
        if value is not None and value not in (0.25, 0.5, 1, 2, 4, 8, 16, 32):
            raise ValueError("Device memory must be a supported approximate GiB value")
        return value

    @field_validator("fonts")
    @classmethod
    def valid_fonts(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (
            len(set(value)) != len(value)
            or any(not font.strip() or len(font) > 100 or "\x00" in font for font in value)
        ):
            raise ValueError("Emulated fonts require unique, bounded family names")
        return value

    @model_validator(mode="after")
    def unique_media(self) -> "DeviceEmulation":
        if self.media is not None and len({d.device_id for d in self.media}) != len(self.media):
            raise ValueError("Emulated media device IDs must be unique")
        return self


class SitePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str
    local_storage: dict[str, str] = Field(default_factory=dict, max_length=50)
    cookies: dict[str, str] = Field(default_factory=dict, max_length=50)

    @field_validator("origin")
    @classmethod
    def valid_origin(cls, value: str) -> str:
        # The same origin contract as explicit permission grants.
        return PermissionConfig.valid_origin(value)

    @field_validator("local_storage", "cookies")
    @classmethod
    def bounded_values(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not key or len(key) > 128 or len(value) > 4096 for key, value in values.items()):
            raise ValueError("Site preference key or value exceeds its limit")
        return values


class VisitState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visitor: Literal["new", "returning"]
    cache: Literal["cold", "warm"]
    grant_geolocation: bool = Field(default=False, strict=True)
    preferences: list[SitePreferences] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def coherent_state(self) -> "VisitState":
        if self.visitor == "new" and self.cache == "warm":
            raise ValueError("A warm page visit requires the returning visitor state")
        return self


class ChromiumIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform_version: str = Field(default="", pattern=r"^(|\d{1,2}\.\d{1,2}\.\d{1,2})$")
    architecture: Literal["arm", "x86"] | None = Field(default=None, exclude_if=lambda v: v is None)
    hardware_concurrency: int | None = Field(
        default=None, strict=True, ge=1, le=128, exclude_if=lambda value: value is None
    )
    sensors: StationarySensors | None = Field(default=None, exclude_if=lambda value: value is None)
    motion: SensorMotion | None = Field(default=None, exclude_if=lambda v: v is None)
    experience: ChromiumExperience | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def motion_requires_pose(self) -> "ChromiumIdentity":
        if self.motion is not None and (
            self.sensors is None
            or abs(self.sensors.pitch) + self.motion.amplitude + self.motion.tremor_amplitude >= 90
        ):
            raise ValueError("Sensor motion requires a pose away from the pitch singularity")
        return self


class PhoneIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: Literal["android", "ios"]
    form_factor: Literal["phone", "tablet", "foldable"] = Field(
        default="phone", exclude_if=lambda v: v == "phone"
    )
    model: str = Field(min_length=1, max_length=80)
    os_version: str = Field(pattern=r"^\d{1,2}(?:\.\d{1,2}){0,2}$")
    orientation: Literal["portrait", "landscape"] = "portrait"
    preset_id: str | None = Field(
        default=None, min_length=1, max_length=120, exclude_if=lambda value: value is None
    )
    hardware_concurrency: int | None = Field(
        default=None, ge=1, le=32, exclude_if=lambda value: value is None
    )


class PermissionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str
    permissions: list[
        Literal[
            "geolocation", "notifications", "camera", "microphone", "accelerometer", "gyroscope"
        ]
    ]

    @field_validator("origin")
    @classmethod
    def valid_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Permissions require an HTTP(S) origin")
        return value.rstrip("/")


class GeolocationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float = Field(default=100, ge=0, le=100000)


class PersonaDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    required: bool = False
    fingerprintjs: bool = True
    browser_integrity: bool = True
    playwright_trace: bool = True
    mitmproxy: bool = False


class MandatoryInteractionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1, 2] = 2
    contextual_pacing: Literal[True] = True
    unified_interactions: Literal[True] = True
    route_variants: Literal[True] = True
    environment_consistency: Literal[True] = True
    readiness_before_pacing: Literal[True] = True
    interaction_measurement: Literal[True] = True


class BenchmarkHardwareLimits(BaseModel):
    """Measured QA reference, not instructions to modify browser properties."""

    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=200)
    max_texture_size: int | None = Field(default=None, gt=0)
    max_renderbuffer_size: int | None = Field(default=None, gt=0)
    storage_quota_min_bytes: int | None = Field(default=None, ge=0)
    storage_quota_max_bytes: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def ordered_quota(self) -> "BenchmarkHardwareLimits":
        if (
            self.storage_quota_min_bytes is not None
            and self.storage_quota_max_bytes is not None
            and self.storage_quota_min_bytes > self.storage_quota_max_bytes
        ):
            raise ValueError("Storage quota minimum exceeds maximum")
        return self


class DeviceCoherence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    recipe_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9-]+$")
    benchmark_limits: BenchmarkHardwareLimits | None = Field(
        default=None,
        exclude_if=lambda v: v is None,
    )


class BrowserPersona(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    profile_id: int | None = Field(default=None, gt=0)
    persona_schema_version: Literal[1] = 1
    persona_revision: int = Field(default=1, ge=1)
    config_hash: str = Field(default="", pattern=r"^(|[a-f0-9]{64})$")
    fingerprint_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    browser_engine: Literal["chromium", "firefox", "webkit"] = "chromium"
    locale: str = "en-US"
    timezone_id: str = "UTC"
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    proxy_id: str | None = None
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    display: DisplayPreferences | None = Field(default=None, exclude_if=lambda value: value is None)
    chromium: ChromiumIdentity | None = Field(default=None, exclude_if=lambda value: value is None)
    phone: PhoneIdentity | None = Field(default=None, exclude_if=lambda value: value is None)
    native_audio: NativeAudioIdentity | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    native_desktop: NativeDesktopIdentity | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    visit_state: VisitState | None = Field(default=None, exclude_if=lambda v: v is None)
    experiment: BrowserExperiment | None = Field(default=None, exclude_if=lambda v: v is None)
    native_media: NativeMediaPreset | None = Field(default=None, exclude_if=lambda v: v is None)
    emulation: DeviceEmulation | None = Field(default=None, exclude_if=lambda v: v is None)
    coherence: DeviceCoherence | None = Field(default=None, exclude_if=lambda v: v is None)
    interaction_policy: MandatoryInteractionPolicy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    permissions: list[PermissionConfig] = Field(default_factory=list)
    geolocation: GeolocationConfig | None = None
    # user_data_dir belongs to ProfileManager, never to user-supplied metadata.
    browserforge: dict[str, Any] = Field(default_factory=dict)
    diagnostics: PersonaDiagnostics = Field(default_factory=PersonaDiagnostics)

    @model_validator(mode="after")
    def owner_matches(self) -> "BrowserPersona":
        if self.profile_id is not None and self.id != str(self.profile_id):
            raise ValueError("Persona and profile owner differ")
        if self.interaction_policy is not None:
            if not self.behavior.enabled:
                raise ValueError("Mandatory interaction policy requires behavior.enabled=true")
            if self.behavior.pause_min_ms <= 0 or self.behavior.key_min_ms <= 0:
                raise ValueError("Mandatory interaction policy requires positive pause/key timing")
        if (
            self.phone is not None
            and self.chromium is not None
            and self.phone.hardware_concurrency is not None
            and self.chromium.hardware_concurrency is not None
            and self.phone.hardware_concurrency != self.chromium.hardware_concurrency
        ):
            raise ValueError("Phone and Chromium hardware concurrency differ")
        if self.emulation is not None and self.emulation.hardware_concurrency is not None:
            for value in (
                self.phone.hardware_concurrency if self.phone else None,
                self.chromium.hardware_concurrency if self.chromium else None,
            ):
                if value is not None and value != self.emulation.hardware_concurrency:
                    raise ValueError("Native and document CPU identities differ")
        if (
            self.emulation is not None
            and self.emulation.privacy is not None
            and self.native_desktop is not None
            and (
                self.emulation.privacy.do_not_track != self.native_desktop.do_not_track
                or self.emulation.privacy.global_privacy_control
                != self.native_desktop.global_privacy_control
            )
        ):
            raise ValueError("Native and document privacy identities differ")
        if (
            self.emulation is not None
            and self.emulation.audio is not None
            and self.native_audio is not None
            and self.emulation.audio != self.native_audio
        ):
            raise ValueError("Native and document audio identities differ")
        return self

    @property
    def hardware_concurrency_override(self) -> int | None:
        if self.phone is not None and self.phone.hardware_concurrency is not None:
            return self.phone.hardware_concurrency
        if self.chromium is not None and self.chromium.hardware_concurrency is not None:
            return self.chromium.hardware_concurrency
        return self.emulation.hardware_concurrency if self.emulation is not None else None

    def digest(self) -> str:
        excluded = {"config_hash"}
        if self.fingerprint_id is None:
            # Existing profile and queued-session hashes predate this optional field.
            excluded.add("fingerprint_id")
        data = self.model_dump(mode="json", exclude=excluded)
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()

    def sealed(self, revision: int | None = None) -> "BrowserPersona":
        result = self.model_copy(deep=True)
        result.profile_id = int(self.id)
        result.persona_revision = revision or self.persona_revision
        result.config_hash = result.digest()
        return result

    def verify_snapshot(self, profile_id: int) -> None:
        if self.profile_id != profile_id or self.id != str(profile_id):
            raise ProfileValidationError("profile_id: snapshot owner mismatch")
        if self.config_hash != self.digest():
            raise ProfileValidationError("config_hash: snapshot integrity mismatch")


class ValidationResult(BaseModel):
    valid: bool = True
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class DeviceProfileResolver:
    def resolve(self, device: DeviceConfig, devices: Any) -> dict[str, Any]:
        if device.source in {"playwright", "mobile"}:
            preset = device.preset or ("iPhone 15" if device.source == "mobile" else "")
            if preset not in devices:
                raise ProfileValidationError("Unknown Playwright device preset")
            resolved = dict(devices[preset])
            # Some official descriptors omit screen; Playwright defaults it to viewport.
            resolved.setdefault("screen", dict(resolved["viewport"]))
            return resolved
        return {
            "viewport": device.viewport,
            "screen": device.screen,
            "device_scale_factor": device.device_scale_factor,
            "is_mobile": device.mobile,
            "has_touch": device.touch,
        }


class PersonaValidator:
    def validate(
        self,
        persona: BrowserPersona,
        device: dict[str, Any],
        mode: Literal["off", "warning", "strict"] = "strict",
        proxy_metadata: dict[str, Any] | None = None,
    ) -> ValidationResult:
        if mode == "off":
            return ValidationResult()
        issues: list[str] = []
        warnings: list[str] = []
        from syntetic_core._engine.device_coherence import coherence_issues

        issues.extend(coherence_issues(persona))
        if persona.native_media is not None and persona.runtime.backend != "camoufox":
            issues.append("Native media presets require Camoufox")
        if persona.experiment is not None:
            for event in persona.experiment.events:
                if event.kind == "display" and persona.runtime.backend == "camoufox":
                    issues.append("Dynamic Camoufox geometry is not supported")
                if (
                    event.kind == "display"
                    and persona.browser_engine != "chromium"
                    and (
                        event.safe_area
                        or (event.keyboard and event.keyboard.mode == "native")
                        or event.posture
                        or event.page_scale != 1
                    )
                ):
                    issues.append("Extended display conditions require Chromium")
        if persona.proxy_id and persona.network.proxy_pool:
            issues.append("Choose a fixed proxy or a proxy pool, not both")
        if persona.runtime.backend == "camoufox":
            if persona.browser_engine != "firefox":
                issues.append("Camoufox requires the Firefox engine")
            if device.get("is_mobile") or device.get("has_touch"):
                issues.append("Camoufox supports desktop identities only")
            if persona.runtime.channel:
                issues.append("Camoufox cannot use a Chromium channel")
        elif persona.runtime.channel and persona.browser_engine != "chromium":
            issues.append("Browser channels require Chromium")
        if persona.runtime.backend == "playwright" and (
            persona.runtime.fonts or persona.runtime.webgl
        ):
            issues.append("Fonts and WebGL overrides require Camoufox")
        if persona.runtime.target_os and persona.runtime.backend == "playwright":
            if persona.browser_engine != "chromium" and not (
                persona.browser_engine == "webkit" and persona.runtime.target_os == "ios"
            ):
                issues.append("Playwright OS emulation requires Chromium")
        if persona.runtime.target_os in {"android", "ios"}:
            expected_engine = "chromium" if persona.runtime.target_os == "android" else "webkit"
            if (
                persona.runtime.backend != "playwright"
                or persona.browser_engine != expected_engine
                or not device.get("is_mobile")
                or not device.get("has_touch")
                or persona.phone is None
                or persona.phone.family != persona.runtime.target_os
            ):
                issues.append("Phone identity requires its mobile engine, touch and matching OS")
        elif persona.phone is not None:
            issues.append("Phone identity requires Android or iOS")
        if persona.phone is not None and persona.phone.family == "ios":
            if persona.phone.hardware_concurrency is not None:
                issues.append("WebKit does not support a native CPU count override")
        if persona.phone is not None and persona.phone.family == "android":
            if (
                persona.chromium is None
                or persona.chromium.platform_version != persona.phone.os_version
            ):
                issues.append("Android OS version must match Chromium Client Hints")
        if persona.chromium is not None and (
            persona.runtime.backend != "playwright"
            or persona.browser_engine != "chromium"
            or persona.runtime.target_os is None
        ):
            issues.append("Chromium identity requires Chromium with an assigned OS")
        if (
            persona.chromium is not None
            and persona.chromium.sensors is not None
            and (persona.phone is None or persona.phone.family != "android")
        ):
            issues.append("Virtual phone sensors require an Android Chromium identity")
        if persona.native_audio is not None and persona.runtime.backend != "camoufox":
            issues.append("Native audio identity requires Camoufox")
        if persona.native_desktop is not None:
            desktop = persona.native_desktop
            if persona.runtime.backend != "camoufox" or persona.phone is not None:
                issues.append("Native desktop geometry requires desktop Camoufox")
            if (
                desktop.avail_left + desktop.avail_width > persona.device.screen["width"]
                or desktop.avail_top + desktop.avail_height > persona.device.screen["height"]
                or not persona.device.viewport["width"]
                <= desktop.outer_width
                <= desktop.avail_width
                or not persona.device.viewport["height"] + 86
                <= desktop.outer_height
                <= desktop.avail_height
            ):
                issues.append("Native desktop window must fit its available screen and toolbar")
        if persona.chromium is not None and persona.chromium.experience is not None:
            fold = persona.chromium.experience.foldable
            if fold is not None:
                dimension = "width" if fold.orientation == "vertical" else "height"
                if (
                    persona.phone is None
                    or persona.phone.form_factor != "foldable"
                    or fold.offset + fold.mask_length >= persona.device.viewport[dimension]
                ):
                    issues.append("Display segments require a matching foldable device")
        if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", persona.locale):
            issues.append("Invalid locale")
        try:
            ZoneInfo(persona.timezone_id)
        except (ZoneInfoNotFoundError, ValueError):
            issues.append("Unknown timezone")
        for name in ("viewport", "screen"):
            size = device.get(name, {})
            if set(size) != {"width", "height"} or any(
                isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in size.values()
            ):
                issues.append(f"Invalid {name}")
        if not issues:
            if any(device["viewport"][k] > device["screen"][k] for k in ("width", "height")):
                issues.append("Viewport exceeds screen")
            if persona.phone is not None:
                landscape = device["screen"]["width"] > device["screen"]["height"]
                if landscape != (persona.phone.orientation == "landscape"):
                    issues.append("Phone orientation differs from the assigned screen")
        dpr = device.get("device_scale_factor", 1)
        if not math.isfinite(dpr) or not 0 < dpr <= 10:
            issues.append("Invalid device scale factor")
        if device.get("is_mobile") and not device.get("has_touch"):
            issues.append("Mobile device requires touch support")
        if persona.browser_engine == "firefox" and device.get("is_mobile"):
            issues.append("Playwright Firefox does not support is_mobile")
        expected = device.get("default_browser_type")
        if expected and expected != persona.browser_engine:
            issues.append("Device preset and browser engine differ")
        if proxy_metadata:
            country = proxy_metadata.get("country")
            if country and len(country) != 2:
                issues.append("Proxy country must be an ISO country code")
            if country and "-" in persona.locale and persona.locale.rsplit("-", 1)[-1] != country:
                warnings.append("Proxy country differs from locale region")
            if not country:
                warnings.append("Proxy geography is unknown")
            if (
                persona.network.expected_country
                and country
                and country != persona.network.expected_country
            ):
                issues.append("Proxy country differs from the required country")
        if mode == "warning":
            return ValidationResult(warnings=warnings + issues)
        return ValidationResult(valid=not issues, errors=issues, warnings=warnings)


class PersonaVariant:
    """A fresh profile with exactly one changed environment parameter."""

    @staticmethod
    def create(base: BrowserPersona, persona_id: str, parameter: str, value: Any) -> BrowserPersona:
        if persona_id == base.id:
            raise ProfileValidationError("Variant requires a distinct storage owner")
        data = base.model_dump()
        data["id"] = persona_id
        data["profile_id"] = int(persona_id)
        data["persona_revision"] = 1
        data["config_hash"] = ""
        if parameter in {"locale", "timezone_id"}:
            data[parameter] = value
        elif parameter in {"viewport", "mobile"}:
            if base.device.source not in {"custom", "desktop"}:
                raise ProfileValidationError(
                    "Resolve preset into a custom profile before varying it"
                )
            data["device"][parameter] = value
        elif parameter != "fresh_storage":
            raise ProfileValidationError("Unsupported variation parameter")
        return BrowserPersona.model_validate(data)
