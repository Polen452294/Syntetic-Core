# Anti-Detect Engine Development Guidelines

- **Architecture:** Public APIs live in `core.py`, `proxy.py`, and `cli.py`; `_engine` contains the extracted anti-detect and device emulation engine from the ПФ platform.
- **Fingerprint Stealth & Integrity:** Never weaken fingerprint spoofing (Canvas 2D subpixel noise, WebGL vendor/renderer, Web Audio, Client Hints, or `[native code]` Proxy/WeakMap function shims).
- **WebWorker Interception:** All background threads (Dedicated, Shared, Service, Nested Workers) must continue to be auto-intercepted and patched via the CDP controller before worker scripts run.
- **Persistence & Cookies:** Preserve the persistent profile model (`browser-data/`, `ProfileLock`, `config_hash`). Profiles accumulate cookies, local storage, and history across sessions to maintain anti-fraud trust.
- **Device Coherence:** Never introduce mismatched hardware parameters (e.g. invalid GPU/CPU/DPR combinations) that could trigger anti-fraud fraud scores.
- **Network Safety:** Never fall back to a direct connection if proxy fails. Always enforce physical modem channel locking (`proxy_channels`) and verify exit IP changes via probe.
- **Lightweight Standalone Scope:** Do not re-introduce external dependencies (PostgreSQL, Redis, Celery/Dramatiq, S3 mesh, Docker).
- **Code Quality:** Run unit tests, Ruff, formatting, and Mypy after changes. Browser tests require a real local fixture run (`$env:SYNTETIC_CORE_RUN_BROWSER="1"`).
- **Confidentiality:** Never commit `.env`, proxy credentials, live profile data, cookies, model weights, or browser binaries.
