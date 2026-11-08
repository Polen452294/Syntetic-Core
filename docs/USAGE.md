# API Reference & Anti-Detect Operation

English · [Russian translation](ru/USAGE.md)

## Core Class: `SynteticCore`

The main entry point manages profile storage, device generation, anti-detect capabilities discovery, and session execution.

```python
from syntetic_core import CoreSettings, SynteticCore

core = SynteticCore(
    profile_root="data/profiles",
    settings=CoreSettings(
        allowed_target_hosts=["example.com", "api.example.com"],
        browser_headless=False,
    ),
    proxy_channels={"mobile-port-1": "modem-A", "mobile-port-2": "modem-A"},
)
```

Use a single instance per `asyncio` event loop. Settings are validated and frozen at creation.

---

### `capabilities(refresh=False)`

Asynchronously inspects local runtimes, browser binaries, and supported anti-detect features (Chromium CDP patching, Camoufox C++ engine, WebKit decoders). Returns a cached manifest. Use `refresh=True` only after changing local browser binaries.

---

### `create_profile(...)`

Generates a fully coherent device identity, locks in fingerprint seeds, and creates the persistent profile folder.

```python
persona = await core.create_profile(
    "user-001",               # Profile ID; generates a UUID if None
    family="android",         # "desktop", "android", or "ios"
    backend="playwright",     # "playwright" (Chromium/WebKit) or "camoufox" (Firefox)
    proxy_id="mobile-1",      # Optional proxy identifier from Settings.proxies
    locale="en-US",
    timezone_id="America/New_York",
    fresh=False,              # False = persistent (retains cookies/storage); True = virgin single-use
)
```

- **Coherent Hardware Generation:** Automatically pairs compatible GPUs, CPUs, screen dimensions, DPR, and Client Hints architecture.
- **Persistent by Default (`fresh=False`):** Creates persistent storage (`browser-data/`) to retain cookies, session state, and history across runs for account warming and high anti-fraud trust.
- **Single-Use Mode (`fresh=True`):** Creates an ephemeral single-visit profile that rejects reuse after closing.

---

### `load_profile(id)`

Synchronously reads `profile.json` and verifies the SHA-256 `config_hash`. Validates that the device fingerprint has not been corrupted or tampered with.

---

### `session(id, base_url=None)`

Asynchronous context manager that initializes the browser, injects stealth layers, handles proxy channels, and yields an active session.

```python
async with core.session("user-001") as session:
    await session.goto("https://example.com")
    
    # Human typing simulation (per-character delays & typos)
    await session.behavior.type_text("input[name='q']", "anti-detect automation")
    
    # Human cursor movement along natural Bezier curves
    await session.behavior.click_element("button[type='submit']")
    
    # Natural inertial scroll down the page
    await session.behavior.scroll_smooth(delta_y=600)
    
    # Emulate human presence and dwell time (behavioral factors / ПФ)
    await session.maintain_presence(seconds=4.0)
```

Closing the context automatically flushes cookies, saves `localStorage` / `IndexedDB`, closes browser processes, and releases the OS file lock.

---

## `BrowserSession` Methods & Properties

| Attribute / Method | Description |
|---|---|
| `session.page` | Standard Playwright `Page` object (locators, tabs, downloads, DOM queries) with active anti-detect protections. |
| `session.context` | Standard Playwright `BrowserContext` with persistent cookies and isolated storage. |
| `session.behavior` | Built-in human behavioral simulator (Bezier mouse curves, human typing, inertial scrolling). |
| `session.persona` | The loaded `BrowserPersona` containing the hardware recipe, seeds, and device identity. |
| `session.connection` | Observed network transport and exit connection state. |
| `await session.goto(url)` | Navigates to URL, enforces the host allowlist, waits for DOM readiness, and performs an automatic stealth sanity check. |
| `await session.check_environment(page=None)` | Asserts that `navigator.webdriver === false`, CDP worker controllers are active, and no automation leaks have occurred. |
| `await session.maintain_presence(seconds)` | Emulates human presence through micro-movements, slight scrolls, and realistic dwell time to build behavioral score. |

---

## Core Settings

| Setting | Default | Purpose |
|---|---|---|
| `allowed_target_hosts` | `[]` | Strict allowlist of target domains and third-party resource hosts. |
| `trusted_local_target_hosts` | `[]` | Explicit authorization for localhost or private LAN endpoints. |
| `browser_headless` | `False` | Run browser in headless or visible window mode. |
| `browser_start_timeout` | `30.0` | Max seconds allotted for browser launch, CDP connection, and worker injection. |
| `navigation_timeout` | `15.0` | Navigation timeout applied to `session.goto()`. |
| `action_timeout` | `10.0` | Playwright locator and click action timeout. |
| `proxies` | `[]` | List of `ProxyConfig` objects available for profile assignment. |
| `proxy_required` | `False` | When `True`, prevents sessions from opening without a proxy (blocks direct connection leaks). |
| `camoufox_install_path` | `None` | Path to the pinned Camoufox anti-detect Firefox binary. |
| `traffic_optimizer_enabled` | `False` | Activates native resource filtering to block ads, trackers, or media. |

Environment variables use the `SYNTETIC_CORE_` prefix with `__` for nested objects:

```powershell
$env:SYNTETIC_CORE_BROWSER_HEADLESS="false"
$env:SYNTETIC_CORE_ALLOWED_TARGET_HOSTS='["example.com","auth.example.com"]'
```

---

## Behavioral Factors & Interaction Helpers (`session.behavior`)

The `behavior` helper simulates human interaction patterns (ПФ) that defeat anti-bot behavioral scoring:

- **`click_element(selector)`:** Calculates target element center coordinates and moves the cursor along a randomized Bezier curve before clicking.
- **`type_text(selector, text, wpm=180, error_rate=0.03)`:** Types text with natural inter-character delays, simulating occasional typos and backspace corrections.
- **`scroll_smooth(delta_y, steps=20)`:** Executes a smooth inertial scroll with deceleration physics rather than instantaneous DOM jumps.
- **`hover_element(selector)`:** Naturally sweeps the cursor across the viewport to hover over elements.

---

## Profile Backup & Portability

Because profiles are persistent, copying the `data/profiles/<id>/` folder preserves the full identity, including:
1. `profile.json` (device recipe and seeds)
2. `browser-data/` (all cookies, local storage, indexedDB, and cache)
3. `canvas-identity.json` & `session-hardware-identity.json` (deterministic fingerprint seeds)

Ensure no active sessions are running (`.locks/<id>.lock` is unlocked) before copying or archiving profile directories.
