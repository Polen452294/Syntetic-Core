"""Exact, operator-controlled target authorization for local browser testing."""

from urllib.parse import urlsplit

from syntetic_core._engine.config import Settings, get_settings
from syntetic_core._engine.errors import DomainError


def authorize_url(url: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".").encode("idna").decode()
        allowed = {
            h.lower().rstrip(".").encode("idna").decode() for h in settings.allowed_target_hosts
        }
        valid = (
            parsed.scheme in {"http", "https"}
            and host in allowed
            and not parsed.username
            and not parsed.password
            and parsed.port != 0
        )
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        raise DomainError(
            "Target is not authorized; ask the operator to update ALLOWED_TARGET_HOSTS"
        )
