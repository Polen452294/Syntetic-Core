"""Private working copy and recoverable file delta, always under ProfileLock.

This is application-level copy-on-write, not a kernel overlay filesystem.
Never publish files from a browser that has not closed successfully.
"""

import asyncio
import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

from syntetic_core._engine.errors import DiskSpaceLow, ProfileValidationError
from syntetic_core._engine.profile_storage import atomic_json

EXCLUDED = {
    "crashpad",
    "crashes",
    "minidumps",
    "runs",
}
TRANSIENT = {
    "singletonlock",
    "singletoncookie",
    "singletonsocket",
    "parent.lock",
    ".parentlock",
    "lock",
}


async def finish_io[T](function: Callable[..., T], *args: object) -> T:
    """Cancellation must not release the profile lock while its I/O still runs."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
        raise


def validate_ram_root(root: Path) -> None:
    if os.name != "posix" or not Path("/proc/mounts").exists():
        raise ProfileValidationError("RAM profiles require Linux tmpfs at /dev/shm")
    if not any(
        line.split()[1:3] == ["/dev/shm", "tmpfs"]
        for line in Path("/proc/mounts").read_text().splitlines()
    ):
        raise ProfileValidationError("/dev/shm must be a tmpfs mount")
    if not root.resolve().is_relative_to(Path("/dev/shm").resolve()):
        raise ProfileValidationError("RAM profile root must be inside /dev/shm")


def inventory(root: Path, limit: int) -> dict[str, str]:
    result: dict[str, str] = {}
    size = 0
    if root.is_symlink():
        raise ProfileValidationError("Profile symlinks are not supported")
    if not root.exists():
        return result
    for folder, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name.lower() not in EXCLUDED]
        for name in directories:
            if (Path(folder) / name).is_symlink():
                raise ProfileValidationError("Profile symlinks are not supported")
        for name in files:
            # LevelDB *.log files are WALs, not disposable browser logs.
            if name.lower() in TRANSIENT or name.lower() in {"chrome_debug.log", "debug.log"}:
                continue
            path = Path(folder) / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ProfileValidationError("Profile contains a non-regular file")
            size += info.st_size
            if size > limit:
                raise ProfileValidationError("Profile exceeds RAM staging limit")
            with path.open("rb") as source:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    source, "sha256"
                ).hexdigest()
    return result


def sync_directories(root: Path) -> None:
    if os.name != "nt":
        for folder, _, _ in os.walk(root, topdown=False):
            descriptor = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


class RamProfile:
    def __init__(self, profile: Path, root: Path, limit: int) -> None:
        self.base = profile.parent
        self.root, self.limit = root, limit
        self.journal = self.base.parent / f".{self.base.name}.delta"
        self.workspace: Path | None = None
        self.before: dict[str, str] = {}
        self.name = profile.name

    def recover(self) -> None:
        if self.journal.is_symlink():
            raise ProfileValidationError("Invalid delta journal")
        marker = self.journal / "manifest.json"
        if not marker.exists():
            if self.journal.exists():
                shutil.rmtree(self.journal)
            return
        manifest = json.loads(marker.read_text())
        # Validate all entries before writing any file. Journal is private worker state.
        entries = manifest["changed"] + manifest["deleted"]
        for name in entries:
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in name:
                raise ProfileValidationError("Invalid delta path")
            target = self.base / relative
            if not target.resolve().is_relative_to(self.base.resolve()):
                raise ProfileValidationError("Delta escapes profile")
        for name in manifest["changed"]:
            source = self.journal / "files" / name
            if (
                source.is_symlink()
                or not source.is_file()
                or not source.resolve().is_relative_to((self.journal / "files").resolve())
            ):
                raise ProfileValidationError("Invalid delta file")
            with source.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != manifest["hashes"][name]:
                    raise ProfileValidationError("Delta checksum mismatch")
        for name in manifest["changed"]:
            source = self.journal / "files" / name
            target = self.base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, filename = tempfile.mkstemp(prefix=".delta-", dir=target.parent)
            os.close(descriptor)
            temporary = Path(filename)
            try:
                shutil.copy2(source, temporary)
                with temporary.open("rb+") as handle:
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        for name in manifest["deleted"]:
            (self.base / name).unlink(missing_ok=True)
        # Flush directory entries before retiring the recovery journal.
        sync_directories(self.base)
        # Removing the marker first makes interrupted journal cleanup recognizable.
        marker.unlink()
        sync_directories(self.journal)
        shutil.rmtree(self.journal)

    def prepare(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.root).free < 2048 * 1024**2:
            raise DiskSpaceLow("RAM workspace has less than 2048 MiB free")
        self.before = inventory(self.base, self.limit)
        required = sum((self.base / name).stat().st_size for name in self.before)
        if shutil.disk_usage(self.root).free - required < 2048 * 1024**2:
            raise DiskSpaceLow("Profile restore would consume the 2048 MiB RAM reserve")
        self.workspace = Path(tempfile.mkdtemp(prefix="profile-", dir=self.root))
        destination = self.workspace / self.base.name
        destination.mkdir()
        for name in self.before:
            size = (self.base / name).stat().st_size
            if shutil.disk_usage(self.root).free - size < 2048 * 1024**2:
                raise DiskSpaceLow("Profile restore would consume the 2048 MiB RAM reserve")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.base / name, target)
        if shutil.disk_usage(self.root).free < 2048 * 1024**2:
            raise DiskSpaceLow("RAM workspace has less than 2048 MiB free after restore")
        (destination / self.name).mkdir(exist_ok=True)
        return destination / self.name

    def commit(self) -> None:
        assert self.workspace is not None
        current = self.workspace / self.base.name
        after = inventory(current, self.limit)
        changed = [name for name, digest in after.items() if self.before.get(name) != digest]
        deleted = sorted(self.before.keys() - after.keys())
        if not changed and not deleted:
            return
        self.journal.mkdir(mode=0o700, exist_ok=False)
        for name in changed:
            target = self.journal / "files" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current / name, target)
            with target.open("rb+") as handle:
                os.fsync(handle.fileno())
        sync_directories(self.journal)
        atomic_json(
            self.journal / "manifest.json",
            {
                "changed": changed,
                "deleted": deleted,
                "hashes": {name: after[name] for name in changed},
            },
        )
        self.recover()

    def cleanup(self) -> None:
        if self.workspace is not None:
            shutil.rmtree(self.workspace)
