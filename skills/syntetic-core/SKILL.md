---
name: syntetic-core
description: High-stealth anti-detect browser automation engine for undetectable human session simulation, anti-fraud/anti-bot bypass (Cloudflare, DataDome, Akamai, Yandex), full fingerprint spoofing (Canvas, WebGL, Audio, Client Hints), early WebWorker patching, persistent cookie jars, human behavioral factors (ПФ), and mobile proxy rotation.
---

# Syntetic Core

Use the bundled Syntetic Core anti-detect browser engine rather than rebuilding custom fingerprint spoofing or anti-detection scripts from scratch. This skill works with Codex and Claude Code.

## 1. Runtime Resolution

Run `python scripts/runtime.py info` relative to this skill directory to resolve the environment:
- Resolves `SYNTETIC_CORE_HOME`, the installed project pointer, the containing checkout, or the bootstrapped runtime.
- Use that interpreter for generated task scripts, or invoke:
  `python scripts/runtime.py python path/to/task.py`
  `python scripts/runtime.py cli --profiles /absolute/path/profiles doctor`

If no runtime is available, bootstrap one using:
```bash
python scripts/runtime.py setup
python scripts/runtime.py cli prepare --engine chromium
```

## 2. Core Automation Guidelines

- **Anti-Detect Session Lifecycle:**
  Always use `SynteticCore`, `CoreSettings`, and `async with core.session(id) as session:`.
  The session yields standard Playwright `session.page` and `session.context` with all fingerprint spoofing and CDP stealth layers pre-injected.
- **Persistent Profiles & Cookie Warming:**
  Profiles are persistent by default (`fresh=False`). Always create or load profiles with stable IDs (`core.load_profile(id)` / `core.create_profile(id, family="desktop")`). This preserves `cookies`, `localStorage`, `IndexedDB`, and cache across launches, building trust scores to bypass CAPTCHAs and bot checks.
- **Full Fingerprint Protection:**
  Profiles automatically apply Canvas 2D subpixel noise (±0.02 px), WebGL vendor/renderer spoofing, Web Audio API noise, Client Hints (`Sec-CH-UA`), CPU cores (`hardwareConcurrency`), RAM (`deviceMemory`), BatteryManager, and OS font filtering.
- **Early WebWorker Patching:**
  The background CDP controller intercepts all Dedicated, Shared, Service, and Nested Workers before scripts execute, ensuring worker threads have matching fingerprints.
- **Human Behavioral Simulation (ПФ):**
  Use `session.behavior` for user actions to defeat behavioral analysis:
  - `await session.behavior.click_element(selector)` (moves cursor along natural Bezier curves)
  - `await session.behavior.type_text(selector, text)` (human typing cadence with typos & corrections)
  - `await session.behavior.scroll_smooth(delta_y)` (inertial scrolling with reading pauses)
  - `await session.maintain_presence(seconds)` (simulates dwell time and micro-activity)
- **Target Host Authorization:**
  Explicitly authorize destination domains in `CoreSettings(allowed_target_hosts=["target.com"])`.
- **Mobile Proxies & IP Rotation:**
  Use `ProxyConfig` and `HttpRotationProvider`. When rotating mobile IPs with `core.rotate_ip(...)`, the core locks the physical modem channel (`proxy_channels`) and verifies the new public exit IP with an independent external probe before proceeding.

Read [workflows.md](references/workflows.md) for code patterns and [runtime.md](references/runtime.md) for platform requirements.
