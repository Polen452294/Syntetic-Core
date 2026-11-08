"""Runtime-only settings extracted from Synthetic Sessions."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from syntetic_core._engine.personas import DeviceFamily
from syntetic_core._engine.proxies import ProxyConfig


class DiagnosticsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    required: bool = False
    fingerprintjs: bool = True
    browser_integrity: bool = True
    playwright_trace: bool = True
    mitmproxy: bool = False
    timeout: float = Field(default=45, gt=0, le=300)
    mitm_executable: str = "mitmdump"


class ProfileRandomizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    ios_emulation: Literal["current", "legacy"] = "current"
    runtimes: list[Literal["camoufox", "playwright"]] = Field(
        default=["camoufox", "playwright"], min_length=1, max_length=2
    )
    device_weights: dict[DeviceFamily, Annotated[int, Field(ge=0, le=100)]] = Field(
        default={"desktop": 30, "android": 42, "ios": 28}
    )

    @field_validator("device_weights")
    @classmethod
    def valid_device_weights(cls, value: dict[DeviceFamily, int]) -> dict[DeviceFamily, int]:
        if sum(value.values()) != 100:
            raise ValueError("Device weights must sum to 100")
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYNTETIC_CORE_",
        env_nested_delimiter="__",
        extra="forbid",
        hide_input_in_errors=True,
    )
    profile_archive_enabled: bool = False
    profile_ram_enabled: bool = False
    profile_ram_root: Path = Path("/dev/shm/sessions")
    profile_ram_max_mb: int = Field(default=512, ge=1, le=16384)
    allowed_target_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1", "demo", "stress-fixture"]
    )
    allow_public_resources: bool = False
    trusted_local_target_hosts: list[str] = Field(default_factory=list)
    browser_engine: Literal["chromium", "firefox", "webkit"] = "firefox"
    camoufox_version: str = "official/156.0.1-beta.35"
    camoufox_install_path: Path = Path("build/native-browser")
    browser_headless: bool = True
    fixed_session_configuration: bool = False
    fresh_session_profiles: bool = True
    prepared_session_profile: bool = False
    incubation_config: dict | None = None
    traffic_optimizer_enabled: bool | None = None
    traffic_optimization_level: Literal["disabled", "metadata_only", "strict"] | None = None
    block_stylesheets: bool = False
    profile_randomization: ProfileRandomizationConfig = Field(
        default_factory=ProfileRandomizationConfig
    )
    persona_validation: Literal["off", "warning", "strict"] = "strict"
    direct_transport: bool = False
    proxy_required: bool = False
    proxies: list[ProxyConfig] = Field(default_factory=list)
    asocks_pool_timeout: float = Field(default=120, gt=0, le=600, allow_inf_nan=False)
    asocks_pool_max_bytes: int = Field(default=67108864, ge=1, le=134217728)
    asocks_pool_max_entries: int = Field(default=100000, ge=1, le=100000)
    network_probe_url: str | None = None
    network_probe_timeout: float = Field(default=15, gt=0, le=60)
    diagnostics: DiagnosticsConfig = Field(default_factory=DiagnosticsConfig)
    distributed_workers: bool = False
    profile_storage_shared: bool = False
    profile_lock_distributed: bool = False
    production_mode: bool = False
    experimental_arm64: bool = False
    expected_profile_storage: dict | None = Field(default=None, repr=False)
    initialize_profile_storage: bool = False
    controller_url: str | None = None
    cookie_farming_ultra_load: bool = True
    cookie_farming_daily_new_profiles: int | None = Field(default=None, ge=1, le=100000)
    cookie_farming_balance_guard: bool = True
    cookie_farming_recheck_proxy_ips: bool = True
    browser_start_timeout: float = Field(default=30, gt=0, le=300)
    retry_initial_delay: float = Field(default=5, ge=0)
    retry_backoff_multiplier: float = Field(default=2, ge=1, le=100)
    retry_max_delay: float = Field(default=60, ge=0)
    navigation_timeout: float = Field(default=15, gt=0, le=300)
    action_timeout: float = Field(default=10, gt=0, le=300)

    @property
    def use_fresh_session_profiles(self) -> bool:
        return self.fresh_session_profiles or self.profile_randomization.enabled

    @model_validator(mode="after")
    def standalone_only(self) -> "Settings":
        if self.distributed_workers or self.profile_storage_shared or self.profile_lock_distributed:
            raise ValueError("Standalone core supports local profile volumes and OS locks")
        if self.controller_url or self.profile_archive_enabled:
            raise ValueError("Controller/archive orchestration belongs to the source platform")
        if self.direct_transport:
            raise ValueError(
                "Use proxies=[] for direct transport; implicit proxy bypass is disabled"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
