"""WebKit phone configuration and the persistent identity of an emulated iPhone."""

import asyncio
import random
from pathlib import Path

from playwright.async_api import BrowserContext, Page
from playwright.async_api import Error as PlaywrightError

from syntetic_core._engine.browser.identity import read_json, write_json
from syntetic_core._engine.browser.native_functions import native_script
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.pacing import _sample_pause_ms
from syntetic_core._engine.personas import BehaviorConfig, BrowserPersona


async def mobile_key(page: Page, key: str) -> None:
    """Native key events. Chromium's protocol also supports non-US Unicode keys."""
    try:
        await page.keyboard.down(key)
    except PlaywrightError as error:
        if "Unknown key:" not in str(error):
            raise
        # Playwright's US key map rejects these before dispatch on every engine.
        # Do not silently fall back to insert_text, which loses the key events.
        browser = page.context.browser
        if browser is None or browser.browser_type.name != "chromium":
            raise ProfileValidationError(
                "Native Unicode key events require the Chromium mobile driver; "
                "Playwright WebKit does not expose a Unicode key transport"
            ) from None
        session = await page.context.new_cdp_session(page)
        try:
            await session.send(
                "Input.dispatchKeyEvent",
                {
                    "type": "keyDown",
                    "key": key,
                    "text": key,
                    "unmodifiedText": key,
                },
            )
            await session.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key})
        finally:
            await session.detach()
        return
    await page.keyboard.up(key)


async def type_mobile_text(
    page: Page,
    value: str,
    config: BehaviorConfig,
    rng: random.Random,
) -> None:
    for character in value:
        # Restrict corrected typos to simple letters: Backspace removes a whole
        # grapheme on some platforms, so never intentionally corrupt Unicode clusters.
        if config.enabled and character.isascii() and character.isalpha() and rng.random() < 0.015:
            wrong = rng.choice("abcdefghijklmnopqrstuvwxyz".replace(character.lower(), ""))
            await mobile_key(page, wrong)
            await asyncio.sleep(
                _sample_pause_ms(config.key_min_ms, config.key_max_ms, config, rng) / 1000
            )
            await mobile_key(page, "Backspace")
            await asyncio.sleep(
                _sample_pause_ms(config.key_min_ms, config.key_max_ms, config, rng) / 1000
            )
        await mobile_key(page, character)
        if config.enabled:
            await asyncio.sleep(
                _sample_pause_ms(config.key_min_ms, config.key_max_ms, config, rng) / 1000
            )


# WebKit's desktop port provides real touch events/coarse pointers but keeps
# the host's platform and zero maxTouchPoints. This explicit, iOS-only compatibility
# shim covers documents/frames; it does not claim to reproduce an actual iOS kernel.
IOS_NAVIGATOR = native_script("""(() => {
    const makeNative = __NATIVE_FUNCTIONS__;
    for (const [name, value] of [['platform', 'iPhone'], ['maxTouchPoints', 5]]) {
        const descriptor = Object.getOwnPropertyDescriptor(Navigator.prototype, name);
        Object.defineProperty(Navigator.prototype, name, {
            configurable: descriptor?.configurable ?? true,
            enumerable: descriptor?.enumerable ?? true,
            get: makeNative(function () {
                if (descriptor?.get) Reflect.apply(descriptor.get, this, []);
                return value;
            }, 'get ' + name, descriptor?.get)
        });
    }
})()""")


def ios_navigator(persona: BrowserPersona) -> str:
    assert persona.phone is not None
    if persona.phone.form_factor == "tablet":
        return IOS_NAVIGATOR.replace("iPhone", "iPad")
    return IOS_NAVIGATOR


def ios_user_agent(persona: BrowserPersona) -> str:
    assert persona.phone is not None and persona.phone.family == "ios"
    version = persona.phone.os_version
    # Safari 26 freezes the OS token for compatibility; Version/ still reports
    # Safari's release. See the WebKit release notes linked in browser-personas.
    os_token = version
    if persona.phone.preset_id is not None and int(version.split(".", 1)[0]) >= 26:
        os_token = "18.6" if version == "26.0" else "18.7"
    device_token = (
        "iPad; CPU OS" if persona.phone.form_factor == "tablet" else "iPhone; CPU iPhone OS"
    )
    return (
        f"Mozilla/5.0 ({device_token} "
        f"{os_token.replace('.', '_')} like Mac OS X) "
        f"AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{version} "
        "Mobile/15E148 Safari/604.1"
    )


async def configure_ios(
    context: BrowserContext, persona: BrowserPersona, profile_path: Path
) -> None:
    assert persona.phone is not None and persona.phone.family == "ios"
    path = profile_path.parent / "ios-identity.json"
    if persona.fingerprint_id:
        path = profile_path.parent / "fingerprints" / f"{persona.fingerprint_id}.json"
    signature = {"phone": persona.phone.model_dump(), "device": persona.device.model_dump()}
    version = context.browser.version if context.browser else "unknown"
    stored = await asyncio.to_thread(read_json, path)
    if stored and (stored.get("signature") != signature or stored.get("version") != version):
        raise ProfileValidationError("iOS identity changed; create a new profile")
    navigator_script = ios_navigator(persona)
    await context.add_init_script(navigator_script)
    for page in context.pages:
        await page.evaluate(navigator_script)
    await asyncio.to_thread(write_json, path, {"signature": signature, "version": version})
