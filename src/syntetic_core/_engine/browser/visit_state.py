"""Prepare observable visitor/storage/cache conditions before scenario timing."""

import json
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext

from syntetic_core._engine.config import Settings
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona
from syntetic_core._engine.targets import authorize_url


def require_unused_profile(
    persona: BrowserPersona,
    profile_path: Path,
    prior_sessions: int,
    *,
    fixed_fresh: bool = False,
) -> None:
    if not fixed_fresh and (persona.visit_state is None or persona.visit_state.visitor != "new"):
        return
    if prior_sessions:
        raise ProfileValidationError("New visitor condition requires an unused profile")
    # The storage fencing manifest is written before the first browser launch.
    # Any browser-created data means this directory is not a clean initial profile.
    if profile_path.exists() and any(
        path.name != ".storage-incarnation.json" for path in profile_path.iterdir()
    ):
        raise ProfileValidationError("New visitor condition requires empty browser storage")


async def prepare_visit_state(
    context: BrowserContext,
    persona: BrowserPersona,
    base_url: str,
    settings: Settings,
    prior_sessions: int,
    *,
    organic_search: bool = False,
) -> dict[str, Any]:
    if settings.incubation_config:
        return {"cache_policy": "native_profile", "prior_sessions": prior_sessions}
    state = persona.visit_state
    if state is None:
        return {}
    authorize_url(base_url, settings)
    origin = urlsplit(base_url)
    origin_url = f"{origin.scheme}://{origin.netloc}"
    if state.visitor == "new" and prior_sessions:
        raise ProfileValidationError("New visitor condition requires a fresh profile")
    if organic_search and state.cache == "cold" and (prior_sessions or state.visitor != "new"):
        raise ProfileValidationError(
            "Organic cold cache requires a fresh profile; interception is forbidden"
        )
    if state.visitor == "new":
        host = origin.hostname or ""
        # Inspect all cookie paths, including cookies that would only be sent
        # after navigating deeper into the same site.
        cookies = await context.cookies()
        if any(
            host == cookie["domain"].lstrip(".")
            or host.endswith("." + cookie["domain"].lstrip("."))
            for cookie in cookies
        ):
            raise ProfileValidationError("New visitor condition forbids existing target cookies")
    if state.grant_geolocation and persona.geolocation is not None:
        await context.grant_permissions(["geolocation"], origin=origin_url)
    for preferences in state.preferences:
        # Never visit extra origins to seed state. Only the scenario origin is eligible.
        if preferences.origin != origin_url:
            continue
        if preferences.cookies:
            await context.add_cookies(
                [
                    {"name": name, "value": value, "url": origin_url}
                    for name, value in preferences.cookies.items()
                ]
            )
        if preferences.local_storage:
            payload = json.dumps({"origin": origin_url, "values": preferences.local_storage})
            await context.add_init_script(
                script="""(data => {
                if (location.origin !== data.origin) return;
                for (const [key, value] of Object.entries(data.values)) {
                    if (localStorage.getItem(key) === null) localStorage.setItem(key, value);
                }
            })("""
                + payload
                + ");"
            )
    started = monotonic()
    primer_visits = 0
    if not organic_search and (
        state.visitor == "returning" and not prior_sessions or state.cache == "warm"
    ):
        page = await context.new_page()
        try:
            # A real preparatory visit creates the site's own storage and cache.
            await page.goto(base_url, wait_until="load", timeout=settings.navigation_timeout * 1000)
            primer_visits = 1
        finally:
            await page.close()
    if state.cache == "cold" and not organic_search:
        if persona.browser_engine == "chromium":
            page = context.pages[0] if context.pages else await context.new_page()
            client = await context.new_cdp_session(page)
            try:
                await client.send("Network.clearBrowserCache")
            finally:
                await client.detach()
        elif persona.browser_engine != "firefox":
            raise ProfileValidationError("Native cold cache control is unavailable for this engine")
        # Firefox/Camoufox disable native caches at launch for cold sessions.
    return {
        "visitor": state.visitor,
        "cache_requested": state.cache,
        "cache_policy": (
            "native_profile"
            if organic_search
            else "cleared_at_start"
            if persona.browser_engine == "chromium"
            else "disabled"
            if state.cache == "cold"
            else "browser_managed_after_primer"
        ),
        "primer_visits": primer_visits,
        "prior_sessions": prior_sessions,
        "preparation_ms": round((monotonic() - started) * 1000),
        "cache_guaranteed": state.cache == "cold" and not organic_search,
        "geolocation_permission": "granted" if state.grant_geolocation else "unchanged",
    }
