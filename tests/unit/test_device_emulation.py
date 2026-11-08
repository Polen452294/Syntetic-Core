import random

import pytest
from pydantic import ValidationError

from syntetic_core._engine.browser.device_emulation import emulation_headers, emulation_script
from syntetic_core._engine.browser_runtime import (
    RuntimeCapability,
    RuntimeCompatibilityError,
    require_compatible,
)
from syntetic_core._engine.device_emulation import EMULATION_FIELDS, randomize_device_emulation
from syntetic_core._engine.persona_randomization import randomize_persona
from syntetic_core._engine.personas import (
    BrowserPersona,
    DeviceEmulation,
    EmulatedPrivacy,
    EmulatedWebGL,
    NativeAudioIdentity,
)
from tests.runtime_contract import manifest


def emulation_manifest():
    worker = manifest()
    for runtime in worker["runtimes"]:
        runtime["parameters"] += ["emulation_" + field for field in EMULATION_FIELDS]
    return worker


@pytest.mark.parametrize("family", ["desktop", "android", "ios"])
def test_generated_parameters_are_stable_coherent_and_hashed(family):
    worker = emulation_manifest()
    seeds = set()
    for seed in range(30):
        persona = randomize_persona(
            BrowserPersona(id="1"),
            ["playwright"],
            device_family=family,
            worker_capabilities=worker,
            rng=random.Random(seed),
        )
        assert persona.emulation is not None
        seeds.add(persona.emulation.seed)
        require_compatible(persona, worker)
        sealed = persona.sealed()
        restored = BrowserPersona.model_validate_json(sealed.model_dump_json())
        restored.verify_snapshot(1)
        assert restored == sealed
        if family == "android":
            assert persona.emulation.hardware_concurrency == 8
            assert persona.chromium.sensors is not None
            assert persona.emulation.sensors is None
        assert persona.digest() != persona.model_copy(update={"emulation": None}).digest()
    assert len(seeds) == 30


def test_legacy_profiles_and_worker_contract_remain_compatible():
    persona = BrowserPersona(id="1")
    assert "emulation" not in persona.model_dump()
    runtime = RuntimeCapability.model_validate(manifest()["runtimes"][0])
    randomize_device_emulation(persona, runtime, random.Random(1))
    assert persona.emulation is None
    persona.emulation = DeviceEmulation(seed=1, webgl=EmulatedWebGL(vendor="a", renderer="b"))
    with pytest.raises(RuntimeCompatibilityError, match="emulation.webgl"):
        require_compatible(persona, manifest())


def test_emulation_validation_and_safe_serialization():
    with pytest.raises(ValidationError):
        DeviceEmulation(seed=0)
    with pytest.raises(ValidationError):
        DeviceEmulation(seed=1, fonts=["Arial", "Arial"])
    with pytest.raises(ValidationError):
        DeviceEmulation(seed=1, hardware_concurrency=True)
    persona = BrowserPersona(
        id="1",
        emulation=DeviceEmulation(
            seed=7,
            fonts=['Font "quoted" </script>'],
            privacy=EmulatedPrivacy(do_not_track=True, global_privacy_control=True),
            audio=NativeAudioIdentity(sample_rate=48000, buffer_frames=256),
        ),
    )
    assert emulation_headers(persona) == {"DNT": "1", "Sec-GPC": "1"}
    script = emulation_script(persona)
    assert "__DEVICE_EMULATION_CONFIG__" not in script
    assert 'Font \\"quoted\\" </script>' in script


async def test_worker_retains_independently_verified_features_when_one_fails():
    from syntetic_core._engine.device_emulation_capabilities import verify_document_emulation

    runtime = RuntimeCapability.model_validate(manifest()["runtimes"][0])

    async def probe(persona, label, check):
        if persona.emulation.audio is not None:
            raise RuntimeError("No audio subsystem")

    await verify_document_emulation(BrowserPersona(id="1"), runtime, probe, "http://127.0.0.1", [])
    assert "emulation_audio" not in runtime.parameters
    assert "emulation_webgl" in runtime.parameters
    assert "emulation_fonts" in runtime.parameters
    assert "emulation_privacy" in runtime.parameters
    assert "emulation_sensors" not in runtime.parameters  # Existing native sensors win.
    assert any("audio" in text for text in runtime.limitations)
