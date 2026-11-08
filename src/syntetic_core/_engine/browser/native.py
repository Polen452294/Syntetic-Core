"""Camoufox native fingerprints bound to their persistent profile."""

import json
import platform
import re
from pathlib import Path
from typing import Any

from syntetic_core._engine.browser.identity import read_json, write_json
from syntetic_core._engine.errors import BrowserLaunchError, ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona
from syntetic_core._engine.proxies import ProxyConfig


def align_fingerprint_platform(fingerprint: dict[str, Any], target_os: str) -> None:
    """Repair inconsistent sampled navigator fields before saving a new identity."""
    navigator = fingerprint["navigator"]
    if target_os in {"windows", "macos"}:
        navigator["platform"] = "Win32" if target_os == "windows" else "MacIntel"
    else:
        architecture = re.search(
            r"Linux (?:x86_64|i686|aarch64|armv\w+)", navigator.get("userAgent", "")
        )
        if architecture:
            navigator["platform"] = architecture.group()
            navigator["oscpu"] = architecture.group()


def camoufox_options(
    persona: BrowserPersona,
    profile_path: Path,
    headless: bool,
    proxy: ProxyConfig | None,
    browser_build: str,
    installation: Path,
    addons: list[str] | None = None,
) -> dict[str, Any]:
    from camoufox.addons import DefaultAddons
    from camoufox.fingerprints import generate_fingerprint
    from camoufox.pkgman import Version, launch_path
    from camoufox.utils import launch_options

    try:
        # Installation is an explicit build/setup step, not a network side effect of a session.
        installation = installation.resolve()
        version = Version.from_path(installation).full_string
        if version != browser_build.rsplit("/", 1)[-1]:
            raise ValueError("Installed native browser differs from the configured pin")
        executable = launch_path(installation)
    except Exception:
        raise BrowserLaunchError(
            "Pinned Camoufox is not installed; run python scripts/setup_browser.py"
        ) from None
    identity_path = profile_path.parent / "native-identity.json"
    if persona.fingerprint_id is not None:
        identity_path = profile_path.parent / "fingerprints" / f"{persona.fingerprint_id}.json"
    stored = read_json(identity_path)
    target_os = (
        persona.runtime.target_os
        or {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[platform.system()]
    )
    signature = {
        "os": target_os,
        "installation": str(installation),
        "device": persona.device.model_dump(),
        "fonts": persona.runtime.fonts,
        "webgl": list(persona.runtime.webgl) if persona.runtime.webgl else None,
    }
    if persona.coherence is not None:
        signature["coherence"] = persona.coherence.model_dump()
    if persona.native_audio is not None:
        signature["audio"] = persona.native_audio.model_dump()
    if persona.native_desktop is not None:
        signature["desktop"] = persona.native_desktop.model_dump()
    if persona.native_media is not None:
        signature["media"] = persona.native_media.model_dump()
    if stored and (stored.get("signature") != signature or stored.get("version") != version):
        raise ProfileValidationError(
            "Native device or browser build changed; create a new profile to change identity"
        )
    fingerprint = stored.get("fingerprint")
    if fingerprint is None:
        fingerprint = generate_fingerprint(
            os=target_os,
            window=(persona.device.viewport["width"], persona.device.viewport["height"]),
        )
        align_fingerprint_platform(fingerprint, target_os)
    config = dict(stored.get("config", {}))
    # Travel/locale changes do not redraw the hardware identity.
    config["timezone"] = persona.timezone_id
    for key in list(config):
        if key.startswith("locale:") or key in {
            "navigator.language",
            "navigator.languages",
            "headers.Accept-Language",
        }:
            del config[key]
    config["window.devicePixelRatio"] = persona.device.device_scale_factor
    # Generated desktop fingerprints can include touch-capable laptops, while
    # this runtime's validated desktop contract explicitly has touch disabled.
    config["navigator.maxTouchPoints"] = 0
    if persona.coherence is not None:
        config["navigator.hardwareConcurrency"] = int(persona.coherence.recipe_id.rsplit("-", 1)[1])
    # Persona viewport is the content area, not the outer window including browser chrome.
    config["window.innerWidth"] = persona.device.viewport["width"]
    config["window.innerHeight"] = persona.device.viewport["height"]
    # Assign geometry directly; strict generator screen filters can have no
    # matching samples for a supported OS/display combination (e.g. macOS/1366x768).
    config["screen.width"] = persona.device.screen["width"]
    config["screen.height"] = persona.device.screen["height"]
    config["screen.availWidth"] = persona.device.screen["width"]
    config["screen.availHeight"] = persona.device.screen["height"]
    config.setdefault("screen.availLeft", 0)
    config.setdefault("screen.availTop", 0)
    desktop = persona.native_desktop
    prefs: dict[str, Any] = {"permissions.default.geo": 0}
    if persona.emulation is not None and persona.emulation.privacy is not None:
        privacy = persona.emulation.privacy
        config["navigator.doNotTrack"] = "1" if privacy.do_not_track else "unspecified"
        config["navigator.globalPrivacyControl"] = privacy.global_privacy_control
        prefs["privacy.donottrackheader.enabled"] = privacy.do_not_track
        prefs["privacy.globalprivacycontrol.enabled"] = privacy.global_privacy_control
    if desktop is not None:
        config.update(
            {
                "screen.availWidth": desktop.avail_width,
                "screen.availHeight": desktop.avail_height,
                "screen.availLeft": desktop.avail_left,
                "screen.availTop": desktop.avail_top,
                "window.outerWidth": desktop.outer_width,
                "window.outerHeight": desktop.outer_height - desktop.config_height_offset,
                "window.screenX": desktop.avail_left,
                "window.screenY": desktop.avail_top,
                "navigator.doNotTrack": "1" if desktop.do_not_track else "unspecified",
                "navigator.globalPrivacyControl": desktop.global_privacy_control,
            }
        )
        prefs.update(
            {
                "privacy.donottrackheader.enabled": desktop.do_not_track,
                "privacy.globalprivacycontrol.enabled": desktop.global_privacy_control,
            }
        )
    # Session interactions own Fitts timing and the full tremor/correction path.
    # A second native trajectory would distort every generated segment.
    config["humanize"] = False
    if persona.native_audio is not None:
        config.update(
            {
                "AudioContext:sampleRate": persona.native_audio.sample_rate,
                "AudioContext:outputLatency": persona.native_audio.output_latency,
                "AudioContext:maxChannelCount": persona.native_audio.max_channels,
            }
        )
    # Camoufox's C++ location override auto-grants every origin. Use Playwright's
    # native context location with explicit origin grants instead.
    for key in list(config):
        if key.startswith("geolocation:"):
            del config[key]
    if persona.native_media is not None:
        from syntetic_core._engine.browser.media_presets import apply_media_preset

        apply_media_preset(config, persona)
    options = launch_options(
        config=config,
        executable_path=executable,
        os=target_os,
        fingerprint=fingerprint,
        locale=persona.locale,
        headless=headless,
        main_world_eval=True,
        window=(persona.device.viewport["width"], persona.device.viewport["height"]),
        fonts=persona.runtime.fonts,
        webgl_config=persona.runtime.webgl,
        block_webrtc=persona.runtime.webrtc == "disabled"
        or (persona.runtime.webrtc == "proxy_only" and proxy is not None),
        humanize=False,
        enable_cache=True,
        firefox_user_prefs=prefs,
        exclude_addons=list(DefaultAddons),
        addons=addons or [],
        pin_cpu_cores=persona.runtime.pin_cpu_cores,
        proxy=proxy.playwright() if proxy else None,
        i_know_what_im_doing=True,
    )
    options.update(
        user_data_dir=str(profile_path),
        no_viewport=False,
        viewport=persona.device.viewport,
        screen=persona.device.screen,
        device_scale_factor=persona.device.device_scale_factor,
        timezone_id=persona.timezone_id,
    )
    if persona.geolocation:
        options["geolocation"] = persona.geolocation.model_dump()
    # Persist generated identity data, never process env, proxy auth or launch options.
    chunks = sorted(
        (int(key.rsplit("_", 1)[1]), value)
        for key, value in options["env"].items()
        if key.startswith("CAMOU_CONFIG_")
    )
    generated = json.loads("".join(value for _, value in chunks))
    if persona.coherence is not None:
        from camoufox.coherence import validate

        if generated.get("navigator.hardwareConcurrency") != config[
            "navigator.hardwareConcurrency"
        ] or validate(generated, {"windows": "win", "macos": "mac", "linux": "lin"}[target_os]):
            raise ProfileValidationError(
                "coherence.native: generated hardware conflicts with recipe"
            )
    write_json(
        identity_path,
        {
            "version": version,
            "signature": signature,
            "fingerprint": fingerprint,
            "config": generated,
        },
    )
    return options
