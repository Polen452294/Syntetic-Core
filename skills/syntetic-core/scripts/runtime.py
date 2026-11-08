"""Locate, explicitly bootstrap, or run the skill's Syntetic Core runtime."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
import venv
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


def interpreter(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def project_runtime(path: Path) -> dict[str, str] | None:
    manifest = path / "pyproject.toml"
    if not manifest.is_file():
        return None
    try:
        name = tomllib.loads(manifest.read_text("utf-8"))["project"]["name"]
    except (OSError, ValueError, KeyError):
        return None
    python = interpreter(path / ".venv")
    if name != "syntetic-core" or not python.is_file():
        return None
    return {
        "kind": "project",
        "project_root": str(path.resolve()),
        "python": str(python.resolve()),
        "readme": str((path / "README.md").resolve()),
    }


def managed_home() -> Path:
    return (
        Path(
            os.environ.get(
                "SYNTETIC_CORE_SKILL_RUNTIME",
                str(Path.home() / ".cache/syntetic-core/skill-runtime"),
            )
        )
        .expanduser()
        .resolve()
    )


def locate() -> dict[str, str]:
    explicit = os.environ.get("SYNTETIC_CORE_HOME")
    if explicit:
        found = project_runtime(Path(explicit).expanduser().resolve())
        if found is None:
            raise ValueError("SYNTETIC_CORE_HOME must point to a checkout with its own .venv")
        return found
    pointer = SKILL / "runtime.json"
    if pointer.is_file():
        record = json.loads(pointer.read_text("utf-8"))
        path = record.get("project_root")
        if isinstance(path, str) and (found := project_runtime(Path(path))) is not None:
            return found
    for path in SKILL.parents:
        if (found := project_runtime(path)) is not None:
            return found
    managed = managed_home()
    marker = managed / ".syntetic-core-runtime.json"
    if marker.is_file() and interpreter(managed).is_file():
        state = json.loads(marker.read_text("utf-8"))
        if state.get("package") == "syntetic-core" and state.get("ready") is True:
            return {
                "kind": "managed",
                "python": str(interpreter(managed)),
                "runtime_root": str(managed),
            }
    raise FileNotFoundError("No Syntetic Core runtime found; run this helper's setup command")


def child_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONHOME", "PYTHONPATH"}
    }


def setup(directory: Path) -> dict[str, str]:
    if sys.version_info < (3, 12):  # noqa: UP036 -- this helper may be run by Python 3.11
        raise ValueError("Setup requires Python 3.12 or newer")
    directory = directory.expanduser().resolve()
    marker = directory / ".syntetic-core-runtime.json"
    if directory.exists() and not marker.is_file():
        raise FileExistsError("Refusing to modify an existing unmanaged runtime directory")
    if marker.is_file() and json.loads(marker.read_text("utf-8")).get("package") != "syntetic-core":
        raise ValueError("Runtime directory belongs to another installation")
    wheel = SKILL / "assets/syntetic_core-0.1.0-py3-none-any.whl"
    constraints = SKILL / "assets/requirements.lock"
    if not wheel.is_file() or not constraints.is_file():
        raise FileNotFoundError("Bundled runtime wheel or constraints are missing")
    directory.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"package": "syntetic-core", "version": "0.1.0", "ready": False}), "utf-8"
    )
    if not interpreter(directory).is_file():
        venv.EnvBuilder(with_pip=True).create(directory)
    subprocess.run(
        [str(interpreter(directory)), "-m", "pip", "install", "-c", str(constraints), str(wheel)],
        check=True,
        env=child_environment(),
    )
    marker.write_text(
        json.dumps({"package": "syntetic-core", "version": "0.1.0", "ready": True}), "utf-8"
    )
    return {
        "kind": "managed",
        "python": str(interpreter(directory)),
        "runtime_root": str(directory),
    }


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"python", "cli"}:
        runtime = locate()
        tail = sys.argv[2:]
        if tail[:1] == ["--"]:
            tail = tail[1:]
        prefix = [runtime["python"]]
        if sys.argv[1] == "cli":
            prefix += ["-m", "syntetic_core"]
        return subprocess.run(prefix + tail, env=child_environment(), check=False).returncode
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("info")
    install = commands.add_parser("setup")
    install.add_argument("--venv", type=Path)
    for name in ("python", "cli"):
        command = commands.add_parser(name)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == "setup":
        print(json.dumps(setup(args.venv or managed_home()), indent=2))
        return 0
    runtime = locate()
    if args.command == "info":
        print(json.dumps(runtime, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
