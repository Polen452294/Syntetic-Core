"""Package reviewed sources and already-built distributions without local state."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".toml",
    ".lock",
    ".js",
    ".c",
    ".mp4",
    ".yml",
    ".yaml",
    ".typed",
    ".whl",
}


def main() -> None:
    candidates = [
        p
        for p in ROOT.iterdir()
        if p.is_file()
        and (p.suffix in SUFFIXES or p.name in {"MANIFEST.in", ".gitignore", ".env.example"})
    ]
    for name in ("src", "docs", "examples", "tests", "tools", "skills", ".github"):
        candidates.extend(
            p
            for p in (ROOT / name).rglob("*")
            if p.is_file()
            and p.suffix in SUFFIXES
            and not {"__pycache__", ".pytest_cache"}.intersection(p.parts)
        )
    candidates += [
        ROOT / "dist/syntetic_core-0.1.0-py3-none-any.whl",
        ROOT / "dist/syntetic_core-0.1.0.tar.gz",
    ]
    archive = ROOT / "dist/Syntetic-Core-0.1.0.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(set(candidates)):
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                raise ValueError("Release inputs must be local regular files")
            bundle.write(path, "Syntetic Core/" + path.relative_to(ROOT).as_posix())
    print(f"Packaged {len(set(candidates))} files into {archive.name}")
    skill_root = ROOT / "skills/syntetic-core"
    skill_archive = ROOT / "dist/syntetic-core-skill.zip"
    with ZipFile(skill_archive, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(skill_root.rglob("*")):
            if path.is_file() and path.suffix in SUFFIXES and "__pycache__" not in path.parts:
                if path.is_symlink():
                    raise ValueError("Skill release inputs must be regular files")
                bundle.write(path, "syntetic-core/" + path.relative_to(skill_root).as_posix())
    print(f"Packaged portable skill into {skill_archive.name}")


if __name__ == "__main__":
    main()
