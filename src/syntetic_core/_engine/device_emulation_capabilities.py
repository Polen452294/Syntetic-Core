"""Accept JS emulation only after real document observations on this worker."""

import random
from collections.abc import Awaitable, Callable
from typing import Any

from syntetic_core._engine.browser.device_emulation import validate_device_emulation
from syntetic_core._engine.browser.sensors import readings_match
from syntetic_core._engine.browser_runtime import RuntimeCapability
from syntetic_core._engine.device_emulation import EMULATION_FIELDS, randomize_device_emulation
from syntetic_core._engine.personas import BrowserPersona, PermissionConfig


async def verify_document_emulation(
    persona: BrowserPersona,
    capability: RuntimeCapability,
    probe: Callable[[BrowserPersona, str, Any], Awaitable[None]],
    url: str,
    headers: list[dict[str, str]],
) -> None:
    fields = (
        ["sensors", "hardware_concurrency"]
        if persona.runtime.backend == "camoufox"
        else [field for field in EMULATION_FIELDS if field != "hardware_concurrency"]
    )
    if persona.browser_engine == "webkit":
        fields.append("hardware_concurrency")
    if persona.browser_engine != "chromium":
        fields = [field for field in fields if field not in {"device_memory", "battery"}]
    if persona.runtime.backend == "camoufox":
        for native_field, emulated_fields in (
            ("native_desktop", ["privacy"]),
            ("native_audio", ["audio"]),
            ("native_media", ["media", "voices"]),
        ):
            if native_field not in capability.parameters:
                fields.extend(emulated_fields)
    if persona.browser_engine == "chromium" and "virtual_sensors" in capability.parameters:
        fields.remove("sensors")

    async def attempt(selected: list[str], label: str) -> None:
        candidate = persona.model_copy(deep=True)
        advertised = capability.model_copy(deep=True)
        advertised.parameters = ["emulation_" + field for field in selected]
        randomize_device_emulation(candidate, advertised, random.Random(42))
        assert candidate.emulation is not None
        if candidate.emulation.privacy is not None:
            candidate.emulation.privacy.do_not_track = True
            candidate.emulation.privacy.global_privacy_control = True
        if candidate.emulation.voices is not None:
            candidate.emulation.voices = "none"
        if candidate.emulation.sensors is not None:
            candidate.permissions = [
                PermissionConfig(origin=url, permissions=["accelerometer", "gyroscope"])
            ]

        async def check(context: Any, factory: Any) -> None:
            assert candidate.emulation is not None
            page = await context.new_page()
            await page.goto(url)
            native = candidate.runtime.backend == "camoufox"
            actual = await validate_device_emulation(page, candidate, main_world=native)
            if candidate.emulation.privacy is not None:
                assert headers[-1].get("dnt") == "1" and headers[-1].get("sec-gpc") == "1"
            if candidate.emulation.media is not None:
                assert actual["media"] is not None
                assert {d["kind"] for d in actual["media"]} == {
                    d.kind for d in candidate.emulation.media
                }
            if candidate.emulation.sensors is not None:
                # Observe events in the same main-world interface as target scripts.
                from syntetic_core._engine.browser.sensors import SENSOR_OBSERVATION_SCRIPT

                readings = await page.evaluate(
                    ("mw:" if native else "") + SENSOR_OBSERVATION_SCRIPT
                )
                assert readings_match(candidate.emulation.sensors, readings)
            await page.set_content('<iframe src="' + url + '"></iframe>')
            frame = page.frames[-1]
            await frame.wait_for_load_state()
            await validate_device_emulation(frame, candidate, main_world=native)

        await probe(candidate, label, check)

    try:
        await attempt(fields, "document-emulation")
        passed = fields
    except Exception:
        passed = []
        for field in fields:
            try:
                await attempt([field], "document-emulation-" + field)
                passed.append(field)
            except Exception:
                pass
    capability.parameters.extend("emulation_" + field for field in passed)
    if passed:
        capability.limitations.append(
            "JS device emulation covers documents/frames, not workers or physical hardware. "
            "WebGL masks identity strings; fonts filter FontFaceSet/canvas; media lists do not "
            "create streams; voices are a subset of host voices."
        )
    missing = set(fields) - set(passed)
    if missing:
        capability.limitations.append(
            "Document emulation smoke did not pass: " + ", ".join(sorted(missing))
        )
    required = (
        {"emulation_webgl", "hardware_concurrency"}
        if persona.browser_engine == "chromium"
        else {"emulation_webgl", "emulation_hardware_concurrency"}
        if persona.browser_engine == "webkit"
        else set()
    )
    if required <= set(capability.parameters):
        from syntetic_core._engine.device_coherence import bind_device_recipe

        candidate = persona.model_copy(deep=True)
        advertised = capability.model_copy(deep=True)
        advertised.parameters.append("device_coherence")

        async def coherent_check(context: Any, factory: Any) -> None:
            page = await context.new_page()
            await page.goto(url)
            await validate_device_emulation(
                page, candidate, main_world=candidate.runtime.backend == "camoufox"
            )
            if candidate.chromium is not None and candidate.chromium.architecture is not None:
                architecture = await page.evaluate("""async () =>
                    (await navigator.userAgentData.getHighEntropyValues(['architecture']))
                        .architecture
                """)
                assert architecture == candidate.chromium.architecture

        try:
            randomize_device_emulation(candidate, advertised, random.Random(71))
            bind_device_recipe(candidate, advertised, random.Random(71))
            await probe(candidate, "device-coherence", coherent_check)
            capability.parameters.append("device_coherence")
            from syntetic_core._engine.device_coherence import supported_recipe_ids

            capability.coherence_version = 1
            capability.coherence_recipes = supported_recipe_ids(persona.browser_engine)
        except Exception:
            capability.limitations.append("Coherent device recipe smoke did not pass.")
