"""Observe the exit connection through a browser navigation, never a Python HTTP client."""

import ipaddress
import math
import re
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext
from pydantic import BaseModel, ConfigDict, Field, field_validator

from syntetic_core._engine.errors import ProfileValidationError, ProxyUnavailableError
from syntetic_core._engine.personas import BrowserPersona


class NetworkObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ip: str
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    timezone: str | None = None
    asn: int | None = Field(default=None, gt=0)
    kind: str | None = None
    risk_score: float | None = Field(default=None, ge=0, le=100)
    user_agent: str | None = Field(default=None, max_length=1000)
    tls_version: str | None = Field(default=None, max_length=100)
    ja4: str | None = Field(default=None, max_length=200)
    http2_fingerprint: str | None = Field(default=None, max_length=1000)
    http_version: str | None = Field(default=None, max_length=100)
    dns_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")

    @field_validator("ip")
    @classmethod
    def valid_ip(cls, value: str) -> str:
        return str(ipaddress.ip_address(value))


def validate_probe_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.scheme not in {"http", "https"}
    ):
        raise ProfileValidationError("Network probe requires an HTTP(S) URL without credentials")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ProfileValidationError("Remote network probes require HTTPS")


async def observe_network(context: BrowserContext, url: str) -> dict[str, Any]:
    validate_probe_url(url)
    page = await context.new_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded")
        if response is None or not response.ok:
            raise ValueError("Probe response failed")
        # Redirecting to a login or challenge page must fail, never become a direct fallback.
        original, final = urlsplit(url), urlsplit(page.url)
        if (final.scheme, final.netloc) != (original.scheme, original.netloc):
            raise ValueError("Probe changed origin")
        body = await response.body()
        if len(body) > 65536:
            raise ValueError("Probe response exceeds limit")
        observation = NetworkObservation.model_validate_json(body)
        actual_ua = await page.evaluate("navigator.userAgent")
        if observation.user_agent and observation.user_agent != actual_ua:
            raise ProfileValidationError("HTTP User-Agent differs from JavaScript User-Agent")
        return observation.model_dump(exclude_none=True)
    except ProfileValidationError:
        raise
    except Exception:
        raise ProxyUnavailableError("Browser network probe failed") from None
    finally:
        await page.close()


def validate_network(persona: BrowserPersona, observation: dict[str, Any]) -> None:
    policy = persona.network
    if policy.expected_country and observation.get("country") != policy.expected_country:
        raise ProfileValidationError("Observed IP country differs from the required country")
    if policy.allowed_asns and observation.get("asn") not in policy.allowed_asns:
        raise ProfileValidationError("Observed ASN is not allowed")
    if policy.allowed_kinds and observation.get("kind") not in policy.allowed_kinds:
        raise ProfileValidationError("Observed network kind is not allowed")
    if policy.max_risk_score is not None and (
        observation.get("risk_score") is None or observation["risk_score"] > policy.max_risk_score
    ):
        raise ProfileValidationError("IP reputation is missing or exceeds the allowed risk")
    if policy.require_timezone_match and observation.get("timezone") != persona.timezone_id:
        raise ProfileValidationError("Observed IP timezone differs from the browser timezone")
    if policy.require_dns_match and (
        not observation.get("dns_country")
        or observation["dns_country"] != observation.get("country")
    ):
        raise ProfileValidationError("DNS country differs from the exit IP country")
    if policy.expected_ja4 and observation.get("ja4") != policy.expected_ja4:
        raise ProfileValidationError("TLS fingerprint differs from the required baseline")
    if (
        policy.expected_http2_fingerprint
        and observation.get("http2_fingerprint") != policy.expected_http2_fingerprint
    ):
        raise ProfileValidationError("HTTP/2 fingerprint differs from the required baseline")


