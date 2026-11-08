"""Only explicitly transient failures are retried; the database owns attempts."""

import re

from syntetic_core._engine.config import Settings

MAX_DAY_ATTEMPTS_MULTIPLIER = 2.5

PROXY_FAILURES = {"ProxyUnavailableError", "ProxyIdentityChangedError"}
PROXY_ERROR_CODE = re.compile(
    r"\b(?:ERR_(?:PROXY_[A-Z_]+|TUNNEL_CONNECTION_FAILED|NO_SUPPORTED_PROXIES|SOCKS_CONNECTION_FAILED)"
    r"|NS_ERROR_(?:PROXY_[A-Z_]+|UNKNOWN_PROXY_HOST))\b"
)

RETRYABLE = {
    "NavigationTimeout",
    "TemporaryNetworkError",
    "BrowserCrash",
    "PageCrash",
    "TemporaryTargetUnavailable",
    "SessionTimeoutError",
    "WorkerInterruptedError",
    "WorkerLost",
    "StaleSession",
    "ProfileLockedError",
    "ArtifactUploadError",
    "LeaseLost",
    "TransportUnavailable",
}


def retry_delay(attempt: int, settings: Settings) -> float:
    return min(
        settings.retry_max_delay,
        settings.retry_initial_delay * settings.retry_backoff_multiplier ** max(0, attempt - 1),
    )


def classify_error(exc: BaseException) -> tuple[str, str]:
    import httpx
    from playwright.async_api import Error as PlaywrightError

    from syntetic_core._engine.errors import DomainError, ScenarioError

    if isinstance(exc, httpx.HTTPError):
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            return "LeaseLost", "Controller rejected attempt ownership"
        return "TransportUnavailable", "Controller connection temporarily unavailable"

    if isinstance(exc, TimeoutError):
        return "SessionTimeoutError", "Session exceeded its total timeout"
    if isinstance(exc, AssertionError):
        return "AssertionFailed", "Scenario assertion failed"
    if isinstance(exc, PlaywrightError):
        if PROXY_ERROR_CODE.search(str(exc)):
            return "ProxyUnavailableError", "Browser proxy connection failed"
        message = str(exc).lower()
        if "crash" in message:
            return "PageCrash", "Browser page crashed"
        if "closed" in message:
            return "BrowserCrash", "Browser connection closed"
        if "selector" in message:
            return "InvalidSelectorDefinition", "Invalid selector definition"
        return "ScenarioError", "Browser action failed"
    if (
        isinstance(exc, (DomainError, ScenarioError))
        or type(exc).__module__ == "syntetic_core._engine.errors"
    ):
        return type(exc).__name__, str(exc)[:1000]
    return "InternalWorkerError", "Internal worker failure"
