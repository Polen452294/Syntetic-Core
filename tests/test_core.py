import asyncio
import json

import pytest
from pydantic import ValidationError

from syntetic_core import CoreSettings, ProfileLockedError, ProfileValidationError, SynteticCore
from syntetic_core._engine.profile_lock import ProfileLock
from tests.runtime_contract import manifest


@pytest.fixture
def core(tmp_path):
    result = SynteticCore(tmp_path)
    result._capabilities = manifest()
    return result


async def test_profile_roundtrip_and_immutable_checksum(core):
    persona = await core.create_profile("persistent")
    assert persona.fingerprint_id and persona.config_hash == persona.digest()
    assert persona.visit_state is None
    assert core.load_profile("persistent") == persona
    path = core.root / "persistent/profile.json"
    damaged = json.loads(path.read_text())
    damaged["timezone_id"] = "UTC"
    path.write_text(json.dumps(damaged))
    with pytest.raises(ProfileValidationError, match="checksum"):
        core.load_profile("persistent")


async def test_never_overwrite_existing_profile(core):
    original = await core.create_profile("one")
    with pytest.raises(FileExistsError):
        await core.create_profile("one")
    assert core.load_profile("one") == original


@pytest.mark.parametrize("name", ["../outside", "a/b", "a\\b", "", ".", "a" * 65])
async def test_profile_path_is_confined(core, name):
    with pytest.raises(ValueError):
        core.load_profile(name)


async def test_missing_proxy_fails_before_profile_creation(core):
    with pytest.raises(Exception, match="proxy is missing"):
        await core.create_profile("missing", proxy_id="undefined")
    assert not (core.root / "missing").exists()


async def test_capability_result_does_not_mutate_authority(core):
    received = await core.capabilities()
    received["runtimes"].clear()
    assert (await core.capabilities())["runtimes"]


async def test_profile_lock_excludes_other_owner(core):
    lock = ProfileLock(core.root / "held/browser-data", settings=core.settings)
    await lock.acquire_async()
    try:
        with pytest.raises(ProfileLockedError):
            await core.create_profile("held")
    finally:
        lock.release()


@pytest.mark.parametrize(
    "field",
    [
        "direct_transport",
        "distributed_workers",
        "profile_archive_enabled",
        "profile_storage_shared",
    ],
)
def test_settings_reject_unimplemented_or_bypassing_modes(field):
    with pytest.raises(ValidationError):
        CoreSettings(**{field: True})


async def test_cancelled_profile_write_finishes_before_releasing_lock(core, monkeypatch):
    import threading

    import syntetic_core.core as module

    entered, release = threading.Event(), threading.Event()
    original = module.atomic_json

    def slow_write(*args):
        entered.set()
        release.wait(timeout=5)
        original(*args)

    monkeypatch.setattr(module, "atomic_json", slow_write)
    task = asyncio.create_task(core.create_profile("cancelled"))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    competing = ProfileLock(core.root / "cancelled/browser-data", settings=core.settings)
    try:
        with pytest.raises(ProfileLockedError):
            competing.acquire()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert core.load_profile("cancelled").fingerprint_id
