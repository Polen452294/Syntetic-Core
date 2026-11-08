import random
from collections import Counter

import pytest
from pydantic import ValidationError

from syntetic_core._engine.browser.mobile import ios_user_agent
from syntetic_core._engine.browser_runtime import RuntimeCompatibilityError, require_compatible
from syntetic_core._engine.config import ProfileRandomizationConfig
from syntetic_core._engine.persona_randomization import randomize_persona
from syntetic_core._engine.personas import (
    BrowserPersona,
    DeviceProfileResolver,
    PersonaValidator,
    PhoneIdentity,
)
from syntetic_core._engine.phone_personas import PHONE_MODELS, PHONE_PRESETS, randomize_phone
from tests.runtime_contract import manifest


def test_phone_catalog_has_hundreds_of_distinct_valid_presets_per_family() -> None:
    assert len(PHONE_MODELS) >= 50
    assert len({model.model for model in PHONE_MODELS}) == len(PHONE_MODELS)
    assert len({preset.key for preset in PHONE_PRESETS}) == len(PHONE_PRESETS)
    counts = Counter(preset.phone.family for preset in PHONE_PRESETS)
    assert min(counts.values()) >= 300
    identities = set()
    resolver = DeviceProfileResolver()
    for preset in PHONE_PRESETS:
        persona = randomize_phone(BrowserPersona(id="1"), preset.phone.family, random.Random(1))
        persona.device = preset.device()
        persona.phone = PhoneIdentity(
            family=preset.phone.family,
            model=preset.phone.model,
            os_version=preset.os_version,
            orientation=preset.orientation,
            preset_id=preset.key,
        )
        if persona.chromium:
            persona.chromium.platform_version = preset.os_version
        device = resolver.resolve(persona.device, {})
        assert PersonaValidator().validate(persona, device).valid, preset.key
        assert persona.device.viewport["height"] < persona.device.screen["height"]
        assert persona.device.device_scale_factor == preset.phone.dpr
        identities.add(
            (
                preset.phone.model,
                preset.os_version,
                preset.orientation,
                persona.device.model_dump_json(),
            )
        )
        if preset.phone.model.startswith("Pixel 10"):
            assert int(preset.os_version.split(".")[0]) >= 16
        if preset.phone.model in {"Pixel 5", "Pixel 5a"}:
            assert int(preset.os_version.split(".")[0]) <= 14
        if preset.phone.model.startswith("iPhone 17") or preset.phone.model == "iPhone Air":
            assert int(preset.os_version.split(".")[0]) >= 26
        if preset.phone.model == "iPhone 17e":
            assert preset.os_version == "26.3"
    # IDs and presentation labels alone must not inflate the preset count.
    assert len(identities) == len(PHONE_PRESETS)


def test_extra_os_versions_do_not_make_a_phone_model_more_likely() -> None:
    rng = random.Random(2026)
    counts = Counter(
        randomize_phone(BrowserPersona(id="1"), "android", rng).phone.model for _ in range(6000)
    )
    # Pixel 6 has four OS versions, Pixel 10 only one, but equal model weight.
    assert 0.04 < counts["Pixel 6"] / 6000 < 0.06
    assert 0.04 < counts["Pixel 10"] / 6000 < 0.06


def test_phone_timing_is_mobile_specific_and_disabled_behavior_is_preserved() -> None:
    template = BrowserPersona(id="1")
    template.behavior.seed = 42
    template.runtime.channel = "chrome"
    template.runtime.fonts = ["Arial"]
    template.runtime.webgl = {"vendor": "desktop", "renderer": "desktop"}
    for seed in range(50):
        phone = randomize_phone(template, "android", random.Random(seed))
        assert phone.behavior.seed == 42
        assert 55 <= phone.behavior.key_min_ms <= 160
        assert phone.behavior.key_min_ms < phone.behavior.key_max_ms <= 421
        assert phone.behavior.pause_min_ms < phone.behavior.pause_max_ms <= 1740
        assert 3 <= phone.behavior.scroll_steps <= 8
        assert phone.runtime.channel is phone.runtime.fonts is phone.runtime.webgl is None
        assert phone.phone.hardware_concurrency == 8
    template.behavior.enabled = False
    assert randomize_phone(template, "ios", random.Random(1)).behavior == template.behavior


@pytest.mark.parametrize(
    "version,os_token", [("18.6", "18_6"), ("18.7", "18_7"), ("26.0", "18_6"), ("26.3", "18_7")]
)
def test_safari_ua_uses_the_frozen_os_token_for_ios_26(version, os_token) -> None:
    persona = BrowserPersona(
        id="1",
        phone=PhoneIdentity(
            family="ios", model="iPhone", os_version=version, preset_id="new-preset"
        ),
    )
    ua = ios_user_agent(persona)
    assert f"CPU iPhone OS {os_token} like Mac OS X" in ua
    assert f"Version/{version} Mobile/" in ua


