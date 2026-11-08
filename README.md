# Syntetic Core

English · [Russian documentation](docs/ru/README.md)

**A high-stealth anti-detect browser automation engine for simulating authentic human browser sessions undetectable by modern anti-fraud, anti-bot, and behavioral analysis systems.** The project name is intentionally spelled `Syntetic Core`; the Python package is `syntetic_core`, and the CLI command is `syntetic-core`.

Extracted directly on November 8, 2026, from a production enterprise behavioral factor (ПФ / Behavioral Factors simulation and anti-fraud bypass) system, this package isolates the core browser runtime: full-spectrum fingerprint spoofing, coherent device recipes, deep CDP / worker patching, persistent cookie jars, native browser TLS networking, and realistic human behavior emulation.

It is specifically engineered to bypass cutting-edge bot-mitigation and behavioral analysis platforms (including Cloudflare Turnstile / Bot Management, DataDome, Akamai Bot Manager, Kasada, Yandex SmartCaptcha & Anti-Fraud, Google reCAPTCHA v2/v3/Enterprise, CreepJS, FingerprintJS Pro, and Pixelscan).

## Key Capabilities

- **Real Browser Engines:** Powered by Playwright **1.62.0** (with custom CDP target patches), **Camoufox 0.5.8** (hardened anti-detect Firefox with C++ engine modifications), and native **WebKit** (for iOS/macOS layout and runtime authenticity).
- **Full-Stack Fingerprint Spoofing & Randomization:**
  - **Canvas 2D Protection:** Profile-deterministic subpixel text shift (±0.02 px) preventing canvas hash clustering without triggering synthetic entropy traps.
  - **WebGL 1 & 2 Spoofing:** Realistic unmasked vendor, unmasked renderer, extensions, and context capabilities tailored to matched hardware recipes.
  - **Web Audio API:** Stable mathematical noise injected into AudioBuffer and DynamicsCompressor readings to defeat audio fingerprinting.
  - **Client Hints (`Sec-CH-UA`):** Accurate browser brand versions, full version lists, platform, architecture, bitness, and mobile flags aligned across HTTP headers and JS APIs.
  - **Hardware Metrics:** Realistic `navigator.hardwareConcurrency` (CPU cores) and `navigator.deviceMemory` (RAM) matching the emulated device.
  - **Battery & MediaDevices:** Authentic `BatteryManager` states and consistent `enumerateDevices` video/audio device lists.
  - **Speech & Fonts:** OS-consistent system voices (`speechSynthesis`) and `FontFaceSet` font filtering to prevent OS font leaking.
  - **Sensors & Multitouch:** Realistic 5-point multitouch for mobile, plus Accelerometer, Gyroscope, and Magnetometer emulation via CDP.
- **CDP & Anti-Automation Leak Elimination:**
  - Playwright driver patch that overrides target resume/detach ownership, preventing CDP race conditions.
  - Neutralizes `navigator.webdriver` (strictly `false`), automation flags, and known automation properties (`cdc_`, runtime inspector hooks).
  - Proxy/WeakMap layer providing `[native code]` representations for all patched JS functions and getters (`Function.prototype.toString` looks 100% native).
- **Early WebWorker Fingerprint Injection:**
  - CDP controller recursively auto-attaches to dedicated, shared, service, and nested WebWorkers.
  - Pauses workers before script execution and injects CPU, deviceMemory, userAgent, Client Hints, and WebGL offscreen canvas configuration before any fingerprinting script runs inside background threads.
- **Persistent Profiles, Cookie Jars & Session Warming:**
  - True persistence of cookies, `localStorage`, `sessionStorage`, `IndexedDB`, and browser disk cache.
  - Allows progressive "cookie warming" and trust building across repeated sessions to eliminate security challenges and recurring logins.
  - Deterministic profile integrity with SHA config hashes and cross-process OS file locks (`ProfileLock`).
- **Coherent Hardware Recipes (1000+ Device Presets):**
  - Rigid cross-property coherence linking OS, GPU, CPU architecture, screen geometry, viewport, DPR, and Client Hints.
  - Prevents impossible hardware combinations that anti-fraud systems flag (e.g. Apple Silicon GPU on Windows, mobile user agent with desktop touch points, mismatched DPR/resolutions).
  - Presets cover Windows, macOS (Apple Silicon M1/M2 and Intel), Linux, iPhone/iPad, Android phones (hundreds of exact Samsung Galaxy, Google Pixel, Xiaomi models), and foldables.
