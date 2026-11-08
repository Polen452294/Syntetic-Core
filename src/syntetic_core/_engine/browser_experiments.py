"""Bounded, opt-in test conditions; never part of the hardware identity."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_ms: int = Field(default=0, strict=True, ge=0, le=300000)


class NetworkCondition(Condition):
    kind: Literal["network"] = "network"
    offline: bool = False
    latency_ms: int = Field(default=0, ge=0, le=2000)
    download_kbps: int = Field(default=0, ge=0, le=1000000)
    upload_kbps: int = Field(default=0, ge=0, le=1000000)


class Insets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top: int = Field(default=0, ge=0, le=200)
    right: int = Field(default=0, ge=0, le=200)
    bottom: int = Field(default=0, ge=0, le=200)
    left: int = Field(default=0, ge=0, le=200)


class KeyboardGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["viewport", "native"] = "viewport"
    x: int = Field(default=0, ge=0, le=10000)
    y: int = Field(default=0, ge=0, le=10000)
    width: int = Field(ge=0, le=10000)
    height: int = Field(ge=0, le=10000)


class DisplayCondition(Condition):
    kind: Literal["display"] = "display"
    width: int = Field(ge=200, le=5000)
    height: int = Field(ge=200, le=5000)
    orientation: Literal["portrait", "landscape"] = "portrait"
    page_scale: float = Field(default=1, ge=1, le=3, allow_inf_nan=False)
    safe_area: Insets | None = None
    keyboard: KeyboardGeometry | None = None
    posture: Literal["continuous", "folded"] | None = None


class LocationCondition(Condition):
    kind: Literal["location"] = "location"
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float = Field(default=50, ge=0, le=100000, allow_inf_nan=False)


class StorageCondition(Condition):
    kind: Literal["storage"] = "storage"
    # Operators name the target site's keys. No cross-origin clearing is allowed.
    remove_cookies: list[str] = Field(default_factory=list, max_length=50)
    remove_local_storage: list[str] = Field(default_factory=list, max_length=50)
    expire_cookies: dict[str, str] = Field(default_factory=dict, max_length=50)

    @field_validator("remove_cookies", "remove_local_storage")
    @classmethod
    def bounded_keys(cls, values: list[str]) -> list[str]:
        if any(not key or len(key) > 128 for key in values):
            raise ValueError("Storage keys must contain 1–128 characters")
        return list(dict.fromkeys(values))

    @field_validator("expire_cookies")
    @classmethod
    def bounded_cookies(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not k or len(k) > 128 or len(v) > 4096 for k, v in values.items()):
            raise ValueError("Cookie key or value exceeds its limit")
        return values


class HistoryCondition(Condition):
    kind: Literal["history"] = "history"
    direction: Literal["back", "forward", "reload"]


ExperimentEvent = Annotated[
    NetworkCondition | DisplayCondition | LocationCondition | StorageCondition | HistoryCondition,
    Field(discriminator="kind"),
]


class BrowserExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int = Field(default=1, ge=0, le=2**32 - 1)
    events: list[ExperimentEvent] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def ordered(self) -> "BrowserExperiment":
        if any(a.after_ms > b.after_ms for a, b in zip(self.events, self.events[1:], strict=False)):
            raise ValueError("Experiment events must be ordered by after_ms")
        return self


class NativeMediaPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    devices: Literal["library", "none", "laptop", "conference"] = "library"
    voices: Literal["library", "none", "local"] = "library"
