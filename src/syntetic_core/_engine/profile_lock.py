"""Profile storage fence: Redis quorum leases for workers, local OS locks offline."""

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from syntetic_core._engine.errors import ProfileLockedError

if TYPE_CHECKING:
    from syntetic_core._engine.config import Settings


class ProfileLock:
    def __init__(self, profile_path: Path, *, settings: "Settings | None" = None) -> None:
        from syntetic_core._engine.config import get_settings

        settings = settings or get_settings()
        profile_path = profile_path.resolve()
        # Outside the deletable profile directory; never unlink the lock inode.
        self.path = profile_path.parent.parent / ".locks" / f"{profile_path.parent.name}.lock"
        self.handle: BinaryIO | None = None
        self.distributed = None

    @property
    def lost(self) -> bool:
        return self.distributed is not None and self.distributed.lost.is_set()

    async def acquire_async(self, on_lost: Callable[[], None] | None = None) -> None:
        if self.distributed is not None:
            owner, loop = asyncio.current_task(), asyncio.get_running_loop()

            def cancel_owner() -> None:
                if owner is not None:
                    loop.call_soon_threadsafe(owner.cancel)

            self.distributed.on_lost = on_lost or cancel_owner
        task = asyncio.create_task(asyncio.to_thread(self.acquire))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                await asyncio.to_thread(self.release)
            raise

    def acquire(self) -> None:
        if self.distributed is not None:
            self.distributed.acquire()
            return
        if self.handle is not None:
            raise ProfileLockedError("Profile lock is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except OSError:
            handle.close()
            raise ProfileLockedError("Persistent profile is already in use") from None
        self.handle = handle

    def release(self) -> None:
        if self.distributed is not None:
            self.distributed.release()
            return
        if self.handle is not None:
            self.handle.close()
            self.handle = None
