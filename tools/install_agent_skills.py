"""Install the shared Syntetic Core skill for Codex and/or Claude Code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills/syntetic-core"
STAMP = ".syntetic-core-install.json"


def skill_files(source: Path) -> list[Path]:
    return sorted(
        p
        for p in source.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_one(source: Path, destination: Path, project: Path) -> Path:
    files = skill_files(source)
    for required in (
        "SKILL.md",
        "scripts/runtime.py",
        "assets/requirements.lock",
        "assets/syntetic_core-0.1.0-py3-none-any.whl",
    ):
        if not (source / required).is_file():
            raise FileNotFoundError(f"Incomplete skill source: {required}")
    if destination.is_symlink():
        raise ValueError("Refusing to overwrite a linked skill directory")
    stamp = destination / STAMP
    previous = json.loads(stamp.read_text("utf-8")) if stamp.is_file() else None
    if destination.exists():
        if previous is None or previous.get("skill") != "syntetic-core":
            raise FileExistsError("Existing skill is not managed by this installer")
        for relative, expected in previous["files"].items():
            target = (destination / relative).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("Invalid installed skill manifest path")
            if not target.is_file() or digest(target) != expected:
                raise ValueError(f"Installed skill has local changes: {relative}")
        for path in files:
            relative = path.relative_to(source).as_posix()
            if (destination / relative).exists() and relative not in previous["files"]:
                raise FileExistsError(f"Unmanaged file would be overwritten: {relative}")
    destination.mkdir(parents=True, exist_ok=True)
    owned: dict[str, str] = {}
    for path in files:
        relative = path.relative_to(source)
        target = destination / relative
        if target.is_symlink():
            raise ValueError("Refusing to overwrite linked skill files")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        owned[relative.as_posix()] = digest(target)
    pointer = destination / "runtime.json"
    pointer.write_text(json.dumps({"project_root": str(project.resolve())}, indent=2), "utf-8")
    owned["runtime.json"] = digest(pointer)
    stamp.write_text(json.dumps({"skill": "syntetic-core", "files": owned}, indent=2), "utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=["codex", "claude", "both"], default="both")
    parser.add_argument(
        "--codex-location", choices=["modern", "desktop", "both"], default="desktop"
    )
    parser.add_argument(
        "--user-home", type=Path, help="Override the home directory, e.g. for validation"
    )
    args = parser.parse_args()
    home = (args.user_home or Path.home()).expanduser().resolve()
    targets = []
    if args.agent in {"codex", "both"}:
        if args.codex_location in {"modern", "both"}:
            targets.append(home / ".agents/skills/syntetic-core")
        if args.codex_location in {"desktop", "both"}:
            codex_home = (
                home / ".codex"
                if args.user_home
                else Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
            )
            targets.append(codex_home / "skills/syntetic-core")
    if args.agent in {"claude", "both"}:
        claude_home = (
            home / ".claude"
            if args.user_home
            else Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
        )
        targets.append(claude_home / "skills/syntetic-core")
    for target in dict.fromkeys(targets):
        print(install_one(SOURCE, target, ROOT))


if __name__ == "__main__":
    main()
