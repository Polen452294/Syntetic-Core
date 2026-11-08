"""Offline MV3 rules, executed by the browser without Playwright interception."""

import json
import os
import platform
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from syntetic_core._engine.browser.network import (
    ADS_AND_TRACKERS_BLACKLIST,
    TrafficPolicy,
    _hostname,
)
from syntetic_core._engine.errors import ProfileValidationError
from syntetic_core._engine.personas import BrowserPersona

TEMPLATE = Path(__file__).parent / "extensions" / "content_filter"


def origin_pattern(base_url: str) -> str:
    origin = urlsplit(base_url)
    hostname = _hostname(base_url)
    host = re.escape(f"[{hostname}]" if ":" in hostname else hostname)
    default_port = 443 if origin.scheme == "https" else 80
    port = origin.port or default_port
    port_pattern = f"(:{port})?" if port == default_port else f":{port}"
    return f"^{origin.scheme}://{host}{port_pattern}/"


def prepare_filter(
    policy: TrafficPolicy,
    persona: BrowserPersona,
    profile: Path,
    base_url: str | None,
    *,
    incubation: bool = False,
) -> Path | None:
    if not policy.enabled:
        return None
    if persona.browser_engine == "webkit":
        if platform.system() != "Linux":
            raise ProfileValidationError(
                "Native Content Blocking requires Linux WebKitGTK and the native filter bridge"
            )
        target = profile.parent / ".content-filter" / "webkit-rules.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(webkit_rules(policy, base_url)), encoding="utf-8")
        return target.resolve()
    if persona.browser_engine == "chromium" and persona.runtime.channel not in {None, "chromium"}:
        raise ProfileValidationError("Content extensions require bundled Chromium")
    manifest = json.loads((TEMPLATE / "manifest.json").read_text(encoding="utf-8"))
    if persona.browser_engine == "firefox":
        manifest["browser_specific_settings"] = {
            "gecko": {"id": "qa-content-filter@local.invalid"},
        }
    types = ["media", "font"]
    if policy.version == 1:
        types += ["image", "websocket", "other", "ping"]
    if policy.block_stylesheets:
        types.append("stylesheet")
    rules: list[dict] = []

    def block(condition: dict, priority: int = 1) -> None:
        rules.append(
            {
                "id": len(rules) + 1,
                "priority": priority,
                "action": {"type": "block"},
                "condition": condition,
            }
        )

    block({"resourceTypes": types})
    if incubation:
        block({"resourceTypes": ["sub_frame"], "domainType": "thirdParty"})
    if policy.level != "metadata_only":
        if policy.version == 2:
            block({"resourceTypes": ["image"]})
            if base_url:
                rules.append(
                    {
                        "id": len(rules) + 1,
                        "priority": 2,
                        "action": {"type": "allow"},
                        "condition": {
                            "resourceTypes": ["image"],
                            "regexFilter": origin_pattern(base_url),
                        },
                    }
                )
        for pattern in ADS_AND_TRACKERS_BLACKLIST:
            condition: dict = {
                "urlFilter": "||" + pattern + ("^" if "/" not in pattern else ""),
            }
            if policy.version == 1:
                condition["excludedRequestDomains"] = [
                    "ya.ru",
                    "clck.yandex.ru",
                    "passport.yandex.ru",
                    *([_hostname(base_url)] if base_url else []),
                ]
            block(condition, priority=3)
    target = profile.parent / ".content-filter"
    target.mkdir(parents=True, exist_ok=True)
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    return target.resolve()


def local_vendor_extensions() -> list[Path]:
    """Load operator-provisioned unpacked MV3 uBlock/AdGuard bundles, never download."""
    extensions = []
    for name in ("ublock", "adguard"):
        path = TEMPLATE.parent / name
        if not path.exists():
            continue
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("manifest_version") != 3:
            raise ProfileValidationError("Local content extensions must use Manifest V3")
        extensions.append(path.resolve())
    return extensions


def chromium_filter_options(extension: Path, vendors: list[Path] | None = None) -> dict:
    paths = ",".join(str(path) for path in [extension, *(vendors or [])])
    return {
        "channel": "chromium",
        "ignore_default_args": ["--disable-extensions"],
        "args": [f"--disable-extensions-except={paths}", f"--load-extension={paths}"],
    }


def gecko_profile_options(profile: Path, extensions: list[Path]) -> dict[str, bool | int]:
    """Package profile-scoped XPIs for native installation before navigation."""
    directory = profile.parent / ".gecko-addons"
    directory.mkdir(parents=True, exist_ok=True)
    expected: set[Path] = set()
    for extension in extensions:
        manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
        identity = manifest.get("browser_specific_settings", {}).get("gecko", {}).get("id")
        if not identity or not re.fullmatch(r"[a-zA-Z0-9@._{}-]+", identity):
            raise ProfileValidationError("Gecko extension requires a stable, safe manifest ID")
        target = directory / f"{identity}.xpi"
        if target in expected:
            raise ProfileValidationError("Duplicate Gecko content extension ID")
        expected.add(target)
        temporary = target.with_suffix(".xpi.tmp")
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                for source in sorted(extension.rglob("*")):
                    if source.is_symlink():
                        raise ProfileValidationError("Extension symlinks are not supported")
                    if source.is_file():
                        archive.write(source, source.relative_to(extension).as_posix())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    # Restored profiles must not activate extensions absent from the current policy.
    for previous in directory.glob("*.xpi"):
        if previous not in expected:
            previous.unlink()
    return {
        "devtools.debugger.remote-enabled": True,
        "devtools.debugger.prompt-connection": False,
        "devtools.debugger.force-local": True,
    }


