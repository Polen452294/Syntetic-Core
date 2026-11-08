"""Profile-owned runtime identity and bounded session history (no browser storage values)."""

import hashlib
import json
from pathlib import Path
from typing import Any

from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.profile_storage import atomic_json


def profile_identity_hashes(profile_path: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((profile_path.parent / name).read_bytes()).hexdigest()
        for name in ("canvas-identity.json", "session-hardware-identity.json")
        if (profile_path.parent / name).exists()
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        return data
    except (OSError, ValueError):
        raise ProfileValidationError(f"Invalid profile identity file: {path.name}") from None


def write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_json(path, data)


def check_storage_engine(profile_path: Path, engine: str, state: dict[str, Any]) -> None:
    owner_engine = state.get("engine")
    if owner_engine and owner_engine != engine:
        raise ProfileValidationError(
            "Changing a persistent profile's engine requires a new profile"
        )
    if (profile_path / "Default").exists() and engine != "chromium":
        raise ProfileValidationError("Chromium storage cannot be opened by another engine")
    if (profile_path / "prefs.js").exists() and engine != "firefox":
        raise ProfileValidationError("Firefox storage cannot be opened by another engine")


def record_session(
    state: dict[str, Any],
    *,
    engine: str,
    backend: str,
    proxy_id: str | None,
    observation: dict[str, Any],
    started: float,
    finished: float,
    success: bool,
    identity_accepted: bool = True,
) -> dict[str, Any]:
    old_ip = state.get("network", {}).get("ip")
    new_ip = observation.get("ip")
    changed = state.get("proxy_id") != proxy_id or (old_ip and new_ip and old_ip != new_ip)
    identity_since = started if changed or not state else state.get("identity_since", started)
    history = state.get("sessions", [])[-99:]
    history.append(
        {
            "started": started,
            "finished": finished,
            "success": success,
            "proxy_id": proxy_id,
            "ip": new_ip,
        }
    )
    if not identity_accepted:
        return {
            **state,
            "engine": engine,
            "backend": backend,
            "session_count": state.get("session_count", 0) + 1,
            "sessions": history,
        }
    return {
        "engine": engine,
        "backend": backend,
        "proxy_id": proxy_id,
        "identity_since": identity_since,
        "network": observation,
        "session_count": state.get("session_count", 0) + 1,
        "sessions": history,
    }
