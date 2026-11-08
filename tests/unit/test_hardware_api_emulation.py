import random

import pytest
from pydantic import ValidationError

from syntetic_core._engine.browser_runtime import (
    RuntimeCapability,
    RuntimeCompatibilityError,
    require_compatible,
)
from syntetic_core._engine.device_coherence import (
    bind_device_recipe,
    coherence_issues,
    device_memory_choices,
)
from syntetic_core._engine.device_emulation import randomize_device_emulation
from syntetic_core._engine.personas import (
    BrowserPersona,
    DeviceEmulation,
    EmulatedBattery,
    RuntimeConfig,
)
from tests.unit.test_device_coherence import coherent_manifest, phone_profile
from tests.unit.test_device_emulation import emulation_manifest


@pytest.mark.parametrize("memory", [True, 0, 3, 6, 12, 64, float("nan")])
def test_memory_rejects_non_approximate_or_invalid_values(memory):
    with pytest.raises(ValidationError):
        DeviceEmulation(seed=7, device_memory=memory)


@pytest.mark.parametrize(
    "patch",
    [
        {"level": -0.1},
        {"level": 1.1},
        {"level": float("nan")},
        {"level": True},
        {"charging": 1},
        {"charge_seconds": 0},
        {"discharge_seconds": float("inf")},
    ],
)
def test_battery_validates_level_state_and_rates(patch):
    with pytest.raises(ValidationError):
        EmulatedBattery.model_validate({"charging": False, "level": 0.5, **patch})


@pytest.mark.parametrize("engine", ["chromium", "webkit", "firefox"])
def test_generated_hardware_is_seeded_sealed_and_engine_appropriate(engine):
    worker = emulation_manifest()
    source = BrowserPersona(
        id="1",
        browser_engine=engine,
        runtime=RuntimeConfig(
            backend="camoufox" if engine == "firefox" else "playwright", target_os="windows"
        ),
    )
    capability = RuntimeCapability.model_validate(
        next(runtime for runtime in worker["runtimes"] if runtime["engine"] == engine)
    )
    first = source.model_copy(deep=True)
    second = source.model_copy(deep=True)
    randomize_device_emulation(first, capability, random.Random(72))
    randomize_device_emulation(second, capability, random.Random(72))
    assert first == second
    assert BrowserPersona.model_validate_json(first.sealed().model_dump_json()) == first.sealed()
    if engine == "chromium":
        assert first.emulation.device_memory in (4, 8, 16)
        assert 0.3 <= first.emulation.battery.level < 1
        runtime = next(r for r in worker["runtimes"] if r["engine"] == engine)
        runtime["parameters"].remove("emulation_battery")
        with pytest.raises(RuntimeCompatibilityError, match="emulation.battery"):
            require_compatible(first, worker)
    else:
        assert first.emulation.device_memory is None and first.emulation.battery is None
        first.emulation.device_memory = 8
        assert any("hardware" in issue for issue in coherence_issues(first))


@pytest.mark.parametrize("model,expected", [("Pixel 5a", 4), ("Pixel 6a", 4), ("Pixel 9 Pro", 8)])
def test_android_memory_matches_rounded_capped_model(model, expected):
    persona = phone_profile(model)
    persona.emulation = DeviceEmulation(seed=7, device_memory=2)
    capability = require_compatible(phone_profile(model), coherent_manifest())
    bind_device_recipe(persona, capability, random.Random(42))
    assert persona.emulation.device_memory == expected
    assert coherence_issues(persona) == []
    persona.emulation.device_memory = 2
    assert any("memory" in issue for issue in coherence_issues(persona))


def test_mac_memory_uses_recipe_and_respects_old_browser_limits():
    persona = BrowserPersona(id="1", runtime=RuntimeConfig(target_os="macos"))
    assert device_memory_choices(persona, "146.0.1") == (8,)
    assert device_memory_choices(persona, "147.0.1") == (8, 16)
    assert "device_memory" not in DeviceEmulation(seed=7).model_dump()
    assert "battery" not in DeviceEmulation(seed=7).model_dump()


async def test_unsupported_engines_do_not_advertise_hardware_emulation():
    from syntetic_core._engine.device_emulation_capabilities import verify_document_emulation

    persona = BrowserPersona(
        id="1", browser_engine="firefox", runtime=RuntimeConfig(backend="camoufox")
    )
    capability = require_compatible(persona, emulation_manifest())
    capability.parameters = []

    async def probe(candidate, label, check):
        assert candidate.emulation.device_memory is None
        assert candidate.emulation.battery is None

    await verify_document_emulation(persona, capability, probe, "http://127.0.0.1", [])
    assert "emulation_device_memory" not in capability.parameters
    assert "emulation_battery" not in capability.parameters
