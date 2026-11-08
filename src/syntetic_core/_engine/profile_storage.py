"""Small durable identity, independent of mutable browser databases.

Creation permits are consumed by the controller before filesystem I/O. A missing
store can therefore never be reinitialized by a later delivery of the same task.
"""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona

MANIFEST = "storage-manifest.json"


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def new_identity(profile_id: int, persona: BrowserPersona, owner: str | None) -> dict:
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "incarnation_id": str(uuid4()),
        "owner_worker_id": owner,
        "engine": None,
        "backend": None,
        "channel": None,
        "metadata_revision": persona.persona_revision,
    }


def initialize_store(path: Path, identity: dict) -> None:
    # Caller must own ProfileLock. Never overwrite pre-existing storage.
    if path.parent.exists():
        raise ProfileValidationError(
            "Profile storage already exists; reconcile instead of replacing"
        )
    path.mkdir(parents=True, exist_ok=False)
    atomic_json(path / ".storage-incarnation.json", identity)
    atomic_json(path.parent / MANIFEST, identity)


def verify_store(path: Path, expected: dict, persona: BrowserPersona) -> dict:
    stage = "directory"
    try:
        if not path.is_dir() or path.is_symlink() or path.parent.is_symlink():
            raise ValueError("Missing browser directory")
        stage = "manifest"
        manifest = json.loads((path.parent / MANIFEST).read_text(encoding="utf-8"))
        stage = "incarnation_marker"
        marker = json.loads((path / ".storage-incarnation.json").read_text(encoding="utf-8"))
        stage = "identity"
        keys = ("schema_version", "profile_id", "incarnation_id", "owner_worker_id")
        if expected.get("schema_version") != 1 or any(
            manifest.get(key) != expected.get(key) or marker.get(key) != expected.get(key)
            for key in keys
        ):
            raise ValueError("Storage identity mismatch")
        if int(persona.id) != expected["profile_id"]:
            raise ValueError("Profile mismatch")
        stage = "runtime_binding"
        runtime = {
            "engine": persona.browser_engine,
            "backend": persona.runtime.backend,
            "channel": persona.runtime.channel,
        }
        if manifest.get("engine") is None and marker.get("engine") is None:
            manifest.update(runtime)
            marker.update(manifest)
            atomic_json(path / ".storage-incarnation.json", marker)
        elif (
            manifest.get("engine") is None
            and not manifest.get("required_files")
            and all(marker.get(key) == value for key, value in runtime.items())
        ):
            # The marker is committed first. A crash before the manifest replace
            # leaves a valid, identified store with a partially committed binding.
            # Complete that exact binding; never recreate files or change runtime.
            manifest.update(runtime)
        for key, value in runtime.items():
            if manifest.get(key) != value or marker.get(key) != value:
                raise ValueError("Runtime incompatible with stored browser data")
        for name in manifest.get("required_files", []):
            stage = "required_file"
            candidate = (path / name).resolve()
            if not candidate.is_relative_to(path.resolve()) or not candidate.is_file():
                raise ValueError("Previously observed browser storage file is missing")
            if name in {"Local State", "Default/Preferences"}:
                stage = "browser_json"
                json.loads(candidate.read_text(encoding="utf-8"))
            elif name.endswith((".sqlite", "Cookies")):
                stage = "browser_sqlite"
                with sqlite3.connect(candidate.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
                    if db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                        raise ValueError("Browser database failed integrity check")
        stage = "write_probe"
        probe = path / f".write-probe-{uuid4().hex}"
        try:
            with probe.open("x") as handle:
                handle.write("ok")
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            probe.unlink(missing_ok=True)
        stage = "manifest_commit"
        receipt = {**manifest, "last_verified_at": datetime.now(UTC).isoformat()}
        atomic_json(path.parent / MANIFEST, receipt)
        return receipt
    except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
        raise ProfileValidationError(
            "Persistent storage missing, corrupt, replaced or runtime incompatible; "
            f"restore required (check: {stage})"
        ) from None


def record_closed_store(path: Path, persona: BrowserPersona, browser_version: str) -> None:
    """Record inexpensive structural checks only after browser writes have stopped."""
    manifest_path = path.parent / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        metadata_revision=persona.persona_revision,
        browser_version=browser_version,
        required_files=[
            name
            for name in (
                "Local State",
                "Default/Preferences",
                "Default/Network/Cookies",
                "Default/Cookies",
                "prefs.js",
                "cookies.sqlite",
                "places.sqlite",
            )
            if (path / name).is_file()
        ],
    )
    atomic_json(manifest_path, manifest)
