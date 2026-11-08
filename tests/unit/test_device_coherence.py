import random

import pytest

from syntetic_core._engine.browser_runtime import RuntimeCapability
from syntetic_core._engine.device_coherence import (
    ANDROID_GPUS,
    bind_device_recipe,
    coherence_issues,
)
from syntetic_core._engine.device_emulation import randomize_device_emulation
from syntetic_core._engine.persona_randomization import randomize_persona
from syntetic_core._engine.personas import (
    BrowserPersona,
    ChromiumIdentity,
    PhoneIdentity,
    RuntimeConfig,
)
from syntetic_core._engine.phone_personas import PRESETS_BY_MODEL
from tests.runtime_contract import manifest
from tests.unit.test_device_emulation import emulation_manifest
from tests.unit.test_environment_extensions import extended_manifest


def phone_profile(model):
    preset = PRESETS_BY_MODEL[model][0]
    family = preset.phone.family
    return BrowserPersona(
        id="1",
        device=preset.device(),
        browser_engine="chromium" if family == "android" else "webkit",
        runtime=RuntimeConfig(target_os=family),
        phone=PhoneIdentity(
            family=family,
            model=model,
            os_version=preset.os_version,
            form_factor=preset.phone.form_factor,
            preset_id=preset.key,
            hardware_concurrency=8 if family == "android" else None,
        ),
        chromium=ChromiumIdentity(platform_version=preset.os_version)
        if family == "android"
        else None,
    )


def emulation_capability(persona):
    data = next(r for r in manifest()["runtimes"] if r["engine"] == persona.browser_engine)
    data["parameters"] += ["emulation_webgl", "emulation_hardware_concurrency", "emulation_media"]
    return RuntimeCapability.model_validate(data)


@pytest.mark.parametrize(
    "model,renderer",
    [
        ("SM-A556B", "Xclipse 530"),
        ("SM-F956U", "Adreno (TM) 750"),
        ("SM-F966U", "Adreno (TM) 830"),
    ],
)
def test_phone_gpu_follows_exact_model_instead_of_family_prefix(model, renderer):
    persona = phone_profile(model)
    randomize_device_emulation(persona, emulation_capability(persona), random.Random(1))
    assert persona.emulation.webgl.renderer == renderer


def test_ipad_mini_never_reports_more_cpu_cores_than_its_six_core_chip():
    for seed in range(30):
        persona = phone_profile("iPad mini 6")
        randomize_device_emulation(persona, emulation_capability(persona), random.Random(seed))
        assert persona.emulation.hardware_concurrency <= 6


def coherent_manifest():
    data = extended_manifest()
    for runtime in data["runtimes"]:
        source = next(
            r for r in emulation_manifest()["runtimes"] if r["engine"] == runtime["engine"]
        )
        runtime["parameters"] += source["parameters"] + ["device_coherence"]
        runtime["parameters"] = list(dict.fromkeys(runtime["parameters"]))
    return data


@pytest.mark.parametrize("family", ["desktop", "android", "ios"])
def test_generated_recipes_remain_valid_after_round_trip_and_sealing(family):
    from syntetic_core._engine.browser_runtime import require_compatible

    worker = coherent_manifest()
    recipes = set()
    for seed in range(500):
        persona = randomize_persona(
            BrowserPersona(id="1"),
            ["playwright", "camoufox"],
            device_family=family,
            worker_capabilities=worker,
            rng=random.Random(seed),
        )
        assert persona.coherence is not None
        assert coherence_issues(persona) == []
        require_compatible(persona, worker)
        restored = BrowserPersona.model_validate_json(persona.sealed().model_dump_json())
        restored.verify_snapshot(1)
        assert coherence_issues(restored) == []
        recipes.add(persona.coherence.recipe_id)
    assert len(recipes) > 5


def test_exact_android_mapping_covers_every_supported_android_model():
    from syntetic_core._engine.phone_personas import PHONE_MODELS

    assert set(ANDROID_GPUS) == {p.model for p in PHONE_MODELS if p.family == "android"}


