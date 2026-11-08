# Installation and browser preparation

English · [Russian translation](ru/INSTALLATION.md)

## Dependencies

Use Python 3.12+, pip, and a dedicated virtual environment.
`pip install -c requirements.lock -e .` installs runtime dependencies;
`pip install -c requirements.lock -e '.[dev]'` also installs tests, Ruff, mypy, and build tools.
Browser binaries are not included in the wheel. Direct versions are pinned in
pyproject; `requirements.lock` records the transitive runtime dependency snapshot.

| Tool | Purpose |
|---|---|
| Playwright 1.62.0 | BrowserContext/Page, emulation, CDP, real browsers |
| Camoufox 0.5.8 | Persistent native Firefox fingerprints |
| BrowserForge 1.2.4 | Fingerprint generation dependency; not a standalone JS override |
| Pydantic / pydantic-settings | Models, configuration validation, environment variables |
| httpx[socks] | Provider APIs and auxiliary HTTP operations |
| websockets | Separate Chromium CDP connection |
| PyYAML | Extracted low-level scenario models |
| psutil | Runtime process/resource observations |
| tzdata | Portable IANA time zones, including Windows |
| pytest / Ruff / mypy / build | Regression tests, linting, types, wheel/sdist builds |

## Chromium

```bash
syntetic-core prepare --engine chromium
```

This installs the browser for the pinned Playwright version and patches only the
Playwright driver in the current Python environment. On Linux, install system
libraries with `python -m playwright install --with-deps chromium`, then run
`python -c 'from syntetic_core.cli import install; install()'`.

To approximate the source Linux image's system font set, also install `fonts-roboto`
and `fonts-noto-color-emoji` with your OS package manager. JavaScript font filtering
does not install fonts or replace their CSS metrics.

Preparation is idempotent. Stop active sessions before patching their environment.
Unsupported driver layouts/versions fail explicitly. Playwright's `page.workers`
list is not a complete registry of targets owned by the separate Chromium controller.

## Camoufox

`tools/setup_browser.py` and `tools/browser-release.json` were copied from the source
project. The installer validates the pinned `156.0.1-beta.35` archive with SHA-256,
never silently accepts another build, and prepares the fingerprint model, including
support for Unicode Windows paths.

```bash
python tools/setup_browser.py --install-dir build/native-browser
```

Then supply an absolute installation path:

```python
from pathlib import Path
from syntetic_core import CoreSettings

settings = CoreSettings(camoufox_install_path=Path("build/native-browser").resolve())
```

To prepare model data only: `python tools/setup_browser.py --prepare-data-only`.
This is a separate download; installing the camoufox Python package is insufficient.
If installing from a wheel, obtain the installer from this project's source archive/sdist.

## WebKit / iOS

```bash
python -m playwright install --with-deps webkit
syntetic-core doctor
```

Linux requires GStreamer and codecs compatible with Playwright WebKit. Native
WebAudio/MediaDevices/SpeechSynthesis and WAV/H.264/AAC checks must pass before
`webkit_full_native_v1` is advertised. Native filtering needs a C compiler and the
system loader; the C source is included and compiled for the current architecture.

WebKit is prohibited on Windows. A target OS field or installed binary cannot
bypass this rule. No new standalone macOS verification has been performed.

## Linux ARM64

```python
settings = CoreSettings(experimental_arm64=True, production_mode=False)
```

Engine binaries, a display for headful sessions, and native extensions must actually
work. Historical Pi evidence does not constitute acceptance of this standalone package.

## Headful mode and launch constraints

Use `CoreSettings(browser_headless=False)` for a visible browser. Linux requires a
working DISPLAY or separately configured Xvfb. A headful model in source code is not
proof of a successful runtime smoke check.

The extracted factory retains the source product's Chromium flags, including
`--disable-gpu` and `--no-sandbox`. The latter assumes trusted content and an isolated
worker environment. The source platform's full supervisor/cgroups and Docker sandbox
are not part of this package. Untrusted content needs a separately prepared isolated
executor and a validated sandbox policy.

## Independence from the source checkout

The installed package imports only `syntetic_core`, the standard library, and declared
dependencies. It does not need the original project's `.env`, database, profiles,
build-directory binaries, or Python modules. Playwright may share its normal per-user
browser binary cache across projects; that is not a source-checkout dependency.
