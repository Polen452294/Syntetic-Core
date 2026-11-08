# Runtime, Platform Constraints & Documentation

The skill bundles `assets/syntetic_core-0.1.0-py3-none-any.whl` and `assets/requirements.lock` for self-contained execution without an active project checkout.

`scripts/runtime.py info` resolves in this priority:
1. Explicit `SYNTETIC_CORE_HOME` environment variable.
2. `runtime.json` created by the skill installer pointing to this project checkout.
3. An enclosing Syntetic Core checkout directory.
4. The bootstrapped skill runtime in `~/.cache/syntetic-core/skill-runtime`.

---

## Setup & Preparation

```bash
python scripts/runtime.py info
python scripts/runtime.py setup
python scripts/runtime.py cli prepare --engine chromium
python scripts/runtime.py cli doctor
python scripts/runtime.py python /absolute/path/to/task.py
```

Preparation installs Playwright Chromium and applies the essential **Worker-target ownership patch** (Playwright 1.62.0), which prevents CDP deadlocks and automation detection flags.

---

## Anti-Detect Platform & Stealth Constraints

- **Chromium:** Uses Playwright 1.62.0 with driver patch and recursive CDP worker interception (handles DedicatedWorkers, SharedWorkers, ServiceWorkers, and NestedWorkers).
- **Camoufox:** Hardened Firefox build with low-level C++ engine protection against Canvas/WebGL/Audio fingerprinting. Requires `camoufox_install_path` or `tools/setup_browser.py`.
- **WebKit:** Emulates iOS and Safari layout/JS behavior. Operates on Linux and macOS; blocked on Windows.
- **Native Browser TLS:** Traffic routed via SOCKS5 TargetProxy uses genuine browser TLS handshakes (real JA3/JA4 signatures), bypassing TLS-level bot mitigation.
- **Hardware Limitations:** Physical CPU instruction sets and GPU hardware capabilities remain host properties. Avoid claiming ARM64 on x86-64 when running benchmarks that test machine instructions.

---

## Project Documentation Index

- `README.md` / `docs/ru/README.md`: Overview, quickstart, and features.
- `docs/ARCHITECTURE.md` / `docs/ru/ARCHITECTURE.md`: Pipeline, CDP worker control, and storage layout.
- `docs/EMULATION.md` / `docs/ru/EMULATION.md`: Digital fingerprint spoofing details (Canvas, WebGL, Audio, Client Hints, Fonts).
- `docs/USAGE.md` / `docs/ru/USAGE.md`: Full API reference, settings, and behavioral helpers (`session.behavior`).
- `docs/PROXIES.md` / `docs/ru/PROXIES.md`: Mobile proxies, modem locking, and IP rotation.
- `docs/EXTRACTION.md` / `docs/ru/EXTRACTION.md`: Provenance and extraction from the production ПФ system.
- `docs/INSTALLATION.md` / `docs/ru/INSTALLATION.md`: Environment setup and Camoufox / WebKit flags.
- `docs/TROUBLESHOOTING.md` / `docs/ru/TROUBLESHOOTING.md`: Common errors, locks, and recovery steps.
