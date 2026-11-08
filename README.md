# Syntetic Core

English · [Russian documentation](docs/ru/README.md)

**A standalone Python core for browser automation with persistent, coherent device
identities.** The project name is intentionally spelled `Syntetic Core`; the Python
package is `syntetic_core`, and the command is `syntetic-core`.

Extracted from the local Synthetic Sessions project on November 8, 2026, this package
preserves its browser implementation: device recipes, Chromium/CDP, Camoufox/Firefox,
WebKit/iOS, JavaScript API emulation, environment checks, isolated storage, and
behavior tools. It is a specific implementation snapshot with a standalone public API.

Use it for dynamic-page scraping, repeatable mobile-layout tests, persistent
signed-in sessions, UI-based data collection, and browser workflows. Persistent
cookies and localStorage reduce repeated authentication and setup. Coherent profiles
reduce accidental environment differences between visits. Performance and success
depend on the site, browser, network, and available resources; no comparative scraping
speed benchmark has been completed.

## Features

- Real browser engines through Playwright **1.62.0** and Camoufox **0.5.8**.
- Desktop Windows/macOS/Linux, Android, iPhone/iPad, and supported foldable presets.
- Linked OS, model, geometry, DPR, CPU, GPU, and Client Hints architecture recipes.
- Shared Canvas, function representation, webdriver, and Chromium hardware API layers.
- Separate early initialization of dedicated/shared/service/nested Chromium Workers.
- Persistent profiles with checksums, saved seeds, and OS file locks.
- Native browser TLS through a local SOCKS5 gateway with exact host authorization.
- HTTP/HTTPS/SOCKS5 proxies and extensible IP rotation through provider APIs.
- Typing, cursor, scrolling, and explicit UX activity helpers.
- Native resource filters and low-level live QA condition/replay tools.

Local use requires no PostgreSQL, Redis, FastAPI server, Dashboard, or Docker.
The controller, distributed leases, S3/Mesh, cookie incubation, quotas, external
analytics, and access-challenge recognition service remain in the source product.

## Requirements

Python **3.12+**. The standalone package has been tested on Windows x86-64 with
Chromium. Linux x86-64 is the source system's primary server platform. Linux ARM64
requires compatible binaries and `experimental_arm64=True`. macOS code is included
but has not been tested in this standalone project. WebKit is prohibited on Windows,
regardless of the profile's target OS.

Browser installation and driver patching are explicit preparation steps. Sessions
do not download browsers or modify a running driver automatically.

## Installation

Windows PowerShell, from the project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c requirements.lock -e ".[dev]"
syntetic-core prepare --engine chromium
```

Linux/macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements.lock -e '.[dev]'
python -m playwright install --with-deps chromium
python -c 'from syntetic_core.cli import install; install()'
```

`prepare` installs the Playwright browser and the checked Worker target ownership
patch. The patch supports exactly Playwright 1.62.0; another version requires
revalidation. Changing the browser version may require a new profile.

See [INSTALLATION.md](docs/INSTALLATION.md) for Camoufox and WebKit setup.

## Quick start

Capability discovery runs real local browser smoke checks and may take several minutes:

```bash
syntetic-core doctor
syntetic-core create --id catalog --family desktop --backend playwright
syntetic-core --allow-host example.com open catalog https://example.com
```

Hosts must be authorized explicitly. `example.com` is a short demonstration; for an
actual scraping job, allow the exact target and resource hosts it needs. Authorizing
`example.com` does not authorize `www.example.com` or every subdomain.

## Python API: scraping

```python
import asyncio
from syntetic_core import CoreSettings, SynteticCore

async def main():
    core = SynteticCore(
        "data/profiles",
        settings=CoreSettings(allowed_target_hosts=["example.com"]),
    )
    # Create once; reuse the same ID on subsequent runs.
    try:
        core.load_profile("catalog")
    except FileNotFoundError:
        await core.create_profile("catalog", family="desktop")

    async with core.session("catalog") as session:
        await session.goto("https://example.com")
        print(await session.page.locator("h1").all_text_contents())
        links = await session.page.locator("a[href]").evaluate_all(
            "nodes => nodes.map(a => ({text:a.textContent.trim(), url:a.href}))"
        )
        print(links)

asyncio.run(main())
```

`session.page` and `session.context` are regular Playwright objects. Use locators,
response waits, tabs, downloads, and DOM extraction normally. `session.goto()` also
checks URL authorization and environment consistency after navigation.

