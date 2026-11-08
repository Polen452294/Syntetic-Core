import math
import random
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from syntetic_core._engine.browser.sensors import moving_sensor_readings
from syntetic_core._engine.browser.visit_state import prepare_visit_state
from syntetic_core._engine.browser_runtime import RuntimeWindowInsets, require_compatible
from syntetic_core._engine.persona_randomization import randomize_persona
from syntetic_core._engine.personas import (
    BrowserPersona,
    SensorMotion,
    StationarySensors,
    VisitState,
)
from tests.runtime_contract import manifest


def extended_manifest():
    value = manifest()
    for runtime in value["runtimes"]:
        runtime["parameters"] += ["visit_state"]
        if "geolocation" not in runtime["parameters"]:
            runtime["parameters"].append("geolocation")
        if runtime["engine"] == "chromium":
            runtime["parameters"] += ["sensor_motion", "chromium_experience", "foldable"]
        elif runtime["engine"] == "webkit":
            runtime["parameters"] += ["tablet_ios"]
        else:
            runtime["parameters"] += ["native_desktop"]
            runtime["window_insets"] = RuntimeWindowInsets(
                width=16, height=175, config_height_offset=85
            ).model_dump()
    return value


@pytest.mark.parametrize("family", ["desktop", "ios", "android"])
def test_random_environment_is_valid_coherent_and_sealed(family):
    worker = extended_manifest()
    forms, visits = set(), set()
    for seed in range(150):
        persona = randomize_persona(
            BrowserPersona(id="1"),
            ["playwright", "camoufox"],
            worker_capabilities=worker,
            device_family=family,
            rng=random.Random(seed),
        )
        require_compatible(persona, worker)
        assert persona.geolocation is not None
        assert persona.visit_state is not None
        visits.add((persona.visit_state.visitor, persona.visit_state.cache))
        if persona.phone:
            forms.add(persona.phone.form_factor)
        if persona.native_desktop:
            d = persona.native_desktop
            assert persona.device.viewport["height"] + 86 <= d.outer_height <= d.avail_height
            assert d.avail_top + d.avail_height <= persona.device.screen["height"]
        restored = BrowserPersona.model_validate_json(persona.sealed().model_dump_json())
        restored.verify_snapshot(1)
    assert visits == {("new", "cold")}
    if family == "ios":
        assert forms == {"phone", "tablet"}
    if family == "android":
        assert forms == {"phone", "foldable"}


def test_motion_is_periodic_with_consistent_gravity_and_angular_velocity():
    pose = StationarySensors(roll=5, pitch=45, yaw=270)
    motion = SensorMotion(amplitude=2, period_seconds=8)
    first = moving_sensor_readings(pose, motion, 0)
    for seconds in [0.2, 1, 4, 8, 12]:
        actual = moving_sensor_readings(pose, motion, seconds)
        gravity = actual["gravity"]["xyz"]
        assert math.sqrt(sum(v * v for v in gravity.values())) == pytest.approx(9.80665)
        assert actual["accelerometer"]["xyz"] == gravity
        assert all(v == 0 for v in actual["linear-acceleration"]["xyz"].values())
        assert sum(
            v * v for v in actual["relative-orientation"]["quaternion"].values()
        ) == pytest.approx(1)
    periodic = moving_sensor_readings(pose, motion, 8)
    for kind, reading in first.items():
        assert list(next(iter(reading.values())).values()) == pytest.approx(
            list(next(iter(periodic[kind].values())).values())
        )


def test_legacy_identity_payload_does_not_gain_extension_fields():
    persona = BrowserPersona(id="1")
    data = persona.model_dump()
    assert "native_desktop" not in data and "visit_state" not in data
    with pytest.raises(ValidationError):
        VisitState(visitor="new", cache="warm")


async def test_preparation_never_seeds_a_different_site():
    from syntetic_core._engine.config import Settings
    from syntetic_core._engine.personas import SitePreferences

    context = AsyncMock()
    context.cookies.return_value = []
    persona = BrowserPersona(
        id="1",
        visit_state=VisitState(
            visitor="new",
            cache="cold",
            preferences=[SitePreferences(origin="https://other.example", local_storage={"x": "y"})],
        ),
    )
    result = await prepare_visit_state(
        context, persona, "http://localhost", Settings(_env_file=None), 0
    )
    assert result["primer_visits"] == 0
    context.add_cookies.assert_not_called()
    context.add_init_script.assert_not_called()
    context.new_page.assert_not_called()
    context.route.assert_not_awaited()
