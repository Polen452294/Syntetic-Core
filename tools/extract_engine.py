"""Reproduce the initial extraction from an explicit Synthetic Sessions checkout."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "src/syntetic_core/_engine"
STOPS = {
    "backend.app.core.config",
    "backend.app.services.proxies",
    "backend.app.services.profile_lock",
    "backend.app.services.targets",
    "worker.ipc",
    "worker.scenarios.engine",
}


def destination(module: str) -> str:
    prefixes = {
        "backend.app.services.": "",
        "backend.app.core.": "",
        "backend.app.schemas.": "schemas.",
        "worker.browser.": "browser.",
        "worker.actions.": "actions.",
        "worker.scenarios.": "scenarios.",
        "worker.": "",
    }
    for prefix, replacement in prefixes.items():
        if module.startswith(prefix):
            return "syntetic_core._engine." + replacement + module[len(prefix) :]
    raise ValueError(module)


def main(source: Path) -> None:
    pending = [
        "worker.browser.factory",
        "worker.browser.experiment_replay",
        "worker.capabilities",
        "backend.app.services.persona_randomization",
        "worker.actions.behavior",
    ]
    sources: dict[str, str] = {}
    while pending:
        module = pending.pop()
        if module in sources:
            continue
        path = source.joinpath(*module.split(".")).with_suffix(".py")
        text = path.read_text(encoding="utf-8-sig")
        if module == "worker.capabilities":
            text = text.replace("from worker.diagnostics.adapters import ASSETS", "")
            begin, end = (
                text.index("def installed_adapters"),
                text.index("async def discover_capabilities"),
            )
            text = (
                text[:begin]
                + "def installed_adapters() -> list[str]:\n"
                + '    return ["environment", "network"]\n\n\n'
                + text[end:]
            )
        sources[module] = text
        if module in STOPS:
            continue
        for node in ast.walk(ast.parse(text)):
            names = (
                [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else ([a.name for a in node.names] if isinstance(node, ast.Import) else [])
            )
            pending.extend(name for name in names if name.startswith(("backend.", "worker.")))

    # Keep runtime models/selection/probes; leave DB health/accounting in the source product.
    text = sources["backend.app.services.proxies"]
    text = text[: text.index("class ProxyProbeResult")]
    text = re.sub(r"^from sqlalchemy[^\n]*\n", "", text, flags=re.M)
    text = text.replace("from backend.app.models import ProxyHealth\n", "")
    sources["backend.app.services.proxies"] = text

    # Reuse the exact OS locking implementation without importing Redis coordination.
    text = sources["backend.app.services.profile_lock"]
    start = text.index("        if (\n")
    end = text.index("    @property", start)
    text = text[:start] + text[end:]
    sources["backend.app.services.profile_lock"] = text

    text = sources["backend.app.services.targets"]
    text = text[: text.index("def authorize_scenario")]
    text = text.replace(
        "from worker.scenarios.validation import YANDEX_HOME, ScenarioDefinition\n", ""
    )
    sources["backend.app.services.targets"] = text

    text = sources["worker.ipc"]
    text = text[: text.index("def proxy_transport")]
    text = re.sub(r"^from (?:backend|pydantic)[^\n]*\n", "", text, flags=re.M)
    sources["worker.ipc"] = text
    sources[
        "worker.scenarios.engine"
    ] = '''"""Standalone event sink boundary for the copied live-condition engine."""
from typing import Any, Protocol

class EventSink(Protocol):
    async def emit(self, event_type: str, **kwargs: Any) -> None: ...
'''
    text = sources["backend.app.core.tracing"]
    text = re.sub(r"^from starlette[^\n]*\n", "", text, flags=re.M)
    sources["backend.app.core.tracing"] = text[: text.index("class TraceMiddleware")]
    text = sources["backend.app.core.sre"]
    sources["backend.app.core.sre"] = text[: text.index("def snapshot")]

    # Include only settings referenced by the runtime, with source validation bounds.
    needed = {
        "fresh_session_profiles",
        "profile_randomization",
        "browser_start_timeout",
        "browser_headless",
        "experimental_arm64",
        "production_mode",
    }
    for module, text in sources.items():
        if module == "backend.app.core.config":
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Attribute):
                needed.add(node.attr)
            if isinstance(node, ast.Dict):
                needed.update(
                    k.value
                    for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                )
    tree = ast.parse(sources["backend.app.core.config"])
    original = sources["backend.app.core.config"]
    settings = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
    fields = [
        ast.get_source_segment(original, n)
        for n in settings.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id in needed
    ]
    # No ambient .env, no DB/Redis dependencies, and no implicit direct bypass.
    header = '''"""Runtime-only settings extracted from Synthetic Sessions."""
from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from syntetic_core._engine.personas import DeviceConfig, DeviceFamily
from syntetic_core._engine.proxies import ProxyConfig

'''
    randomization = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "ProfileRandomizationConfig"
    )
    diagnostics = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DiagnosticsConfig"
    )
    config = (
        header
        + ast.get_source_segment(original, diagnostics)
        + "\n\n"
        + ast.get_source_segment(original, randomization)
        + "\n\nclass Settings(BaseSettings):\n"
    )
    config += (
        '    model_config = SettingsConfigDict(env_prefix="SYNTETIC_CORE_", '
        'env_nested_delimiter="__", extra="forbid", hide_input_in_errors=True)\n'
    )
    config += "\n".join("    " + line for field in fields for line in (field or "").splitlines())
    config += """

    @property
    def use_fresh_session_profiles(self) -> bool:
        return self.fresh_session_profiles or self.profile_randomization.enabled

    @model_validator(mode="after")
    def standalone_only(self) -> "Settings":
        if self.distributed_workers or self.profile_storage_shared or self.profile_lock_distributed:
            raise ValueError("Standalone core supports local profile volumes and OS locks")
        if self.controller_url or self.profile_archive_enabled:
            raise ValueError("Controller/archive orchestration belongs to the source platform")
        if self.direct_transport:
            raise ValueError("Use proxies=[] for direct transport; proxy bypass is disabled")
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()
"""
    sources["backend.app.core.config"] = config

    receipts = []
    for module, text in sorted(sources.items()):
        for old in sorted(sources, key=len, reverse=True):
            text = text.replace(old, destination(old))
        target = ROOT / "src" / Path(*destination(module).split(".")).with_suffix(".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        path = source.joinpath(*module.split(".")).with_suffix(".py")
        receipts.append(
            {
                "source": str(path.relative_to(source)).replace("\\", "/"),
                "destination": str(target.relative_to(ROOT)).replace("\\", "/"),
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    for relative in [
        "device_emulation.js",
        "native_functions.js",
        "assets/webkit-native.mp4",
        "extensions/content_filter/manifest.json",
        "extensions/content_filter/rules.json",
        "extensions/native/webkit_filter.c",
    ]:
        original_path = source / "worker/browser" / relative
        target = BASE / "browser" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original_path.read_bytes())
        receipts.append(
            {
                "source": "worker/browser/" + relative,
                "destination": str(target.relative_to(ROOT)).replace("\\", "/"),
                "source_sha256": hashlib.sha256(original_path.read_bytes()).hexdigest(),
            }
        )
    for folder in (ROOT / "src/syntetic_core").rglob("*"):
        if folder.is_dir() and folder.name not in {
            "assets",
            "extensions",
            "content_filter",
            "native",
        }:
            init = folder / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
    (ROOT / "extraction-manifest.json").write_text(
        json.dumps(
            {
                "project": "Syntetic Core",
                "snapshot_date": "2026-11-08",
                "policy": "Source hashes identify the extraction input, not deployment state.",
                "files": receipts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Extracted {len(sources)} modules and 6 browser resources")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    main(parser.parse_args().source.resolve())
