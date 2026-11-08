"""Mandatory initialization shared by project sessions and scenario test contexts."""

from pathlib import Path
from time import time
from typing import Any

from playwright.async_api import BrowserContext, Page
from playwright.sync_api import BrowserContext as SyncBrowserContext

from syntetic_core._engine.browser.automation import WEBDRIVER_SCRIPT, configure_webdriver
from syntetic_core._engine.browser.canvas import canvas_script, configure_canvas
from syntetic_core._engine.browser.device_emulation import (
    configure_device_emulation,
    emulation_script,
)
from syntetic_core._engine.browser.session_hardware import effective_emulation
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona


async def configure_session_apis(
    context: BrowserContext, persona: BrowserPersona, profile_path: Path
) -> None:
    await configure_canvas(context, persona, profile_path)
    await configure_device_emulation(context, persona, profile_path)
    await configure_webdriver(context, native=persona.runtime.backend == "camoufox")


def configure_sync_session_apis(context: SyncBrowserContext, persona: BrowserPersona) -> None:
    """Apply the same scripts to ephemeral synchronous operator-UI probes."""
    scripts = [canvas_script(persona)]
    if effective_emulation(persona) is not None:
        scripts.append(emulation_script(persona, battery_epoch_ms=int(time() * 1000)))
    if persona.runtime.backend == "camoufox":
        scripts += ["mw:" + source for source in list(scripts)]
    else:
        scripts.append(WEBDRIVER_SCRIPT)
    for source in scripts:
        context.add_init_script(source)
    for page in context.pages:
        for frame in page.frames:
            for source in scripts:
                frame.evaluate(source)


async def validate_session_apis(page: Page, persona: BrowserPersona) -> dict[str, Any]:
    prefix = "mw:" if persona.runtime.backend == "camoufox" else ""
    actual = await page.evaluate(
        prefix
        + """() => ({
        canvas: globalThis[Symbol.for('synthetic-sessions.canvas-geometry.v1')] === true,
        native_functions: typeof globalThis[
            Symbol.for('synthetic-sessions.native-functions.v1')] === 'function',
        canvas_source: CanvasRenderingContext2D.prototype.fillText.toString() ===
            'function fillText() { [native code] }',
        webdriver: navigator.webdriver === false
    })"""
    )
    if not all(
        actual.get(key) is True
        for key in ("canvas", "native_functions", "canvas_source", "webdriver")
    ):
        raise ProfileValidationError("Mandatory session API policy did not initialize")
    return {"version": 1, **actual}
