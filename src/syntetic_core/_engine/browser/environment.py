"""Compare observed page properties with the environment accepted at startup."""

import math
from typing import Any

from playwright.async_api import Page

ENVIRONMENT_SCRIPT = """() => ({
    user_agent: navigator.userAgent, platform: navigator.platform,
    locale: navigator.language, languages: navigator.languages,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    viewport: {width: innerWidth, height: innerHeight},
    screen: {width: screen.width, height: screen.height},
    device_scale_factor: devicePixelRatio,
    viewport_scale: visualViewport?.scale ?? 1,
    touch_points: navigator.maxTouchPoints, hardware_concurrency: navigator.hardwareConcurrency,
    color_scheme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
    reduced_motion: matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'reduce' : 'no-preference',
    contrast: matchMedia('(prefers-contrast: more)').matches ? 'more' : 'no-preference',
    forced_colors: matchMedia('(forced-colors: active)').matches ? 'active' : 'none'
})"""


def environment_differences(
    expected: dict[str, Any], actual: dict[str, Any], *, mobile: bool = False
) -> list[str]:
    fields = (
        "user_agent",
        "platform",
        "locale",
        "languages",
        "timezone",
        "viewport",
        "screen",
        "device_scale_factor",
        "touch_points",
        "hardware_concurrency",
        "color_scheme",
        "reduced_motion",
        "contrast",
        "forced_colors",
    )
    changed = [
        field for field in fields if field in expected and expected[field] != actual.get(field)
    ]
    if not mobile:
        return changed
    # Mobile documents choose a layout viewport through their viewport meta tag.
    # WebKit also includes that page scale in devicePixelRatio. Compare their
    # physical dimensions; changing screen, touch, UA or real DPR still fails.
    try:
        expected_scale = float(expected.get("viewport_scale", 1))
        actual_scale = float(actual["viewport_scale"])
        if not all(math.isfinite(scale) and scale > 0 for scale in [expected_scale, actual_scale]):
            return changed
        viewport_matches = all(
            math.isclose(
                expected["viewport"][axis] * expected_scale,
                actual["viewport"][axis] * actual_scale,
                abs_tol=1,
            )
            for axis in ["width", "height"]
        )
        if viewport_matches:
            changed = [field for field in changed if field != "viewport"]
            if math.isclose(
                expected["device_scale_factor"] / expected_scale,
                actual["device_scale_factor"] / actual_scale,
                abs_tol=0.001,
            ):
                changed = [field for field in changed if field != "device_scale_factor"]
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    return changed


def environment_mismatch_metadata(
    expected: dict[str, Any], actual: dict[str, Any], changed_fields: list[str]
) -> dict[str, Any]:
    """Include only finite geometry in layout diagnostics, never page identity."""
    if not {"viewport", "screen", "device_scale_factor", "viewport_scale"}.intersection(
        changed_fields
    ):
        return {}

    def finite_number(value: Any) -> bool:
        return type(value) is int or (type(value) is float and math.isfinite(value))

    def geometry(source: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field in ("viewport", "screen"):
            dimensions = source.get(field)
            if isinstance(dimensions, dict):
                result[field] = {
                    axis: dimensions[axis]
                    for axis in ("width", "height")
                    if finite_number(dimensions.get(axis))
                }
        for field in ("device_scale_factor", "viewport_scale"):
            if finite_number(source.get(field)):
                result[field] = source[field]
        return result

    return {"geometry": {"expected": geometry(expected), "observed": geometry(actual)}}


async def observe_page_environment(page: Page, *, main_world: bool = False) -> dict[str, Any]:
    return await page.evaluate(("mw:" if main_world else "") + ENVIRONMENT_SCRIPT)