def webkit_rules(policy: TrafficPolicy, base_url: str | None) -> list[dict]:
    """WebKit Content Extensions JSON; native resource types, never JS interception."""
    types = ["media", "font"]
    if policy.version == 1:
        types += ["image"]
    if policy.block_stylesheets:
        types.append("style-sheet")
    rules = [{"trigger": {"url-filter": ".*", "resource-type": types}, "action": {"type": "block"}}]
    if policy.level != "metadata_only":
        if policy.version == 2:
            rules.append(
                {
                    "trigger": {"url-filter": ".*", "resource-type": ["image"]},
                    "action": {"type": "block"},
                }
            )
            if base_url:
                rules.append(
                    {
                        "trigger": {
                            "url-filter": origin_pattern(base_url),
                            "resource-type": ["image"],
                        },
                        "action": {"type": "ignore-previous-rules"},
                    }
                )
        for pattern in ADS_AND_TRACKERS_BLACKLIST:
            host, _, path = pattern.partition("/")
            trigger: dict = {
                "url-filter": r"^https?://([^/]+\.)?"
                + re.escape(host)
                + r"(:[0-9]+)?/"
                + re.escape(path),
            }
            rules.append({"trigger": trigger, "action": {"type": "block"}})
        if policy.version == 1:
            for host in [
                "ya.ru",
                "clck.yandex.ru",
                "passport.yandex.ru",
                *([_hostname(base_url)] if base_url else []),
            ]:
                # WebKit unless-domain tests the document domain, not the requested
                # host. Ordered URL exceptions preserve first-party scripts/XHRs.
                rules.append(
                    {
                        "trigger": {
                            "url-filter": r"^https?://([^/:]+\.)?"
                            + re.escape(host)
                            + r"(:[0-9]+)?/",
                            "resource-type": ["document", "script", "raw", "style-sheet"],
                        },
                        "action": {"type": "ignore-previous-rules"},
                    }
                )
            if policy.block_stylesheets:
                rules.append(
                    {
                        "trigger": {"url-filter": ".*", "resource-type": ["style-sheet"]},
                        "action": {"type": "block"},
                    }
                )
    return rules


def webkit_filter_environment(rules: Path, environment: dict[str, str]) -> dict[str, str]:
    library = Path(
        os.getenv(
            "QA_WEBKIT_FILTER_LIBRARY",
            str(
                TEMPLATE.parent / "native" / "libqa_content_filter.so",
            ),
        )
    ).resolve()
    if not library.is_file() and platform.system() == "Linux":
        build_webkit_filter(library)
    if not library.is_file():
        raise ProfileValidationError("Native WebKit content blocker is not built for this worker")
    cache = rules.parent / "webkit-cache"
    cache.mkdir(parents=True, exist_ok=True)
    status = rules.parent / "webkit-filter-error"
    status.unlink(missing_ok=True)
    # Preserve worker-provided native transport/privacy hooks when adding the bridge.
    # Keep drive-letter colons intact when validating Linux hooks on Windows.
    preloads = [
        path
        for path in re.split(r"\s+|(?<!\b[A-Za-z]):", environment.get("LD_PRELOAD", ""))
        if path
    ]
    if str(library) not in preloads:
        preloads.append(str(library))
    return {
        **environment,
        "LD_PRELOAD": " ".join(preloads),
        "QA_WEBKIT_FILTER_RULES": str(rules),
        "QA_WEBKIT_FILTER_CACHE": str(cache),
        "QA_WEBKIT_FILTER_STATUS": str(status),
    }


def validate_webkit_filter(rules: Path) -> None:
    if (rules.parent / "webkit-filter-error").exists():
        raise ProfileValidationError("WebKit rejected the native content rules")


def build_webkit_filter(library: Path | None = None) -> None:
    """Build atomically on native Linux; Chromium keeps its independent MV3 path."""
    library = library or TEMPLATE.parent / "native" / "libqa_content_filter.so"
    if platform.system() != "Linux" or library.is_file():
        return
    try:
        with tempfile.TemporaryDirectory(dir=library.parent) as directory:
            target = Path(directory) / library.name
            subprocess.run(
                [
                    "cc",
                    "-shared",
                    "-fPIC",
                    "-O2",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(TEMPLATE.parent / "native" / "webkit_filter.c"),
                    "-o",
                    str(target),
                    "-ldl",
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            target.replace(library)
    except (OSError, subprocess.SubprocessError):
        raise ProfileValidationError(
            "Native WebKit filter build failed; install cc or use Chromium with MV3"
        ) from None
