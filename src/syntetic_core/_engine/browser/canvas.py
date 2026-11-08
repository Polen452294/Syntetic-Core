"""Profile-stable canvas text geometry installed before document scripts."""

import asyncio
import hashlib
import json
from pathlib import Path

from playwright.async_api import BrowserContext

from syntetic_core._engine.browser.identity import read_json, write_json
from syntetic_core._engine.browser.native_functions import native_script
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona

CANVAS_SCRIPT = """(config => {
    const marker = Symbol.for('synthetic-sessions.canvas-geometry.v1');
    if (globalThis[marker]) return;
    const makeNative = __NATIVE_FUNCTIONS__;
    const shift = offset => parseInt(config.seed.slice(offset, offset + 8), 16)
        / 4294967296 * 0.04 - 0.02;
    const shiftX = shift(0), shiftY = shift(8);
    for (const name of ['CanvasRenderingContext2D', 'OffscreenCanvasRenderingContext2D']) {
        const proto = globalThis[name]?.prototype;
        if (!proto) continue;
        for (const method of ['fillText', 'strokeText']) {
            const descriptor = Object.getOwnPropertyDescriptor(proto, method);
            if (typeof descriptor?.value !== 'function') continue;
            const wrapped = new Proxy(descriptor.value, {apply(target, receiver, args) {
                if (args.length >= 3) {
                    const x = args[1], y = args[2];
                    // Let WebIDL validate the receiver/arity and coerce arguments in
                    // native order. Unary + preserves errors for Symbol and BigInt.
                    args[1] = {valueOf: () => +x + shiftX};
                    args[2] = {valueOf: () => +y + shiftY};
                }
                return Reflect.apply(target, receiver, args);
            }});
            Object.defineProperty(proto, method, {
                ...descriptor, value: makeNative(wrapped, method, descriptor.value)
            });
        }
    }
    Object.defineProperty(globalThis, marker, {value: true});
})(__CANVAS_CONFIG__);"""


def canvas_identity(persona: BrowserPersona) -> dict[str, int | str]:
    material = {
        "profile": persona.fingerprint_id or persona.id,
        "seed": persona.emulation.seed if persona.emulation else None,
        "recipe": persona.coherence.recipe_id if persona.coherence else None,
    }
    seed = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return {"version": 1, "seed": seed}


def canvas_script(persona: BrowserPersona) -> str:
    return native_script(CANVAS_SCRIPT).replace(
        "__CANVAS_CONFIG__", json.dumps(canvas_identity(persona))
    )


async def configure_canvas(
    context: BrowserContext, persona: BrowserPersona, profile_path: Path
) -> None:
    path = profile_path.parent / "canvas-identity.json"
    signature = canvas_identity(persona)
    stored = await asyncio.to_thread(read_json, path)
    if stored and stored != signature:
        raise ProfileValidationError("Canvas identity changed; create a new profile")
    script = canvas_script(persona)
    scripts = [script, "mw:" + script] if persona.runtime.backend == "camoufox" else [script]
    for source in scripts:
        await context.add_init_script(source)
    for page in context.pages:
        for frame in page.frames:
            for source in scripts:
                await frame.evaluate(source)
    await asyncio.to_thread(write_json, path, signature)
