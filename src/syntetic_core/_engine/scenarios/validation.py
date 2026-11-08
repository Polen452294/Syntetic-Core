from collections.abc import Iterator
from typing import Annotated, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from syntetic_core._engine.errors import ScenarioValidationError
from syntetic_core._engine.schemas.visits import VisitAction


class StepBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StepTiming(StepBase):
    min_ms: int = Field(ge=0, le=60000)
    max_ms: int = Field(ge=0, le=60000)

    @model_validator(mode="after")
    def ordered(self) -> "StepTiming":
        if self.min_ms > self.max_ms:
            raise ValueError("Timing minimum exceeds maximum")
        return self


class TimedStep(StepBase):
    timing: StepTiming | None = None


class UrlStep(StepBase):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            raise ValueError("Only HTTP(S) or relative URLs are supported")
        if parsed.username or parsed.password:
            raise ValueError("URL credentials are not supported")
        return value


class OpenStep(UrlStep):
    action: Literal["open", "goto"]
    timing: StepTiming | None = None


class HttpCheckStep(UrlStep):
    action: Literal["http_check"]
    method: Literal["GET", "HEAD"] = "GET"
    expected_status: int = Field(default=200, ge=100, le=599)


class WaitStep(StepBase):
    action: Literal["wait"]
    seconds: float = Field(ge=0, le=60)


class ClickStep(TimedStep):
    action: Literal["click"]
    selector: str = Field(min_length=1, max_length=1000)


class ScrollStep(TimedStep):
    action: Literal["scroll"]
    percent: float = Field(ge=0, le=100)


class InputStep(TimedStep):
    action: Literal["input", "fill"]
    selector: str = Field(min_length=1, max_length=1000)
    value: str = Field(max_length=10000)


class TypeStep(TimedStep):
    action: Literal["type"]
    selector: str = Field(min_length=1, max_length=1000)
    value: str = Field(max_length=10000)


class EditStep(TimedStep):
    action: Literal["edit"]
    selector: str = Field(min_length=1, max_length=1000)
    operation: Literal["append", "replace", "delete", "insert"]
    value: str | None = Field(default=None, max_length=10000)
    count: int = Field(default=1, ge=1, le=1000)

    @model_validator(mode="after")
    def operation_arguments(self) -> "EditStep":
        if self.operation == "delete" and self.value is not None:
            raise ValueError("delete accepts count, not value")
        if self.operation != "delete" and self.value is None:
            raise ValueError("This edit operation requires value")
        if self.operation != "delete" and self.count != 1:
            raise ValueError("count is only supported by delete")
        return self


class PauseStep(StepBase):
    action: Literal["pause"]
    purpose: Literal["inspect", "decide"] = "decide"
    min_seconds: float = Field(ge=0, le=60)
    max_seconds: float = Field(ge=0, le=60)

    @model_validator(mode="after")
    def ordered(self) -> "PauseStep":
        if self.min_seconds > self.max_seconds:
            raise ValueError("Pause minimum exceeds maximum")
        return self


class ReadStep(StepBase):
    action: Literal["read"]
    selector: str = Field(min_length=1, max_length=1000)
    words_per_minute: int = Field(default=200, ge=30, le=1000)
    min_seconds: float = Field(default=0, ge=0, le=60)
    max_seconds: float = Field(default=60, ge=0, le=60)

    @model_validator(mode="after")
    def ordered(self) -> "ReadStep":
        if self.min_seconds > self.max_seconds:
            raise ValueError("Reading minimum exceeds maximum")
        return self


class HoverStep(TimedStep):
    action: Literal["hover"]
    selector: str = Field(min_length=1, max_length=1000)


class FocusStep(TimedStep):
    action: Literal["focus"]
    selector: str = Field(min_length=1, max_length=1000)


class PressStep(TimedStep):
    action: Literal["press"]
    selector: str = Field(min_length=1, max_length=1000)
    key: str = Field(min_length=1, max_length=100)


class HistoryStep(TimedStep):
    action: Literal["back", "forward"]


class SelectStep(TimedStep):
    action: Literal["select"]
    selector: str = Field(min_length=1, max_length=1000)
    values: list[str] = Field(min_length=1, max_length=100)


class WaitForStep(StepBase):
    action: Literal["wait_for"]
    selector: str = Field(min_length=1, max_length=1000)
    state: Literal["attached", "detached", "visible", "hidden"] = "visible"


class WaitUrlStep(UrlStep):
    action: Literal["wait_for_url"]


class WaitResponseStep(UrlStep):
    action: Literal["wait_for_response"]
    status: int | None = Field(default=None, ge=100, le=599)
    trigger_selector: str | None = Field(default=None, min_length=1, max_length=1000)
    timing: StepTiming | None = None

    @model_validator(mode="after")
    def timing_requires_trigger(self) -> "WaitResponseStep":
        if self.timing is not None and self.trigger_selector is None:
            raise ValueError("Response timing requires trigger_selector")
        return self


class ScrollIntoViewStep(TimedStep):
    action: Literal["scroll_into_view"]
    selector: str = Field(min_length=1, max_length=1000)