@pytest.mark.parametrize(
    "change",
    [
        lambda p: setattr(p.phone, "model", "iPhone 11"),
        lambda p: setattr(p.phone, "os_version", "1.0"),
        lambda p: setattr(p.phone, "orientation", "landscape"),
        lambda p: setattr(p.device, "device_scale_factor", 3),
        lambda p: p.device.screen.update(width=999),
        lambda p: setattr(p.emulation, "hardware_concurrency", 8),
        lambda p: setattr(p.emulation.webgl, "renderer", "NVIDIA Desktop GPU"),
    ],
)
def test_incompatible_changes_are_rejected_before_browser_launch(change):
    from syntetic_core._engine.personas import DeviceProfileResolver, PersonaValidator

    persona = phone_profile("iPad mini 6")
    worker = coherent_manifest()
    cap = RuntimeCapability.model_validate(worker["runtimes"][2])
    randomize_device_emulation(persona, cap, random.Random(7))
    bind_device_recipe(persona, cap, random.Random(7))
    change(persona)
    result = PersonaValidator().validate(
        persona, DeviceProfileResolver().resolve(persona.device, {}), "strict"
    )
    assert not result.valid
    assert any("coherence." in issue for issue in result.errors)


def test_mac_gpu_cpu_and_ch_architecture_are_selected_as_one_recipe():
    from syntetic_core._engine.browser.chromium import identity_override

    persona = BrowserPersona(
        id="1",
        runtime=RuntimeConfig(target_os="macos"),
        chromium=ChromiumIdentity(platform_version="14.7.0", hardware_concurrency=16),
    )
    persona.device.device_scale_factor = 2
    runtime = RuntimeCapability.model_validate(coherent_manifest()["runtimes"][0])
    randomize_device_emulation(persona, runtime, random.Random(1))
    bind_device_recipe(persona, runtime, random.Random(1))
    assert persona.chromium.hardware_concurrency == 8
    assert persona.emulation.hardware_concurrency == 8
    assert "ANGLE Metal Renderer: Apple M" in persona.emulation.webgl.renderer
    assert identity_override(persona, "123.0.0.0")["userAgentMetadata"]["architecture"] == "arm"
    persona.chromium.architecture = "x86"
    assert any("architecture" in issue for issue in coherence_issues(persona))


def test_legacy_hash_and_old_worker_keep_their_original_contract():
    persona = BrowserPersona(id="1")
    assert "coherence" not in persona.model_dump()
    assert "architecture" not in ChromiumIdentity().model_dump()
    randomize_device_emulation(persona, emulation_capability(persona), random.Random(1))
    runtime = RuntimeCapability.model_validate(manifest()["runtimes"][0])
    bind_device_recipe(persona, runtime, random.Random(1))
    assert persona.coherence is None


def test_large_physical_display_excludes_integrated_gpu_recipes():
    persona = BrowserPersona(
        id="1",
        runtime=RuntimeConfig(target_os="windows"),
        chromium=ChromiumIdentity(hardware_concurrency=4),
    )
    persona.device.screen = {"width": 3840, "height": 2160}
    persona.device.device_scale_factor = 2
    cap = RuntimeCapability.model_validate(coherent_manifest()["runtimes"][0])
    for seed in range(30):
        current = persona.model_copy(deep=True)
        randomize_device_emulation(current, cap, random.Random(seed))
        bind_device_recipe(current, cap, random.Random(seed))
        assert "uhd630" not in current.coherence.recipe_id
        assert coherence_issues(current) == []


def test_unknown_phone_has_no_fabricated_gpu_fallback():
    from syntetic_core._engine.errors import ProfileValidationError

    persona = phone_profile("SM-A556B")
    persona.phone.model = "Unknown Android Model"
    with pytest.raises(ProfileValidationError, match="unknown device model"):
        randomize_device_emulation(persona, emulation_capability(persona), random.Random(1))


def test_old_impossible_mobile_count_is_rejected_without_rewriting_its_identity():
    persona = phone_profile("iPad mini 6")
    randomize_device_emulation(persona, emulation_capability(persona), random.Random(1))
    persona.emulation.hardware_concurrency = 8
    original = persona.model_dump_json()
    assert any("coherence.cpu" in issue for issue in coherence_issues(persona))
    assert persona.model_dump_json() == original


def test_malformed_display_is_a_validation_error_not_a_key_error():
    persona = BrowserPersona(
        id="1",
        runtime=RuntimeConfig(target_os="windows"),
        chromium=ChromiumIdentity(hardware_concurrency=8),
    )
    cap = RuntimeCapability.model_validate(coherent_manifest()["runtimes"][0])
    randomize_device_emulation(persona, cap, random.Random(1))
    bind_device_recipe(persona, cap, random.Random(1))
    persona.device.screen = {}
    assert any("coherence.screen" in issue for issue in coherence_issues(persona))
