"""Context-wide traffic filtering for sessions that do not need media assets."""

import logging
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Route
from playwright.async_api import Error as PlaywrightError
from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

if TYPE_CHECKING:
    from syntetic_core._engine.config import Settings

logger = logging.getLogger(__name__)

ALLOWED_RESOURCE_TYPES = frozenset({"document", "script", "xhr", "fetch"})
ADS_AND_TRACKERS_BLACKLIST = (
    "doubleclick.net",
    "google-analytics.com",
    "googleadservices.com",
    "adsafeprotected.com",
    "adnxs.com",
    "yabs.yandex.ru",
    "yandex.ru/ads/",
)


class TrafficPolicy(BaseModel):
    """Resolved session policy, persisted verbatim for experiment replay."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal[1, 2] = 1
    enabled: bool
    block_stylesheets: bool
    level: Literal["disabled", "metadata_only", "strict"] | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler: SerializerFunctionWrapHandler) -> dict:
        data = handler(self)
        if self.version == 1:
            data.pop("level", None)
        return data

    @model_validator(mode="after")
    def coherent(self) -> "TrafficPolicy":
        if (self.version == 2) != (self.level is not None):
            raise ValueError("Version 2 requires an explicit optimization level")
        if self.level is not None and self.enabled != (self.level != "disabled"):
            raise ValueError("Optimization level and enabled flag disagree")
        if self.block_stylesheets and not self.enabled:
            raise ValueError("Stylesheet filtering requires an enabled TrafficOptimizer")
        return self

    @classmethod
    def from_settings(cls, settings: "Settings") -> "TrafficPolicy":
        if settings.traffic_optimization_level is not None:
            level = settings.traffic_optimization_level
            return cls(
                version=2,
                level=level,
                enabled=level != "disabled",
                block_stylesheets=level != "disabled" and settings.block_stylesheets,
            )
        incubation = bool(settings.incubation_config)
        enabled = settings.traffic_optimizer_enabled
        if enabled is None:
            enabled = incubation
        return cls(
            enabled=enabled,
            block_stylesheets=enabled and incubation and settings.block_stylesheets,
        )


def _matches_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _hostname(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Traffic filtering requires an HTTP(S) URL with a hostname")
    return parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()


class TrafficOptimizer:
    def __init__(
        self,
        block_stylesheets: bool = False,
        *,
        base_url: str | None = None,
        level: Literal["disabled", "metadata_only", "strict"] | None = None,
    ) -> None:
        self.allowed_types: frozenset[str] = ALLOWED_RESOURCE_TYPES | (
            frozenset() if block_stylesheets else {"stylesheet"}
        )
        self.target_host = _hostname(base_url) if base_url is not None else None
        self.target_origin = self._origin(base_url) if base_url else None
        self.level = level
        self.block_stylesheets = block_stylesheets

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int]:
        parsed = urlsplit(url)
        return (
            parsed.scheme,
            _hostname(url),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    async def attach_to_context(self, context: BrowserContext) -> None:
        """Attach before navigation; callers must disable service workers.

        Playwright routing disables the context's HTTP cache. Register navigation
        guards afterwards and have them fall back to this handler on success.
        """
        await context.route("**/*", self._handle_route)
        logger.info("TrafficOptimizer attached to browser context")

    def _blocked_reason(self, resource_type: str, url: str) -> str | None:
        if self.level == "disabled":
            return None
        if self.level is not None:
            try:
                origin = self._origin(url)
            except (ValueError, UnicodeError):
                return "invalid_url"
            if resource_type in {"media", "font", "manifest", "webmanifest"} or (
                resource_type == "stylesheet" and self.block_stylesheets
            ):
                return "resource_type"
            if self.level == "metadata_only":
                return None
            if resource_type == "image" and origin != self.target_origin:
                return "resource_type"
            host, path = origin[1], urlsplit(url).path.lower()
            for pattern in ADS_AND_TRACKERS_BLACKLIST:
                domain, _, prefix = pattern.partition("/")
                if _matches_domain(host, domain) and (
                    not prefix or path == "/" + prefix.rstrip("/") or path.startswith("/" + prefix)
                ):
                    return "advertising_domain"
            return None
        if resource_type not in self.allowed_types:
            return "resource_type"
        try:
            host = _hostname(url)
            path = urlsplit(url).path.lower()
        except (ValueError, UnicodeError):
            return "invalid_url"
        if (
            (self.target_host is not None and _matches_domain(host, self.target_host))
            or _matches_domain(host, "ya.ru")
            or _matches_domain(host, "clck.yandex.ru")
            or _matches_domain(host, "passport.yandex.ru")
        ):
            return None
        for pattern in ADS_AND_TRACKERS_BLACKLIST:
            domain, _, prefix = pattern.partition("/")
            if _matches_domain(host, domain) and (
                not prefix or path == "/" + prefix.rstrip("/") or path.startswith("/" + prefix)
            ):
                return "advertising_domain"
        return None

    async def _handle_route(self, route: Route) -> None:
        request = route.request
        reason = self._blocked_reason(request.resource_type, request.url)
        try:
            if reason is not None:
                # Do not log URLs: query strings can contain session credentials.
                logger.debug("TrafficOptimizer blocked %s (%s)", request.resource_type, reason)
                await route.abort("aborted")
            else:
                await route.continue_()
        except PlaywrightError:
            # Do not retry with continue_(): a failed abort must never allow egress.
            logger.debug("TrafficOptimizer route failed (%s)", request.resource_type)
            raise