class EvaluateStep(StepBase):
    action: Literal["evaluate"]
    expression: str = Field(min_length=1, max_length=10000)


class AssertTextStep(StepBase):
    action: Literal["assert_text"]
    selector: str = Field(default="body", min_length=1, max_length=1000)
    text: str = Field(min_length=1, max_length=10000)


class AssertUrlStep(UrlStep):
    action: Literal["assert_url"]


class ScreenshotStep(StepBase):
    action: Literal["screenshot"]


class CloseStep(StepBase):
    action: Literal["close"]


Step = Annotated[
    HttpCheckStep
    | OpenStep
    | WaitStep
    | ClickStep
    | ScrollStep
    | InputStep
    | TypeStep
    | EditStep
    | PauseStep
    | ReadStep
    | HoverStep
    | FocusStep
    | PressStep
    | HistoryStep
    | SelectStep
    | WaitForStep
    | WaitUrlStep
    | WaitResponseStep
    | ScrollIntoViewStep
    | EvaluateStep
    | AssertTextStep
    | AssertUrlStep
    | ScreenshotStep
    | CloseStep,
    Field(discriminator="action"),
]


class ScenarioRoute(StepBase):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    weight: int = Field(default=1, ge=1, le=1000)
    steps: list[Step] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def close_is_last(self) -> "ScenarioRoute":
        if any(step.action == "close" for step in self.steps[:-1]):
            raise ValueError("close must be the last step")
        return self


YANDEX_HOME = "https://ya.ru/"
YANDEX_SSO_HOSTS = frozenset({"sso.ya.ru", "sso.passport.yandex.ru"})


class SearchEntry(StepBase):
    engine: Literal["yandex"] = "yandex"
    queries: list[str] = Field(min_length=1, max_length=1000)
    max_pages: int = Field(default=15, ge=1, le=100)
    timeout_seconds: int = Field(default=90, ge=1, le=600)

    @field_validator("queries", mode="before")
    @classmethod
    def query_lines(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.lstrip("\ufeff").splitlines()
        if isinstance(value, list):
            if any(not isinstance(query, str) for query in value):
                raise ValueError("Queries must contain only text")
            queries = list(dict.fromkeys(query.strip() for query in value if query.strip()))
            if any(len(query) > 500 or "\n" in query or "\r" in query for query in queries):
                raise ValueError("Each query must be one line of at most 500 characters")
            return queries
        return value


class SemanticConfig(StepBase):
    topic: Literal["news", "technology", "information"] = "information"
    seed: int | None = None
    max_actions: int = Field(default=20, ge=1, le=100)


class ScenarioDefinition(StepBase):
    semantic: SemanticConfig | None = None
    name: str = Field(min_length=1, max_length=200)
    steps: list[Step] = Field(default_factory=list, max_length=100)
    routes: list[ScenarioRoute] = Field(default_factory=list, max_length=10)
    route_seed: int | None = None
    measure_interactions: bool = False
    search_entry: SearchEntry | None = None
    visit_actions: list[VisitAction] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def valid_paths(self) -> "ScenarioDefinition":
        if self.semantic and (
            self.routes
            or len(self.steps) != 1
            or not isinstance(self.steps[0], OpenStep)
            or self.visit_actions is not None
        ):
            raise ValueError("Semantic mode requires a single opening step without routes")
        if bool(self.steps) == bool(self.routes):
            raise ValueError("Provide either nonempty steps or routes")
        if any(step.action == "close" for step in self.steps[:-1]):
            raise ValueError("close must be the last step")
        if len({route.name for route in self.routes}) != len(self.routes):
            raise ValueError("Route names must be unique")
        if sum(len(route.steps) for route in self.routes) > 100:
            raise ValueError("All routes together must contain at most 100 steps")
        if any(isinstance(step, HttpCheckStep) for step in self.iter_steps()):
            if (
                self.routes
                or self.search_entry
                or self.visit_actions is not None
                or self.measure_interactions
                or not all(isinstance(step, HttpCheckStep) for step in self.steps)
            ):
                raise ValueError("http_check requires HTTP-only steps without browser options")
        return self

    @property
    def execution_mode(self) -> Literal["browser", "lightweight"]:
        return (
            "lightweight"
            if self.steps and all(isinstance(step, HttpCheckStep) for step in self.steps)
            else "browser"
        )

    def iter_steps(self) -> Iterator[Step]:
        yield from self.steps
        for route in self.routes:
            yield from route.steps


def validate_scenario(source: str) -> ScenarioDefinition:
    if len(source.encode("utf-8")) > 65536:
        raise ScenarioValidationError("YAML exceeds 64 KiB")
    try:
        # Aliases are unnecessary for this DSL and can produce recursive/expanded documents.
        if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(source)):
            raise ScenarioValidationError("YAML aliases are not supported")
        return ScenarioDefinition.model_validate(yaml.safe_load(source))
    except ValidationError as exc:
        errors = [
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
            for e in exc.errors(include_input=False, include_context=False)
        ]
        raise ScenarioValidationError("; ".join(errors)) from None
    except (yaml.YAMLError, ValueError, RecursionError):
        raise ScenarioValidationError("Invalid YAML document") from None
