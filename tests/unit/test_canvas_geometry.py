from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from syntetic_core._engine.browser.canvas import canvas_identity, canvas_script, configure_canvas
from syntetic_core._engine.browser.experiment_replay import capture_identity, restore_identity
from syntetic_core._engine.browser.identity import read_json, write_json
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import (
    BrowserPersona,
    DeviceCoherence,
    DeviceEmulation,
    RuntimeConfig,
)


def test_canvas_seed_is_stable_profile_owned_and_uses_emulation_recipe():
    persona = BrowserPersona(id="1", fingerprint_id="a" * 32, emulation=DeviceEmulation(seed=7))
    original = canvas_identity(persona)
    assert original == canvas_identity(
        BrowserPersona.model_validate_json(persona.model_dump_json())
    )
    persona.locale = "ru-RU"
    persona.id = "2"
    assert canvas_identity(persona) == original  # fingerprint owns identity across replay profiles.
    persona.emulation.seed += 1
    assert canvas_identity(persona) != original
    persona.emulation.seed -= 1
    persona.coherence = DeviceCoherence(recipe_id="recipe-1")
    assert canvas_identity(persona) != original
    assert canvas_identity(BrowserPersona(id="1")) != canvas_identity(BrowserPersona(id="2"))
    assert "__CANVAS_CONFIG__" not in canvas_script(persona)


@pytest.mark.parametrize("native", [False, True])
async def test_canvas_installed_for_legacy_profiles_and_all_existing_frames(tmp_path: Path, native):
    persona = BrowserPersona(
        id="1",
        browser_engine="firefox" if native else "chromium",
        runtime=RuntimeConfig(backend="camoufox" if native else "playwright"),
    )
    frames = [SimpleNamespace(evaluate=AsyncMock()) for _ in range(2)]
    context = SimpleNamespace(add_init_script=AsyncMock(), pages=[SimpleNamespace(frames=frames)])
    path = tmp_path / "1/browser-data"
    await configure_canvas(context, persona, path)
    sources = [call.args[0] for call in context.add_init_script.await_args_list]
    assert sources == (
        [canvas_script(persona), "mw:" + canvas_script(persona)]
        if native
        else [canvas_script(persona)]
    )
    for frame in frames:
        assert [call.args[0] for call in frame.evaluate.await_args_list] == sources
    assert read_json(path.parent / "canvas-identity.json") == canvas_identity(persona)
    # Persistence/replay includes the canvas seed even without DeviceEmulation.
    saved = capture_identity(path, persona)
    target = tmp_path / "replay/browser-data"
    restore_identity(target, persona, saved)
    assert read_json(target.parent / "canvas-identity.json") == canvas_identity(persona)
    write_json(path.parent / "canvas-identity.json", {"version": 1, "seed": "changed"})
    context.add_init_script.reset_mock()
    with pytest.raises(ProfileValidationError, match="Canvas identity changed"):
        await configure_canvas(context, persona, path)
    context.add_init_script.assert_not_awaited()
