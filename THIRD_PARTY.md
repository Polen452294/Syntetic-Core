# Third-party components

Dependencies are installed separately and retain their respective licenses. See the
installed distribution metadata and upstream LICENSE files for the authoritative terms.

| Component | Purpose |
|---|---|
| Playwright / Chromium / WebKit | Browser automation and browser runtimes |
| Camoufox / Firefox | Native configurable browser identity |
| BrowserForge and Camoufox model dependencies | Fingerprint generation/data |
| Pydantic / pydantic-settings | Validation and settings |
| httpx / httpcore / socksio | Provider APIs and HTTP transport |
| websockets | Chromium CDP |
| PyYAML | Scenario model parsing |
| psutil / tzdata | Runtime observations and time zones |
| pytest / pytest-asyncio / Ruff / mypy / build | Development checks |

No FingerprintJS, browser-integrity/CreepJS, uBlock or AdGuard bundle is included.
The native content-filter source and local WebKit media sample were copied from the
first-party browser resources recorded in extraction-manifest.json.
