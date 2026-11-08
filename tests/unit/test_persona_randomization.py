import random
from collections import Counter

import pytest
from pydantic import ValidationError

from syntetic_core._engine.browser_runtime import RuntimeCompatibilityError, require_compatible
from syntetic_core._engine.config import Settings
from syntetic_core._engine.persona_randomization import (
    DESKTOP_PRESETS,
    LOCALE_TIMEZONES,
    randomize_persona,
)
from syntetic_core._engine.personas import BrowserPersona
from tests.runtime_contract import manifest


def test_randomized_environments_are_diverse_coherent_and_supported() -> None:
    template = BrowserPersona(id="1")
    original = template.model_dump()
    environments = [
        randomize_persona(template, ["camoufox", "playwright"], rng=random.Random(seed))
        for seed in range(100)
    ]
    assert {p.runtime.backend for p in environments} == {"camoufox", "playwright"}
    assert {p.runtime.target_os for p in environments if p.runtime.backend == "camoufox"} == {
        "windows",
        "macos",
        "linux",
    }
    assert {p.runtime.target_os for p in environments if p.runtime.backend == "playwright"} == {
        "windows",
        "macos",
        "linux",
    }
    assert len({p.fingerprint_id for p in environments}) == len(environments)
    assert {(p.locale, p.timezone_id) for p in environments} == set(LOCALE_TIMEZONES)
    assert {p.device.model_dump_json() for p in environments} <= {
        preset.device().model_dump_json() for preset in DESKTOP_PRESETS
    }
    for persona in environments:
        require_compatible(persona, manifest())
        persona.sealed().verify_snapshot(1)
        assert persona.proxy_id is None
        assert persona.behavior.enabled == template.behavior.enabled
        assert persona.display is not None
        assert not persona.device.mobile and not persona.device.touch
    assert template.model_dump() == original
    assert len({p.device.model_dump_json() for p in environments}) > 50
    assert len({p.behavior.model_dump_json() for p in environments}) > 90


@pytest.mark.parametrize("backend", ["camoufox", "playwright"])
def test_runtime_selection_respects_worker_capabilities(backend: str) -> None:
    capabilities = manifest()
    for runtime in capabilities["runtimes"]:
        runtime["installed"] = runtime["backend"] == backend
    persona = randomize_persona(
        BrowserPersona(id="1"),
        ["camoufox", "playwright"],
        worker_capabilities=capabilities,
        rng=random.Random(0),
    )
    assert persona.runtime.backend == backend
    require_compatible(persona, capabilities)


@pytest.mark.parametrize("backend", ["camoufox", "playwright"])
def test_os_distribution_is_79_percent_windows_16_macos_5_linux(backend) -> None:
    rng = random.Random(2026)
    template = BrowserPersona(id="1")
    counts = Counter(
        randomize_persona(template, [backend], rng=rng).runtime.target_os for _ in range(4000)
    )
    assert 0.04 <= counts["linux"] / 4000 <= 0.06
    assert 0.77 <= counts["windows"] / 4000 <= 0.81
    assert 0.14 <= counts["macos"] / 4000 <= 0.18


@pytest.mark.parametrize("backend", ["camoufox", "playwright"])
def test_generated_macos_profiles_use_retina_geometry(backend) -> None:
    profiles = [
        randomize_persona(BrowserPersona(id="1"), [backend], rng=random.Random(seed))
        for seed in range(100)
    ]
    macs = [persona for persona in profiles if persona.runtime.target_os == "macos"]
    assert macs
    assert all(persona.device.device_scale_factor == 2 for persona in macs)


def test_display_catalog_has_valid_geometry_and_scale_combinations() -> None:
    assert len(DESKTOP_PRESETS) >= 150
    assert len(set(DESKTOP_PRESETS)) == len(DESKTOP_PRESETS)
    assert {preset.dpr for preset in DESKTOP_PRESETS} == {1, 1.25, 1.5, 1.75, 2}
    for preset in DESKTOP_PRESETS:
        assert 800 <= preset.viewport_width <= preset.screen_width
        assert 480 <= preset.viewport_height <= preset.screen_height
        assert preset.screen_height - preset.viewport_height >= 86


def test_old_chromium_worker_does_not_receive_new_emulation_fields() -> None:
    capabilities = manifest()
    for runtime in capabilities["runtimes"]:
        runtime["parameters"].remove("target_os")
        runtime["parameters"].remove("display_preferences")
    persona = randomize_persona(
        BrowserPersona(id="1"), ["playwright"], worker_capabilities=capabilities
    )
    assert persona.runtime.target_os is None
    assert persona.chromium is None
    assert persona.display is None
    require_compatible(persona, capabilities)
    persona.runtime.target_os = capabilities["operating_system"]
    with pytest.raises(RuntimeCompatibilityError, match="runtime.target_os"):
        require_compatible(persona, capabilities)


def test_no_compatible_runtime_fails_instead_of_falling_back() -> None:
    capabilities = manifest()
    for runtime in capabilities["runtimes"]:
        runtime["smoke_test"] = "failed"
    with pytest.raises(RuntimeCompatibilityError, match="profile_randomization.runtimes"):
        randomize_persona(
            BrowserPersona(id="1"), ["camoufox", "playwright"], worker_capabilities=capabilities
        )
    with pytest.raises(RuntimeCompatibilityError):
        randomize_persona(BrowserPersona(id="1"), ["camoufox"], worker_capabilities={})


def test_old_worker_without_os_selection_retains_its_host_os() -> None:
    capabilities = manifest()
    for runtime in capabilities["runtimes"]:
        if "target_os" in runtime["parameters"]:
            runtime["parameters"].remove("target_os")
    persona = randomize_persona(
        BrowserPersona(id="1"), ["camoufox"], worker_capabilities=capabilities
    )
    assert persona.runtime.target_os == capabilities["operating_system"]
    require_compatible(persona, capabilities)
    persona.runtime.target_os = "windows"
    with pytest.raises(RuntimeCompatibilityError, match="runtime.target_os"):
        require_compatible(persona, capabilities)


def test_randomization_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNTETIC_CORE_PROFILE_RANDOMIZATION__ENABLED", "false")
    monkeypatch.setenv("SYNTETIC_CORE_PROFILE_RANDOMIZATION__RUNTIMES", '["playwright"]')
    settings = Settings()
    assert not settings.profile_randomization.enabled
    assert settings.profile_randomization.runtimes == ["playwright"]
    monkeypatch.setenv("SYNTETIC_CORE_PROFILE_RANDOMIZATION__RUNTIMES", "[]")
    with pytest.raises(ValidationError):
        Settings()