- **Human Behavioral Simulation (ПФ / Behavioral Factors):**
  - Smooth, non-linear cursor movements along Bezier curves with natural micro-jitter, velocity variations, and overshoot.
  - Human-like typing cadence with variable inter-keystroke intervals, realistic typos, and correction delays.
  - Natural inertial scrolling with deceleration curves and reading pauses.
  - Built-in `UXActivityDispatcher` and `maintain_presence()` for realistic dwell time and on-page presence.
- **Mobile Proxies, IP Rotation & Network Stealth:**
  - **Native Browser TLS:** The browser itself negotiates TLS over TCP, preserving genuine browser JA3/JA4/TLS fingerprints without synthetic Python TLS anomalies.
  - Local SOCKS5 loopback target proxy with strict target host allowlisting.
  - Hardware modem channel locking (`proxy_channels`) ensuring multiple ports sharing a physical mobile modem never rotate simultaneously.
  - HTTP API-driven mobile proxy IP rotation with mandatory public IP confirmation probe before session handover.

> [!NOTE]
> Local standalone use requires no PostgreSQL, Redis, FastAPI backend, Dashboard, or Docker. Distributed clustering, S3 mesh pipelines, and external captcha-solving services remain in the enterprise parent system.

## Requirements

- Python **3.12+**.
- Tested primarily on **Windows x86-64** and **Linux x86-64**.
- Linux ARM64 requires compatible binaries and `experimental_arm64=True`.
- WebKit engine requires Linux or macOS (WebKit is blocked on Windows).

## Installation

### Windows PowerShell

From the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c requirements.lock -e ".[dev]"
syntetic-core prepare --engine chromium
```

### Linux / macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements.lock -e '.[dev]'
python -m playwright install --with-deps chromium
python -c 'from syntetic_core.cli import install; install()'
```

The `prepare` command installs the browser and applies the required Playwright **1.62.0** worker target ownership patch.

See [INSTALLATION.md](docs/INSTALLATION.md) for Camoufox (anti-detect Firefox) and WebKit setup.

## Quick Start (CLI)

Verify environment capabilities and launch an anti-detect session:

```bash
# Verify local browser runtimes and fingerprint capabilities
syntetic-core doctor

# Create a coherent persistent profile
syntetic-core create --id my-stealth-profile --family desktop --backend playwright

# Open a session with host authorization
syntetic-core --allow-host example.com open my-stealth-profile https://example.com
```

Hosts must be authorized explicitly via `--allow-host`. Authorizing `example.com` does not implicitly authorize `www.example.com` or other subdomains.

## Python API: Anti-Detect Session & Automation

```python
import asyncio
from syntetic_core import CoreSettings, SynteticCore

async def main():
    # Initialize core with target domain authorization
    core = SynteticCore(
        "data/profiles",
        settings=CoreSettings(allowed_target_hosts=["example.com"]),
    )

    # Create profile once; reuse ID to preserve cookies and session trust
    try:
        core.load_profile("user-01")
    except FileNotFoundError:
        # Generates a fully coherent hardware recipe with unique seeds
        await core.create_profile("user-01", family="desktop")

    # Launch browser with full fingerprint protection and CDP stealth
    async with core.session("user-01") as session:
        # goto() verifies network authorization, DOM readiness, and environment stealth
        await session.goto("https://example.com")
        
        # Human-like interaction via session.behavior
        # session.page and session.context are standard Playwright objects
        print("Page title:", await session.page.title())
        
        # Example of human presence emulation
        await session.maintain_presence(seconds=5.0)

asyncio.run(main())
```

`session.page` and `session.context` provide standard Playwright controls (locators, tabs, downloads, evaluators). Every page automatically inherits the anti-detect layers, canvas shifts, WebGL spoofs, worker hooks, and `[native code]` shims.

### Reusable vs. Fresh Profiles

