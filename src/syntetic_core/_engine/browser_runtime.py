"""Shared, fail-closed launch capability contract. No browser dependency in the controller."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona, DeviceProfileResolver, PersonaValidator
from syntetic_core._engine.webkit_policy import WEBKIT_NATIVE_CAPABILITY, webkit_host_allowed


class RuntimeCompatibilityError(ProfileValidationError):
    status_code = 422

    def __init__(self, parameter: str) -> None:
        self.parameter = parameter
        super().__init__(f"{parameter}: unsupported by the selected worker runtime")


class RuntimeWindowInsets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(strict=True, ge=0, le=100)
    height: int = Field(strict=True, ge=0, le=400)
    config_height_offset: int = Field(default=0, strict=True, ge=0, le=200)


class RuntimeCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["playwright", "camoufox"]
    engine: Literal["chromium", "firefox", "webkit"]
    window_insets: RuntimeWindowInsets | None = None
    browser_version: str = Field(max_length=80)
    installed: bool
    smoke_test: Literal["passed", "failed", "unavailable"]
    headless: bool = True
    headful: bool = False
    persistent_storage: Literal[True] = True
    device_sources: list[Literal["desktop", "custom"]] = Field(default_factory=list)
    device_presets: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    diagnostic_adapters: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    coherence_version: int | None = Field(default=None, ge=1)
    coherence_recipes: list[str] = Field(default_factory=list, max_length=256)


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    interaction_policy_version: Literal[1, 2] | None = None
    visit_settings_version: Literal[1, 2] | None = None
    analytics_balancer_version: Literal[1] | None = None
    automatic_runs_version: Literal[1] | None = None
    cookie_farming_version: Literal[1, 2] | None = None
    profile_archive_version: Literal[0, 1] = 0
    profile_storage_shared: bool = False
    operating_system: Literal["windows", "linux", "macos"]
    architecture: str = Field(max_length=40)
    dependencies: dict[str, str] = Field(default_factory=dict, max_length=10)
    runtimes: list[RuntimeCapability] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=20)


def require_compatible(persona: BrowserPersona, manifest: dict) -> RuntimeCapability:
    try:
        capabilities = CapabilityManifest.model_validate(manifest)
    except ValueError:
        raise RuntimeCompatibilityError("capability_manifest.schema_version") from None
    if persona.browser_engine == "webkit" and not webkit_host_allowed(
        capabilities.operating_system
    ):
        raise RuntimeCompatibilityError("runtime.webkit_host")
    if persona.interaction_policy is not None and (
        capabilities.interaction_policy_version is None
        or capabilities.interaction_policy_version < persona.interaction_policy.version
    ):
        raise RuntimeCompatibilityError("interaction_policy.version")
    candidates = [
        runtime
        for runtime in capabilities.runtimes
        if runtime.engine == persona.browser_engine
        and runtime.backend == persona.runtime.backend
        and runtime.installed
        and runtime.smoke_test == "passed"
    ]
    if not candidates:
        raise RuntimeCompatibilityError("runtime")
    runtime = candidates[0]
    if persona.browser_engine == "webkit" and WEBKIT_NATIVE_CAPABILITY not in runtime.parameters:
        raise RuntimeCompatibilityError("runtime.webkit_full_native")
    if persona.coherence is not None and "device_coherence" not in runtime.parameters:
        raise RuntimeCompatibilityError("coherence")
    if persona.coherence is not None and (
        runtime.coherence_version != persona.coherence.version
        or persona.coherence.recipe_id not in runtime.coherence_recipes
    ):
        raise RuntimeCompatibilityError("coherence.recipe_id")
    if persona.browser_engine == "webkit" and (
        persona.phone is None or persona.phone.family != "ios"
    ):
        raise RuntimeCompatibilityError("device.phone")
    for parameter in (
        "locale",
        "timezone_id",
        "viewport",
        "screen",
        "device_scale_factor",
        "network",
        "native_transport",
        "persistent_storage",
        "session_api_policy_v1",
    ):
        if parameter not in runtime.parameters:
            raise RuntimeCompatibilityError(parameter)
    if persona.geolocation and "geolocation" not in runtime.parameters:
        raise RuntimeCompatibilityError("geolocation")
    if persona.emulation is not None:
        from syntetic_core._engine.device_emulation import EMULATION_FIELDS

        for field in EMULATION_FIELDS:
            if (
                getattr(persona.emulation, field) is not None
                and "emulation_" + field not in runtime.parameters
            ):
                raise RuntimeCompatibilityError("emulation." + field)
    if not persona.runtime.headless and not runtime.headful:
        raise RuntimeCompatibilityError("runtime.headless")
    if persona.runtime.headless and not runtime.headless:
        raise RuntimeCompatibilityError("runtime.headless")
    if persona.runtime.channel:
        raise RuntimeCompatibilityError("runtime.channel")
    if (
        persona.runtime.browser_version
        and persona.runtime.browser_version != runtime.browser_version
    ):
        raise RuntimeCompatibilityError("runtime.browser_version")
    if persona.runtime.target_os and persona.runtime.target_os != capabilities.operating_system:
        if "target_os" not in runtime.parameters:
            raise RuntimeCompatibilityError("runtime.target_os")
    if (
        persona.runtime.backend == "playwright"
        and persona.runtime.target_os
        and "target_os" not in runtime.parameters
    ):
        raise RuntimeCompatibilityError("runtime.target_os")
    for field in ("fonts", "webgl", "pin_cpu_cores"):
        if getattr(persona.runtime, field):
            raise RuntimeCompatibilityError(f"runtime.{field}")
    if persona.chromium is not None and "target_os" not in runtime.parameters:
        raise RuntimeCompatibilityError("chromium")
    if (
        persona.chromium is not None
        and persona.chromium.architecture is not None
        and "device_coherence" not in runtime.parameters
    ):
        raise RuntimeCompatibilityError("chromium.architecture")
    if (
        persona.chromium is not None
        and persona.chromium.hardware_concurrency is not None
        and "hardware_concurrency" not in runtime.parameters
    ):
        raise RuntimeCompatibilityError("chromium.hardware_concurrency")
    if persona.display is not None and "display_preferences" not in runtime.parameters:
        raise RuntimeCompatibilityError("display")
    if persona.native_audio is not None and "native_audio" not in runtime.parameters:
        raise RuntimeCompatibilityError("native_audio")
    if (
        persona.chromium is not None
        and persona.chromium.sensors is not None
        and "virtual_sensors" not in runtime.parameters
    ):
        raise RuntimeCompatibilityError("chromium.sensors")
    if persona.device.source not in runtime.device_sources or persona.device.preset:
        raise RuntimeCompatibilityError("device.source")
    if persona.device.mobile or persona.device.touch:
        if persona.phone is None or f"phone_{persona.phone.family}" not in runtime.parameters:
            raise RuntimeCompatibilityError("device.mobile/touch")
    if persona.runtime.webrtc == "disabled" and persona.browser_engine != "firefox":
        raise RuntimeCompatibilityError("runtime.webrtc")
    if persona.native_desktop is not None and "native_desktop" not in runtime.parameters:
        raise RuntimeCompatibilityError("native_desktop")
    if persona.visit_state is not None and "visit_state" not in runtime.parameters:
        raise RuntimeCompatibilityError("visit_state")
    if persona.native_media is not None and "native_media" not in runtime.parameters:
        raise RuntimeCompatibilityError("native_media")
    if persona.experiment is not None:
        if "visit_timeline" not in runtime.parameters:
            raise RuntimeCompatibilityError("experiment")
        for event in persona.experiment.events:
            if event.kind == "display":
                if "dynamic_viewport" not in runtime.parameters:
                    raise RuntimeCompatibilityError("experiment.display")
                for requested, parameter in (
                    (event.safe_area, "safe_area"),
                    (event.page_scale != 1, "page_scale"),
                    (event.keyboard and event.keyboard.mode == "native", "native_keyboard"),
                    (event.posture, "foldable"),
                ):
                    if requested and parameter not in runtime.parameters:
                        raise RuntimeCompatibilityError("experiment.display." + parameter)
            if event.kind == "location" and "geolocation" not in runtime.parameters:
                raise RuntimeCompatibilityError("experiment.location")
    if persona.phone is not None and persona.phone.form_factor == "tablet":
        if "tablet_ios" not in runtime.parameters:
            raise RuntimeCompatibilityError("phone.form_factor")
    if persona.chromium is not None:
        if persona.chromium.motion is not None and "sensor_motion" not in runtime.parameters:
            raise RuntimeCompatibilityError("chromium.motion")
        if persona.chromium.experience is not None:
            if "chromium_experience" not in runtime.parameters:
                raise RuntimeCompatibilityError("chromium.experience")
            if (
                persona.chromium.experience.foldable is not None
                and "foldable" not in runtime.parameters
            ):
                raise RuntimeCompatibilityError("chromium.experience.foldable")
    for permission in persona.permissions:
        emulated_sensors = (
            persona.emulation is not None
            and persona.emulation.sensors is not None
            and "emulation_sensors" in runtime.parameters
        )
        if any(
            value not in runtime.permissions
            and not (emulated_sensors and value in {"accelerometer", "gyroscope"})
            for value in permission.permissions
        ):
            raise RuntimeCompatibilityError("permissions")
    if persona.diagnostics.mitmproxy:
        raise RuntimeCompatibilityError("diagnostics.mitmproxy")
    if persona.diagnostics.enabled and persona.diagnostics.required:
        for adapter in ("fingerprintjs", "browser_integrity", "playwright_trace"):
            if getattr(persona.diagnostics, adapter) and adapter not in runtime.diagnostic_adapters:
                raise RuntimeCompatibilityError(f"diagnostics.{adapter}")
    device = DeviceProfileResolver().resolve(persona.device, {})
    result = PersonaValidator().validate(persona, device, "strict")
    if not result.valid:
        raise ProfileValidationError("; ".join(result.errors))
    return runtime