Profiles allow repeat visits and retain browser state by default. For a single-use
new-visitor test, call `create_profile(..., fresh=True)` and pass `base_url` to
`session()`. Reusing such a profile is rejected. A new profile receives a new
identity; existing profiles are not regenerated.

## Android, iOS, and Camoufox

```python
await core.create_profile("android", family="android", backend="playwright")
await core.create_profile("desktop-firefox", family="desktop", backend="camoufox")
# Linux/macOS only, with verified WebKit and native media support:
await core.create_profile("iphone", family="ios", backend="playwright")
```

An unavailable mode raises a compatibility error. The core does not silently
replace WebKit with Chromium or open a profile with another browser build.

## Proxies and IP rotation

```python
import os
from pydantic import SecretStr
from syntetic_core import CoreSettings, HttpRotationProvider, ProxyConfig, SynteticCore

proxy = ProxyConfig(
    id="mobile-1",
    server=os.environ["PROXY_SERVER"],
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]),
    kind="mobile",
)
core = SynteticCore(settings=CoreSettings(
    proxies=[proxy], proxy_required=True,
    allowed_target_hosts=["example.com", "api.ipify.org"],
))
provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",  # Match your provider's documented method.
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
    # If needed: success_field="data.success", success_value=True
)
# Inside an async function, between sessions:
# result = await core.rotate_ip("mobile-1", provider,
#                               probe_url="https://api.ipify.org?format=json")
# await core.create_profile("mobile-profile", family="android", proxy_id="mobile-1")
```

Rotation is confirmed by observing a different public IP through the assigned
proxy. A provider API response alone is not proof. Active sessions hold a channel
lock; rotating a busy channel fails immediately. Proxy errors never trigger a
direct-connection fallback. See [examples/rotate_ip.py](examples/rotate_ip.py) and
the extension contract in [PROXIES.md](docs/PROXIES.md).

## Examples

| File | Purpose |
|---|---|
| [parse_page.py](examples/parse_page.py) | Extract headings and links into JSON |
| [parallel_sessions.py](examples/parallel_sessions.py) | Bounded concurrency with a separate profile per task |
| [rotate_ip.py](examples/rotate_ip.py) | Rotate via API, verify the IP, and open an Android session |

## Documentation

- [Installation and platforms](docs/INSTALLATION.md)
- [Architecture and lifecycle](docs/ARCHITECTURE.md)
- [Emulated data and limitations](docs/EMULATION.md)
- [API, settings, and profiles](docs/USAGE.md)
- [Proxies and provider APIs](docs/PROXIES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Extraction provenance and differences](docs/EXTRACTION.md)
- [Codex and Claude Code skill](docs/AGENT_SKILLS.md)
- [Verification results](VERIFICATION.md)
- [Russian translation](docs/ru/README.md)

## Use as an agent skill

```bash
python tools/install_agent_skills.py --agent both
```

Invoke `$syntetic-core` in Codex or `/syntetic-core` in Claude Code. The shared
skill includes a runtime launcher and a bundled wheel for use without this checkout.
See [agent skill setup](docs/AGENT_SKILLS.md) for locations and update behavior.

## Checks and builds

```bash
python -m pytest -m 'not browser' -q
python -m ruff check src tests tools examples skills
python -m ruff format --check src tests tools examples skills
python -m mypy
python -m build
```

Enable the real browser test explicitly; it uses a local HTTP fixture:

```powershell
$env:SYNTETIC_CORE_RUN_BROWSER="1"
python -m pytest tests/test_browser.py -q
```

On Linux: `SYNTETIC_CORE_RUN_BROWSER=1 python -m pytest tests/test_browser.py -q`.

## Limitations and licensing

This emulates a browser environment; it does not run Android/iOS or a virtual
machine with the target OS. It does not guarantee equivalence to a physical device,
a new human visitor, or acceptance by a third-party site's checks. Actual GPU limits,
performance, some Worker APIs, and rendering remain properties of the host.
Use the core for resources and actions you are authorized to access.

Credentials, profiles, cookies, and model data are excluded from the distribution.
No separate open-source license has been assigned to this extracted project.
See [NOTICE.md](NOTICE.md) and [THIRD_PARTY.md](THIRD_PARTY.md). Before distribution,
choose licensing terms for your own code and account for dependency licenses.