- **Persistent Profiles (Default):** Cookies, storage, and identity persist across launches. Ideal for warming profiles, retaining account logins, and accumulating anti-fraud trust scores.
- **Fresh Single-Use Profiles (`fresh=True`):** Creates an isolated one-time identity with virgin storage for clean-slate testing.

## Mobile Devices, Camoufox & WebKit

```python
# Realistic Android device profile (Samsung Galaxy, Google Pixel, etc.)
await core.create_profile("mobile-android", family="android", backend="playwright")

# Camoufox: Hardened Firefox with low-level C++ fingerprint defenses
await core.create_profile("stealth-firefox", family="desktop", backend="camoufox")

# iOS WebKit (Linux/macOS only):
await core.create_profile("ios-safari", family="ios", backend="playwright")
```

If an engine or target OS is unsupported on the current host, an explicit `RuntimeCompatibilityError` is raised rather than falling back to an inaccurate combination.

## Mobile Proxies & Verified IP Rotation

```python
import os
from pydantic import SecretStr
from syntetic_core import CoreSettings, HttpRotationProvider, ProxyConfig, SynteticCore

# Configure mobile proxy with modem serialization
proxy = ProxyConfig(
    id="mobile-modem-1",
    server=os.environ["PROXY_SERVER"],
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]),
    kind="mobile",
)

core = SynteticCore(
    settings=CoreSettings(
        proxies=[proxy],
        proxy_required=True,
        allowed_target_hosts=["example.com", "api.ipify.org"],
    ),
    proxy_channels={"mobile-modem-1": "modem-hardware-channel-A"},
)

# HTTP rotation provider based on your mobile proxy provider's API
provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
)

# Rotate IP between sessions and guarantee exit IP change before proceeding
# result = await core.rotate_ip("mobile-modem-1", provider, probe_url="https://api.ipify.org?format=json")
# print("Rotated to new exit IP:", result.new_ip)
```

IP rotation is only considered successful when an independent external probe through the proxy returns a different public IP. If the proxy fails, sessions never fall back to a direct connection, preventing accidental IP leakage.

## Examples

| File | Purpose |
|---|---|
| [parse_page.py](examples/parse_page.py) | Extract content with persistent identity |
| [parallel_sessions.py](examples/parallel_sessions.py) | Concurrent multi-profile execution with rate limiting |
| [rotate_ip.py](examples/rotate_ip.py) | Mobile proxy rotation, IP verification, and Android session launch |

## Documentation

- [Architecture & Lifecycle](docs/ARCHITECTURE.md)
- [Emulation Data, Fingerprints & Stealth Layers](docs/EMULATION.md)
- [API, Settings & Profiles](docs/USAGE.md)
- [Proxies, Modem Locking & IP Rotation](docs/PROXIES.md)
- [Installation & Platform Setup](docs/INSTALLATION.md)
- [Troubleshooting & Diagnostics](docs/TROUBLESHOOTING.md)
- [Provenance & Extraction Background](docs/EXTRACTION.md)
- [Codex & Claude Code Agent Skill](docs/AGENT_SKILLS.md)
- [Verification & Test Results](VERIFICATION.md)
- [Russian Documentation](docs/ru/README.md)

## Agent Skills (Codex & Claude Code)

```bash
python tools/install_agent_skills.py --agent both
```

Invoked via `$syntetic-core` in Codex or `/syntetic-core` in Claude Code. Includes runtime launcher scripts and bundled wheels for self-contained agent execution.

## Testing & Quality Assurance

```bash
# Unit test suite
python -m pytest -m 'not browser' -q

# Code quality and typing
python -m ruff check src tests tools examples skills
python -m ruff format --check src tests tools examples skills
python -m mypy

# Real browser anti-detect smoke test (uses local HTTP fixture)
$env:SYNTETIC_CORE_RUN_BROWSER="1"
python -m pytest tests/test_browser.py -q
```

## Security & Ethics Notice

This engine provides deep browser environment emulation, fingerprint spoofing, and automation stealth capabilities. It does not magically bypass every host constraint (real physical GPU hardware and low-level OS kernel differences remain host properties). Use Syntetic Core responsibly and strictly for targets, workflows, and accounts you are authorized to operate.
