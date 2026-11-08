# Provenance, Extraction Scope & Enterprise Heritage

English · [Russian translation](ru/EXTRACTION.md)

Syntetic Core was extracted on **November 8, 2026**, from the enterprise behavioral factors automation system ("ПФ" / Behavioral Factors and Anti-Fraud bypass platform).

The parent platform was engineered to simulate millions of authentic human browser sessions across major search engines and commercial platforms without detection by advanced anti-fraud and anti-bot systems (Cloudflare, Akamai, DataDome, Kasada, Yandex SmartCaptcha & Anti-Fraud, Google reCAPTCHA, etc.).

The goal of this extraction is to isolate the **browser anti-detect runtime** into a clean, standalone Python library (`syntetic_core`) and CLI (`syntetic-core`), stripping away heavy enterprise infrastructure requirements.

---

## What Was Extracted into Syntetic Core

57 core browser runtime modules and critical low-level stealth assets were ported:
1. **Full Digital Fingerprint Spoofing Stack:**
   - Canvas 2D subpixel noise generator (`canvas.py`).
   - WebGL 1/2 vendor, renderer, and parameter spoofer (`device_emulation.py`, `device_emulation.js`).
   - Web Audio API buffer noise generator.
   - Client Hints (`Sec-CH-UA`) CDP overrides (`chromium.py`).
   - System fonts filtering (`FontFaceSet`) and media devices emulation (`media_presets.py`).
   - Mobile touch events, Accelerometer, Gyroscope, and Magnetometer emulation (`sensors.py`).
2. **CDP WebWorker Controller:**
   - Early interception and runtime patching for DedicatedWorkers, SharedWorkers, ServiceWorkers, and NestedWorkers (`playwright_worker_control.py`).
3. **Anti-Automation Function Masquerade:**
   - The dual Proxy/WeakMap layer (`native_functions.js`) that enforces `[native code]` representations for all overridden JavaScript APIs and getters.
4. **Coherent Device Recipes:**
   - 1000+ linked hardware configurations matching real Android models, Apple Silicon Macs, Intel PCs, and iPhones (`device_coherence.py`, `phone_personas.py`).
5. **Persistent Cookie Storage & Profile State:**
   - True persistent session storage (`visit_state.py`, `profile_storage.py`), preserving cookies, `localStorage`, `IndexedDB`, and cache across launches.
6. **Human Behavioral Factors (ПФ Simulation):**
   - Natural Bezier mouse paths with micro-jitter and overshoots, human typing cadence with typos, and inertial scrolling (`actions/behavior.py`, `pacing.py`).
7. **Camoufox & WebKit Integrations:**
   - Pinned integration for Camoufox (hardened C++ Firefox) and native WebKit runtime policy.
8. **Network Stealth & Mobile Proxy Management:**
   - Native browser TLS tunneling via local SOCKS5 TargetProxy, hardware modem channel locks, and HTTP API IP rotation with public exit confirmation.

`extraction-manifest.json` preserves the original file SHA-256 hashes and path mappings.

---

## Architectural Refactoring

- **Decoupled Dependencies:** Replaced internal enterprise imports (`backend.app.*`, `worker.*`) with standalone `syntetic_core._engine.*` namespaces.
- **Removed Heavy Infrastructure:** Eliminated requirements for PostgreSQL, SQLAlchemy ORM, Alembic migrations, Redis queues (Dramatiq), distributed leases, and Docker containers.
- **Local OS File Locks:** Converted distributed Redis quorum locks to local atomic OS file locks (`ProfileLock`), enabling high-performance multi-process execution on a single host.
- **Dedicated Public API:** Built the clean `SynteticCore` class, `BrowserSession` context manager, and `syntetic-core` CLI for direct Python automation.
- **Default Persistence:** The standalone package defaults to persistent profiles (`fresh=False`) to support profile warming and cookie accumulation across sessions.

---

## What Remains in the Enterprise Platform

The following distributed enterprise components were deliberately excluded from this standalone library:
- Distributed task dispatching, database cluster accounting, and quota management.
- Multi-node S3 / P2P profile mesh synchronization.
- Automated CAPTCHA solving neural networks and OCR training pipelines.
- Distributed cgroups resource supervisors and cluster metrics aggregators.
