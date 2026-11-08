"""Carry saved native identity into a fresh QA profile without reusing site storage."""

from pathlib import Path
from typing import Any

from syntetic_core._engine.browser.identity import read_json, write_json
from syntetic_core._engine.personas import BrowserPersona


def identity_paths(profile: Path, persona: BrowserPersona) -> dict[str, Path]:
    paths = {
        "ios": profile.parent / "ios-identity.json",
        "canvas": profile.parent / "canvas-identity.json",
    }
    if persona.browser_engine == "chromium":
        paths["hardware"] = profile.parent / "session-hardware-identity.json"
    if persona.emulation is not None:
        paths["emulation"] = profile.parent / "emulation-identity.json"
    if persona.fingerprint_id:
        paths["fingerprint"] = profile.parent / "fingerprints" / f"{persona.fingerprint_id}.json"
    else:
        paths["fingerprint"] = profile.parent / (
            "native-identity.json"
            if persona.runtime.backend == "camoufox"
            else "chromium-identity.json"
        )
    return paths


def capture_identity(profile: Path, persona: BrowserPersona) -> dict[str, Any]:
    return {
        name: data
        for name, path in identity_paths(profile, persona).items()
        if (data := read_json(path))
    }


def restore_identity(profile: Path, persona: BrowserPersona, data: dict[str, Any]) -> None:
    paths = identity_paths(profile, persona)
    if set(data) - paths.keys():
        raise ValueError("Unknown replay identity section")
    for name, identity in data.items():
        if not isinstance(identity, dict):
            raise ValueError("Replay identity must be a JSON object")
        write_json(paths[name], identity)


def hardware_key(persona: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "device",
        "phone",
        "native_audio",
        "native_desktop",
        "native_media",
        "emulation",
        "coherence",
        "chromium",
        "runtime",
        "fingerprint_id",
        "browser_engine",
    )
    return {key: persona.get(key) for key in keys}
