# Anti-Detect Workflow Examples

## 1. Undetected Persistent Browser Session & Automation

Run with the interpreter reported by `scripts/runtime.py info` or via `python scripts/runtime.py python task.py`.

```python
import asyncio
import json
from pathlib import Path
from syntetic_core import CoreSettings, SynteticCore


async def main():
    # Authorize target domains and required CDN/API hosts
    core = SynteticCore(
        Path(".syntetic-core/profiles").resolve(),
        settings=CoreSettings(
            allowed_target_hosts=["example.com", "static.example.com"],
            browser_headless=False,
        ),
    )

    # Load existing profile to reuse cookies & session history, or create a new one
    try:
        core.load_profile("stealth-user")
    except FileNotFoundError:
        # Generates coherent hardware recipe (GPU, CPU, Client Hints, Canvas/Audio seeds)
        await core.create_profile("stealth-user", family="desktop", backend="playwright")

    # Launch browser with CDP worker interception, native code proxying, and anti-detect layers
    async with core.session("stealth-user") as session:
        # goto() verifies network authorization, DOM readiness, and absence of CDP leaks
        response = await session.goto("https://example.com")
        if response is None or response.status >= 400:
            raise RuntimeError(f"Navigation failed with status: {response.status if response else 'None'}")

        # Human-like interaction via session.behavior (defeats behavioral analysis / ПФ)
        # 1. Natural mouse movement along a Bezier curve to focus input
        await session.behavior.click_element("input[name='search']")
        
        # 2. Human typing with variable delays and simulated typo corrections
        await session.behavior.type_text("input[name='search']", "anti-detect automation")
        
        # 3. Inertial scroll with reading dwell time
        await session.behavior.scroll_smooth(delta_y=400)
        
        # 4. Emulate on-page presence
        await session.maintain_presence(seconds=3.0)

        # Standard Playwright DOM extraction
        items = await session.page.locator(".catalog-item").evaluate_all(
            "nodes => nodes.map(n => ({title: n.querySelector('h2')?.textContent.trim()}))"
        )

    # Persist extracted results (cookies and browser cache remain saved in profile storage)
    Path("results.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
```

---

## 2. Coherent Device Presets & Stealth Engines

```python
# Android Mobile (Samsung Galaxy, Google Pixel with 5-point multitouch & CDP sensors)
await core.create_profile("android-user", family="android", backend="playwright")

# Camoufox (Hardened Firefox with low-level C++ fingerprint defenses)
await core.create_profile("firefox-stealth", family="desktop", backend="camoufox")

# iOS / iPadOS WebKit (Linux/macOS only):
await core.create_profile("ios-safari", family="ios", backend="playwright")
```

Every profile enforces **device coherence**: the GPU model, screen geometry, DPR, CPU cores, RAM, and Client Hints architecture are tightly coupled so anti-bot heuristic systems never find conflicting parameters.

---

## 3. Mobile Proxies & Verified IP Rotation

```python
import os
from pydantic import SecretStr
from syntetic_core import CoreSettings, HttpRotationProvider, ProxyConfig, SynteticCore

# Configure mobile proxy with modem serialization channel
proxy = ProxyConfig(
    id="mobile-modem-1",
    server=os.environ["PROXY_SERVER"],
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]),
    kind="mobile",
)

core = SynteticCore(
    "/absolute/task/profiles",
    settings=CoreSettings(
        proxies=[proxy],
        proxy_required=True,  # Disallows direct connections to avoid real IP leaks
        allowed_target_hosts=["example.com", "api.ipify.org"],
    ),
    proxy_channels={"mobile-modem-1": "modem-channel-A"},
)

# HTTP rotation provider based on your mobile proxy provider's API
provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
)

# Rotate IP between sessions and verify exit IP change before proceeding:
# result = await core.rotate_ip("mobile-modem-1", provider, probe_url="https://api.ipify.org?format=json")
# print("New public exit IP:", result.new_ip)
```
