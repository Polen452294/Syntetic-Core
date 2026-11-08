from datetime import date
from math import fsum
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from syntetic_core._engine.schemas.analytics import AnalyticsRoute


class VisitAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["click", "scroll", "follow_link", "goto"] = "click"
    label: str = Field(default="", max_length=100)
    at_min_seconds: int = Field(default=10, ge=0, le=899)
    at_max_seconds: int = Field(default=15, ge=0, le=899)
    selector_type: Literal["css", "id"] = "css"
    selector: str = Field(default="", max_length=900)
    selection: Literal["first", "random"] = "first"
    scroll_percent: int = Field(default=100, ge=0, le=100)
    scroll_duration_seconds: int = Field(default=20, ge=1, le=899)
    url: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def valid_action(self) -> "VisitAction":
        if self.at_min_seconds > self.at_max_seconds:
            raise ValueError("Action time minimum exceeds maximum")
        if self.action in {"click", "follow_link"}:
            self.selector = self.selector.strip()
            if not self.selector and (self.action == "click" or self.selector_type == "id"):
                raise ValueError("A target selector or HTML ID is required")
            if self.selector_type == "id":
                self.selector = self.selector.removeprefix("#")
                if not self.selector or any(character.isspace() for character in self.selector):
                    raise ValueError("HTML ID must not contain whitespace")
            elif ">>" in self.selector or "\x00" in self.selector:
                raise ValueError("Use a CSS selector without Playwright selector chaining")
        if self.action == "goto":
            self.url = self.url.strip()
            try:
                parsed = urlsplit(self.url)
                valid = (
                    bool(self.url)
                    and parsed.scheme in {"", "http", "https"}
                    and not (parsed.username or parsed.password)
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("Page URL must be a relative path or an HTTP(S) URL")
        return self


def validate_action_timeline(actions: list[VisitAction], duration: float, activity: str) -> None:
    if not actions:
        raise ValueError("Add at least one timed action")
    previous_end = 0
    for index, action in enumerate(actions, 1):
        if action.at_min_seconds < previous_end:
            raise ValueError(f"Action {index} overlaps the previous action window")
        previous_end = action.at_max_seconds + (
            action.scroll_duration_seconds if action.action == "scroll" else 0
        )
        if previous_end >= duration:
            raise ValueError(f"Action {index} must finish before the minimum visit duration")
        if activity == "no_clicks" and action.action in {"click", "follow_link"}:
            raise ValueError("Timed clicks require scenario activity")


TrafficSource = Literal["organic", "ad_direct", "social", "messenger", "direct"]
SourceShare = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


def default_source_distribution() -> dict[TrafficSource, float]:
    return {"organic": 1.0, "ad_direct": 0.0, "social": 0.0, "messenger": 0.0}


class UtmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""


class VisitSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def farming_defaults(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        from syntetic_core._engine.config import get_settings

        settings = get_settings()
        return {
            "cookie_farming_ultra_load": settings.cookie_farming_ultra_load,
            "cookie_farming_daily_new_profiles": settings.cookie_farming_daily_new_profiles,
            "cookie_farming_balance_guard": settings.cookie_farming_balance_guard,
            "cookie_farming_recheck_proxy_ips": settings.cookie_farming_recheck_proxy_ips,
            **value,
        }

    traffic_optimization_level: Literal["disabled", "metadata_only", "strict"] | None = None

    enabled: bool = False
    attribution_mode: bool = False
    source_distribution: dict[TrafficSource, SourceShare] = Field(
        default_factory=default_source_distribution,
        min_length=4,
        max_length=5,
        description="All four channel shares; their sum rounded to 6 decimals must equal 1.0",
    )
    returning_users_ratio: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    messenger_mode: Literal["web", "mobile", "desktop"] = "desktop"
    utm_config: UtmConfig | None = None
    timezone: str = "Europe/Moscow"
    duration_min_seconds: int = Field(default=30, ge=15, le=900)
    duration_max_seconds: int = Field(default=45, ge=15, le=900)
    daily_limit: int = Field(default=40, ge=1, le=100000)
    cookie_farming_enabled: bool = False
    cookie_farming_daily_new_profiles: int | None = Field(default=None, ge=1, le=100000)
    cookie_farming_ultra_load: bool = False
    cookie_farming_balance_guard: bool = False
    cookie_farming_cluster_weights: dict[str, float] = Field(default_factory=dict, max_length=3)
    cookie_farming_donor_weights: dict[str, float] = Field(default_factory=dict, max_length=50)
    cookie_farming_recheck_proxy_ips: bool = False
    cookie_farming_sites: list[str] = Field(default_factory=list, max_length=50)
    cookie_farming_clusters: dict[Literal["information", "news", "technology"], list[str]] = Field(
        default_factory=dict, max_length=3
    )
    daily_change_min: int = Field(default=0, ge=-500, le=500)
    daily_change_max: int = Field(default=0, ge=-500, le=500)
    auto_intervals: bool = True
    interval_seconds: int = Field(default=2160, ge=1, le=86400)
    interval_jitter_percent: int = Field(default=15, ge=1, le=50)
    reduce_at_night: bool = True
    reduce_on_weekends: bool = False
    weekly_schedule: list[list[bool]] = Field(
        default_factory=lambda: [[True] * 24 for _ in range(7)]
    )
    uniqueness_hours: int = Field(default=24, ge=1, le=168)
    retention_days: int | None = Field(default=None, ge=1, le=365)
    desktop_percent: int = Field(default=50, ge=0, le=100)
    activity: Literal["no_clicks", "scenario"] = "no_clicks"
    scroll_enabled: bool = True
    timeline_enabled: bool = False
    actions: list[VisitAction] = Field(default_factory=list, max_length=50)

    search_queries: list[str] = Field(default_factory=list, max_length=1000)
    scenario_id: int | None = Field(default=None, gt=0)
    scenario_yaml: str | None = Field(default=None, max_length=65536)

    @field_validator("source_distribution")
    @classmethod
    def source_shares_sum_to_one(
        cls, value: dict[TrafficSource, float]
    ) -> dict[TrafficSource, float]:
        if round(fsum(value.values()), 6) != 1.0:
            raise ValueError("Source distribution must sum to 1.0 rounded to 6 decimal places")
        return value

    @field_validator("search_queries", mode="before")
    @classmethod
    def normalize_search_queries(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.lstrip("\ufeff").splitlines()
        if isinstance(value, list):
            if any(not isinstance(query, str) for query in value):
                raise ValueError("Search queries must contain text")
            result = list(dict.fromkeys(query.strip() for query in value if query.strip()))
            if any(len(query) > 500 or "\n" in query or "\r" in query for query in result):
                raise ValueError("Each search query must be one line of at most 500 characters")
            return result
        return value

    @field_validator("cookie_farming_sites")
    @classmethod
    def farming_sites(cls, value: list[str]) -> list[str]:
        sites = list(dict.fromkeys(site.strip() for site in value if site.strip()))
        for site in sites:
            try:
                parsed = urlsplit(site)
                valid = (
                    parsed.scheme == "https"
                    and parsed.hostname
                    and not parsed.username
                    and not parsed.password
                    and parsed.port in {None, 443}
                    and len(site) <= 2048
                    and not parsed.fragment
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("Cookie-Farming sites must be HTTPS URLs without credentials")
        return sites

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        return value

    @field_validator("weekly_schedule")
    @classmethod
    def schedule_shape(cls, value: list[list[bool]]) -> list[list[bool]]:
        if len(value) != 7 or any(len(day) != 24 for day in value):
            raise ValueError("Schedule must contain 7 days of 24 hours")
        return value

    @model_validator(mode="after")
    def ordered_ranges(self) -> "VisitSettings":
        for host, weight in self.cookie_farming_donor_weights.items():
            pages = {
                url
                for url in self.cookie_farming_sites
                if (urlsplit(url).hostname or "").removeprefix("www.") == host.removeprefix("www.")
            }
            if not 0 < weight <= 1 or len(pages) < 2:
                raise ValueError("Donor weights require positive shares and two approved pages")
        if any(
            name not in self.cookie_farming_clusters or not 0 < weight <= 10
            for name, weight in self.cookie_farming_cluster_weights.items()
        ):
            raise ValueError("Cluster weights must reference configured clusters and be in (0, 10]")
        if self.cookie_farming_enabled and len(self.cookie_farming_sites) < 2:
            raise ValueError("Для Cookie-Farming укажите минимум два HTTPS-сайта")
        for sites in self.cookie_farming_clusters.values():
            if len(set(sites)) < 2 or not set(sites) <= set(self.cookie_farming_sites):
                raise ValueError("Кластер должен содержать минимум два адреса из списка подготовки")
        if self.duration_min_seconds > self.duration_max_seconds:
            raise ValueError("Minimum visit duration exceeds maximum")
        if self.daily_change_min > self.daily_change_max:
            raise ValueError("Minimum daily change exceeds maximum")
        if self.enabled and not any(any(day) for day in self.weekly_schedule):
            raise ValueError("Select at least one visiting hour")
        if self.timeline_enabled:
            validate_action_timeline(self.actions, self.duration_min_seconds, self.activity)
        return self


class IncubationDailyQuotaStatus(BaseModel):
    target: int
    completed: int
    active: int
    remaining: int
    failed: int
    failure_limit: int


class CookieFarmingStatus(BaseModel):
    ultra_load: bool = False
    total_active_profiles: int = 0
    stage_0_initialization: int = 0
    stage_1_warming: int = 0
    stage_2_ready: int = 0
    expired_profiles: int = 0
    failed_profiles: int = 0
    proxy_balance_status: dict | None = None
    enabled: bool
    started_at: str | None
    cold_profiles_until: str | None
    daily_target: int
    warming_day_1: int = 0
    warming_day_2: int = 0
    ready: int = 0
    consumed: int = 0
    failed: int = 0
    expired: int = 0
    warming: int = 0
    min_days: int = 7
    max_days: int = 14
    buffer_factor: float = 1.5
    cluster_reserves: dict[str, dict] = Field(default_factory=dict)
    days_left: dict[str, int] = Field(default_factory=dict)
    planned_at: str | None = None
    error: str | None = None
    daily_new_profile_target: int | None = None
    daily_quota: IncubationDailyQuotaStatus | None = None
    profiles_created_today: int = 0
    sessions_started_today: int = 0
    sessions_queued: int = 0
    dispatch_blocked_reason: str | None = None
    proxy_balance: dict | None = None


class ScheduledTestDay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_date: date
    sessions: int = Field(ge=0, le=100000, strict=True)


class ScheduledTestPlan(BaseModel):
    days: list[ScheduledTestDay] = Field(default_factory=list, max_length=366)

    @model_validator(mode="after")
    def distinct_dates(self) -> "ScheduledTestPlan":
        if len({day.scheduled_date for day in self.days}) != len(self.days):
            raise ValueError("Duplicate scheduled test date")
        return self


class VisitExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    traffic_optimization_level: Literal["disabled", "metadata_only", "strict"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    traffic_source: TrafficSource | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    utm_config: UtmConfig | None = Field(default=None, exclude_if=lambda value: value is None)
    messenger_mode: Literal["web", "mobile", "desktop"] = "desktop"
    duration_seconds: float = Field(ge=15, le=900)
    interval_seconds: float = Field(default=1, ge=1, le=8640000)
    activity: Literal["no_clicks", "scenario"]
    scroll_enabled: bool
    timeline_enabled: bool = Field(default=False, exclude_if=lambda value: not value)
    actions: list[VisitAction] = Field(
        default_factory=list, max_length=50, exclude_if=lambda value: not value
    )
    session_behavior_pattern: Literal["PATTERN_A", "PATTERN_B", "PATTERN_C"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    max_depth_limit: int = Field(default=1, ge=1, le=400001, exclude_if=lambda value: value == 1)

    @model_validator(mode="after")
    def valid_timeline(self) -> "VisitExecution":
        if self.session_behavior_pattern is not None:
            AnalyticsRoute(
                session_behavior_pattern=self.session_behavior_pattern,
                max_depth_limit=self.max_depth_limit,
            )
            if self.timeline_enabled or self.actions:
                raise ValueError("Analytics routes cannot include timed actions")
        elif self.max_depth_limit != 1:
            raise ValueError("Depth limit requires an analytics behavior pattern")
        if self.timeline_enabled:
            validate_action_timeline(self.actions, self.duration_seconds, self.activity)
        return self
