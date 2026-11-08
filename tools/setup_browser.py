"""Prepare the native runtime explicitly, including Unicode Windows path support."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def prepare_model() -> None:
    from camoufox.fpgen_model import PIN, PINNED_MTIME, ensure_fpgen_model, fpgen_data_dir
    from zstandard import ZstdDecompressor

    # indexed-zstd's Windows fopen does not handle Unicode installation paths.
    # fpgen officially supports decompressed files; prepare them at install time.
    ensure_fpgen_model()
    destination = fpgen_data_dir() / "values.dat"
    if destination.exists():
        return
    compressed = destination.with_suffix(".dat.zst")
    temporary = destination.with_suffix(".dat.tmp")
    try:
        with compressed.open("rb") as source, temporary.open("wb") as target:
            with ZstdDecompressor().stream_reader(source) as reader:
                shutil.copyfileobj(reader, target)
        with temporary.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != PIN["decompressed_sha256"]["values.dat"]:
            raise ValueError("Decompressed fingerprint model checksum differs from its pin")
        os.utime(temporary, (PINNED_MTIME, PINNED_MTIME))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def install_browser(destination: Path) -> None:
    from camoufox.pkgman import OS_NAME, RepoConfig, launch_path

    pin = json.loads(Path(__file__).with_name("browser-release.json").read_text())
    repo = next(repo for repo in RepoConfig.load_repos() if repo.name.lower() == "official")
    architecture = repo.get_arch()
    key = f"{OS_NAME}.{architecture}"
    digest = pin["sha256"].get(key)
    if not digest:
        raise ValueError(f"No pinned native browser for {key}")
    full_version = f"{pin['version']}-{pin['build']}"
    url = (
        f"https://github.com/daijro/camoufox/releases/download/v{full_version}/"
        f"camoufox-{full_version}-{key}.zip"
    )
    destination = destination.resolve()
    metadata = {"version": pin["version"], "build": pin["build"], "sha256": digest}
    version_file = destination / "version.json"
    if version_file.exists():
        current = json.loads(version_file.read_text())
        if any(current.get(key) != value for key, value in metadata.items()):
            raise ValueError(
                "Runtime directory contains another build; use a new install directory"
            )
    else:
        if destination.exists() and any(destination.iterdir()):
            raise ValueError("Refusing to overwrite a nonempty browser installation directory")
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile() as archive:
            for _attempt in range(3):
                archive.seek(0)
                archive.truncate()
                # A truncated CDN response must never be installed. Retry the
                # same pinned release; never accept or learn a different hash.
                with urllib.request.urlopen(url, timeout=60) as source:
                    shutil.copyfileobj(source, archive)
                archive.seek(0)
                if hashlib.file_digest(archive, "sha256").hexdigest() == digest:
                    break
            else:
                raise ValueError("Native browser archive checksum differs from its pin")
            archive.seek(0)
            with zipfile.ZipFile(archive) as bundle:
                for entry in bundle.infolist():
                    if not (destination / entry.filename).resolve().is_relative_to(destination):
                        raise ValueError("Browser archive path escapes its install directory")
                bundle.extractall(destination)
        if OS_NAME != "win":
            for entry in destination.rglob("*"):
                entry.chmod(
                    0o755 if entry.is_dir() or entry.suffix not in {".json", ".css"} else 0o644
                )
        version_file.write_text(json.dumps(metadata), encoding="utf-8")
    subprocess.run(
        [launch_path(destination), "--version"],
        check=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-data-only", action="store_true")
    parser.add_argument("--install-dir", type=Path, default=Path("build/native-browser"))
    args = parser.parse_args()
    # Runtime-only Docker stages copy this installer before application sources.
    # The final application receives the separately compiled native filter.
    if sys.platform == "linux" and (Path(__file__).resolve().parents[1] / "worker").is_dir():
        from syntetic_core._engine.browser.content_filter import build_webkit_filter
        from syntetic_core._engine.errors import ProfileValidationError

        try:
            build_webkit_filter()
        except ProfileValidationError as error:
            print(str(error), file=sys.stderr)
    prepare_model()
    if not args.prepare_data_only:
        install_browser(args.install_dir)