def test_legacy_phone_identity_keeps_its_serialized_fields() -> None:
    legacy = {
        "family": "ios",
        "model": "iPhone 12",
        "os_version": "26.0",
        "orientation": "portrait",
    }
    assert PhoneIdentity.model_validate(legacy).model_dump() == legacy
    persona = BrowserPersona(id="1", phone=PhoneIdentity.model_validate(legacy))
    assert "CPU iPhone OS 26_0 like Mac OS X" in ios_user_agent(persona)


def test_phone_validation_rejects_screen_orientation_conflicts_and_unsupported_cpu() -> None:
    persona = randomize_phone(BrowserPersona(id="1"), "ios", random.Random(1))
    persona.phone.hardware_concurrency = 6
    device = DeviceProfileResolver().resolve(persona.device, {})
    assert not PersonaValidator().validate(persona, device).valid
    persona.phone.hardware_concurrency = None
    persona.phone.orientation = (
        "landscape" if persona.phone.orientation == "portrait" else "portrait"
    )
    assert not PersonaValidator().validate(persona, device).valid


@pytest.mark.parametrize("family,engine", [("android", "chromium"), ("ios", "webkit")])
def test_phone_personas_are_coherent_serializable_and_supported(family, engine) -> None:
    template = BrowserPersona(id="1")
    profiles = [
        randomize_persona(
            template,
            ["playwright"],
            device_family=family,
            worker_capabilities=manifest(),
            rng=random.Random(seed),
        )
        for seed in range(100)
    ]
    assert len({p.phone.model for p in profiles}) >= 5
    assert {p.phone.orientation for p in profiles} == {"portrait", "landscape"}
    assert len({p.device.model_dump_json() for p in profiles}) > 10
    for profile in profiles:
        require_compatible(profile, manifest())
        assert profile.runtime.target_os == family
        assert profile.browser_engine == engine
        assert profile.device.mobile and profile.device.touch
        assert profile.device.source == "custom" and profile.device.preset is None
        assert all(
            profile.device.viewport[k] <= profile.device.screen[k] for k in ("width", "height")
        )
        snapshot = profile.sealed()
        restored = BrowserPersona.model_validate_json(snapshot.model_dump_json())
        assert restored == snapshot
        restored.verify_snapshot(1)
    assert template.phone is None and not template.device.mobile


def test_default_device_mix_is_70_percent_mobile_with_android_ios_60_40() -> None:
    weights = ProfileRandomizationConfig().device_weights
    assert weights == {"desktop": 30, "android": 42, "ios": 28}
    rng = random.Random(2026)
    counts = Counter()
    for _ in range(4000):
        persona = randomize_persona(
            BrowserPersona(id="1"),
            ["camoufox", "playwright"],
            device_weights=weights,
            worker_capabilities=manifest(),
            rng=rng,
        )
        counts[persona.phone.family if persona.phone else "desktop"] += 1
    mobile_count = counts["android"] + counts["ios"]
    assert 0.28 < counts["desktop"] / 4000 < 0.32
    assert 0.68 < mobile_count / 4000 < 0.72
    assert 0.40 < counts["android"] / 4000 < 0.44
    assert 0.26 < counts["ios"] / 4000 < 0.30
    assert 0.58 < counts["android"] / mobile_count < 0.62
    assert 0.38 < counts["ios"] / mobile_count < 0.42


def test_workers_without_ios_support_do_not_receive_iphone_profiles() -> None:
    capabilities = manifest()
    capabilities["runtimes"] = [r for r in capabilities["runtimes"] if r["engine"] != "webkit"]
    for seed in range(50):
        persona = randomize_persona(
            BrowserPersona(id="1"),
            ["playwright"],
            device_weights=ProfileRandomizationConfig().device_weights,
            worker_capabilities=capabilities,
            rng=random.Random(seed),
        )
        assert persona.phone is None or persona.phone.family == "android"
        require_compatible(persona, capabilities)
    with pytest.raises(RuntimeCompatibilityError, match="device_family"):
        randomize_persona(
            BrowserPersona(id="1"),
            ["playwright"],
            device_family="ios",
            worker_capabilities=capabilities,
        )


def test_device_mix_must_sum_to_100() -> None:
    for weights in ({"desktop": 90, "ios": 15}, {"desktop": -1, "android": 101}, {}):
        with pytest.raises(ValidationError):
            ProfileRandomizationConfig(device_weights=weights)