def validate_runtime_environment(
    engine: str,
    environment: dict[str, Any],
    version: str,
    *,
    expected_os: str | None = None,
    phone_form_factor: str | None = None,
) -> None:
    token = {
        "chromium": r"(?:Chrome|HeadlessChrome)/(\d+)",
        "firefox": r"Firefox/(\d+)",
        "webkit": r"Version/(\d+)",
    }[engine]
    match = re.search(token, environment.get("user_agent", ""))
    if not match:
        raise ProfileValidationError("User-Agent does not match the running browser engine")
    # WebKit's engine build number is not Safari's product version.
    if engine != "webkit" and version.split(".", 1)[0] != match.group(1):
        raise ProfileValidationError("User-Agent version differs from the running browser")
    if expected_os is not None:
        ua_token, platform_prefix = {
            "windows": ("Windows NT", "Win"),
            "macos": ("Mac OS X", "Mac"),
            "linux": ("Linux", "Linux"),
            "android": ("Android", "Linux"),
            "ios": ("iPhone OS", "iPhone"),
        }[expected_os]
        if expected_os == "ios" and phone_form_factor == "tablet":
            ua_token, platform_prefix = "iPad; CPU OS", "iPad"
        if ua_token not in environment.get("user_agent", "") or not environment.get(
            "platform", ""
        ).startswith(platform_prefix):
            raise ProfileValidationError("User-Agent/platform differs from the assigned OS")
    hints = environment.get("client_hints")
    if hints and engine == "chromium":
        if expected_os is not None:
            hint_platform = {
                "windows": "Windows",
                "macos": "macOS",
                "linux": "Linux",
                "android": "Android",
            }[expected_os]
            if hints.get("platform") != hint_platform:
                raise ProfileValidationError("Client Hints platform differs from the assigned OS")
        brands = hints.get("brands", [])
        actual = [
            brand["version"]
            for brand in brands
            if brand["brand"] in {"Chromium", "Google Chrome", "Microsoft Edge"}
        ]
        if any(value.split(".", 1)[0] != match.group(1) for value in actual):
            raise ProfileValidationError("Client Hints version differs from User-Agent")


def validate_persona_environment(
    persona: BrowserPersona, device: dict[str, Any], environment: dict[str, Any]
) -> None:
    expected = {
        "locale": persona.locale,
        "timezone": persona.timezone_id,
        "viewport": device["viewport"],
        "screen": device["screen"],
        "device_scale_factor": device.get("device_scale_factor", 1),
    }
    if persona.display is not None:
        expected.update(persona.display.model_dump())
    if persona.hardware_concurrency_override is not None:
        expected["hardware_concurrency"] = persona.hardware_concurrency_override
    if device.get("is_mobile"):
        # Mobile layout viewport depends on the document's meta viewport and
        # can legitimately be wider than the emulated display on about:blank.
        expected.pop("viewport")
    for field, value in expected.items():
        if environment.get(field) != value:
            raise ProfileValidationError(f"{field}: browser observation differs from persona")
    if persona.native_audio is not None:
        actual_audio = environment.get("native_audio", {})
        audio = persona.native_audio
        if (
            actual_audio.get("sample_rate") != audio.sample_rate
            or actual_audio.get("max_channels") != audio.max_channels
            or not isinstance(actual_audio.get("output_latency"), (float, int))
            or not math.isclose(actual_audio["output_latency"], audio.output_latency, abs_tol=1e-6)
        ):
            raise ProfileValidationError("native_audio: browser observation differs from persona")
    if persona.native_desktop is not None:
        desktop = persona.native_desktop
        extended = environment.get("extended", {})
        expected_desktop = {
            "available_screen": {
                "left": desktop.avail_left,
                "top": desktop.avail_top,
                "width": desktop.avail_width,
                "height": desktop.avail_height,
            },
            "outer_window": {"width": desktop.outer_width, "height": desktop.outer_height},
            "do_not_track": "1" if desktop.do_not_track else "unspecified",
            "global_privacy_control": desktop.global_privacy_control,
        }
        if any(extended.get(key) != value for key, value in expected_desktop.items()):
            raise ProfileValidationError("native_desktop: observation differs from persona")
    languages = environment.get("languages")
    if not languages or languages[0] != persona.locale:
        raise ProfileValidationError("navigator.languages differs from persona locale")
    if bool(environment.get("touch_points")) != bool(device.get("has_touch")):
        raise ProfileValidationError("Touch support differs from the assigned device")
    cores = environment.get("hardware_concurrency")
    if isinstance(cores, bool) or not isinstance(cores, int) or cores < 1:
        raise ProfileValidationError("Invalid observed hardware concurrency")
