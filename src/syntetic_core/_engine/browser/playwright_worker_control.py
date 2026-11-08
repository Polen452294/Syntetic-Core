"""Checked Playwright 1.62 shim: one CDP owner must release worker startup.

Playwright resumes/detaches worker targets on its independent connection before
our controller can initialize them. Restrict its auto-attach filter only when
the browser was launched with OWNER_FLAG. Ordinary Playwright launches keep their
original behavior. Install at image build time, never mutate a live driver.
"""

import argparse
from functools import cache
from importlib.metadata import version
from pathlib import Path

import playwright

from syntetic_core._engine.errors import ProfileValidationError

OWNER_FLAG = "--synthetic-worker-cdp-owner"
MARKER = "// synthetic-sessions worker CDP ownership v1"
PARAMS = "{ autoAttach: true, waitForDebuggerOnStart: true, flatten: true }"


def driver_path() -> Path:
    return Path(playwright.__file__).parent / "driver/package/lib/coreBundle.js"


def patched_source(source: str) -> str:
    if MARKER in source:
        return source
    replacements = [
        (
            f'this._client.send("Target.setAutoAttach", {PARAMS})',
            f'this._client.send("Target.setAutoAttach", '
            f"syntheticWorkerAttach(this._crPage._browserContext._browser, {PARAMS}))",
            1,
        ),
        (
            f'session2.send("Target.setAutoAttach", {PARAMS})',
            f'session2.send("Target.setAutoAttach", syntheticWorkerAttach(browser, {PARAMS}))',
            2,
        ),
    ]
    for before, after, count in replacements:
        if source.count(before) != count:
            raise RuntimeError(
                "Unsupported Playwright driver layout; worker guard was not installed"
            )
        source = source.replace(before, after)
    return (
        source
        + "\n"
        + MARKER
        + "\n"
        + """
function syntheticWorkerAttach(browser, params) {
  if (!browser.options.originalLaunchOptions.args?.includes('--synthetic-worker-cdp-owner'))
    return params;
  return {...params, filter: [
    {type: 'tab', exclude: true},
    {type: 'worker', exclude: true},
    {type: 'shared_worker', exclude: true},
    {type: 'service_worker', exclude: true}, {}
  ]};
}
"""
    )


def install() -> None:
    if version("playwright") != "1.62.0":
        raise RuntimeError("Worker startup guard requires the pinned Playwright 1.62.0")
    path = driver_path()
    source = path.read_text(encoding="utf-8")
    patched = patched_source(source)
    if patched != source:
        path.write_text(patched, encoding="utf-8")


@cache
def require_worker_control() -> None:
    if version("playwright") != "1.62.0" or MARKER not in driver_path().read_text(encoding="utf-8"):
        raise ProfileValidationError(
            "Chromium worker guard missing; run "
            "syntetic-core prepare --engine chromium before starting sessions"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", required=True)
    parser.parse_args()
    install()
