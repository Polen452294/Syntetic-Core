"""Mandatory Chromium document hardware, without mutating immutable personas."""

from contextvars import ContextVar

from syntetic_core._engine.browser.canvas import canvas_identity
from syntetic_core._engine.device_coherence import device_memory_choices
from syntetic_core._engine.personas import BrowserPersona, DeviceEmulation, EmulatedBattery

session_emulation: ContextVar[DeviceEmulation | None] = ContextVar(
    "session_emulation", default=None
)


def effective_emulation(persona: BrowserPersona) -> DeviceEmulation | None:
    if persona.browser_engine != "chromium":
        return persona.emulation
    if (saved := session_emulation.get()) is not None:
        return saved.model_copy(deep=True)
    seed = str(canvas_identity(persona)["seed"])
    draws = [int(seed[index : index + 8], 16) for index in range(0, 64, 8)]
    value = (
        persona.emulation.model_copy(deep=True)
        if persona.emulation
        else (DeviceEmulation(seed=max(1, draws[0])))
    )
    if value.device_memory is None:
        # The shared 4/8 GiB range is valid in older and current Chromium builds.
        choices = tuple(memory for memory in device_memory_choices(persona) if memory <= 8)
        value.device_memory = float(choices[draws[1] % len(choices)])
    if value.battery is None:
        value.battery = EmulatedBattery(
            charging=draws[2] % 100 < 35,
            level=(30 + draws[3] % 70) / 100,
            charge_seconds=(5400, 7200, 10800)[draws[4] % 3],
            discharge_seconds=(14400, 21600, 28800, 43200)[draws[5] % 4],
        )
    return value


def hardware_identity(persona: BrowserPersona) -> dict:
    value = effective_emulation(persona)
    assert value is not None and persona.browser_engine == "chromium"
    return {
        "version": 1,
        "profile": persona.fingerprint_id or persona.id,
        **(
            {"hardware_concurrency": value.hardware_concurrency}
            if session_emulation.get() is not None
            else {}
        ),
        "device_memory": value.device_memory,
        "battery": value.battery.model_dump(mode="json") if value.battery else None,
    }
