# Device Emulation, Fingerprint Spoofing & Anti-Detection

English · [Russian translation](ru/EMULATION.md)

Syntetic Core is designed to simulate authentic human browser sessions capable of passing modern anti-fraud, anti-bot, and behavioral analysis engines (including Cloudflare Turnstile / Bot Management, DataDome, Akamai Bot Manager, Kasada, Yandex SmartCaptcha & Anti-Fraud, Google reCAPTCHA v2/v3/Enterprise, CreepJS, FingerprintJS Pro, and Pixelscan).

To achieve undetectable status, the engine coordinates four operational layers:
1. **Physical Host:** Windows/Linux/macOS hardware executing the browser binary.
2. **Browser Engine:** Real Chromium, hardened Firefox (Camoufox), or WebKit.
3. **Hardware Recipe & Coherence:** Linked identity parameters defining the target device.
4. **Observable JavaScript & CDP Surface:** Active runtime modifications applied to the DOM, browser headers, and background WebWorkers.

---

## 1. Digital Fingerprint Spoofing (Full Breakdown)

| Fingerprint Surface | Camoufox (Stealth Firefox) | Chromium (Playwright + CDP) | WebKit (iOS / macOS) |
|---|---|---|---|
| **Target OS & Platform** | Low-level C++ native fingerprint (Win/macOS/Linux) | CDP User-Agent, `navigator.platform`, Client Hints (`Sec-CH-UA-Platform`) | Native Safari User-Agent and iOS platform identifiers |
| **Canvas 2D** | Native C++ canvas randomization seed | Stable subpixel text shift (±0.02 px) in `fillText`/`strokeText` per profile | Subpixel text shift layer |
| **WebGL 1 & 2** | Native driver abstraction and capability masking | Emulated unmasked vendor, unmasked renderer, extensions, and limits | WebGL vendor and renderer alignment |
| **Web Audio API** | Native audio buffer sampler and sample rate noise | Deterministic mathematical noise in AudioBuffer and DynamicsCompressor | Audio noise injection layer |
| **Client Hints (`Sec-CH-UA`)** | Not applicable to Gecko architecture | Full CDP Client Hints: brand version list, architecture, bitness, mobile flag | Not applicable to WebKit |
| **CPU (`hardwareConcurrency`)** | Unified native sampler and JS core count | CDP override and synchronized WorkerNavigator property | Synchronized JS core count |
| **RAM (`deviceMemory`)** | API omitted (matching real Firefox behavior) | Synchronized `navigator.deviceMemory` in Document and WebWorkers | API omitted (matching real Safari behavior) |
| **Battery API** | API omitted (matching real Firefox behavior) | Full BatteryManager emulation with realistic charging/level events | API omitted (matching real Safari behavior) |
| **Fonts & FontFaceSet** | Native font visibility filtering | `FontFaceSet` filtering matching the target OS font catalog | Font filtering matching target OS |
| **Media Devices** | Native media device profiles | Consistent `navigator.mediaDevices.enumerateDevices` IDs and labels | Emulated device list |
| **SpeechSynthesis** | Native voice configuration | Host voice subset strictly filtered to match target OS and language | Native voices |
| **Touch & Gestures** | Desktop without touch | Android: `maxTouchPoints = 5`, touch events, and CDP touch emulation | iOS touch events and gesture shim |
| **Sensors API** | Native sensor policy | Android: Accelerometer, Gyroscope, and Magnetometer via CDP | Native sensor policy |
| **Webdriver Flag** | Strictly `navigator.webdriver = false` | Strictly `navigator.webdriver = false` (automated flags cleared) | Strictly `navigator.webdriver = false` |
| **Function Masquerade** | Native Firefox behavior | Proxy/WeakMap layer: `Function.prototype.toString` returns `[native code]` | Native function inspection layer |

---

## 2. Hardware Coherence Engine (`device_coherence`)

A major detection vector in naive automation tools is **attribute inconsistency** (e.g., an iPhone User-Agent reporting 8 CPU cores and an NVIDIA GPU, or a mobile resolution with desktop Client Hints).

Syntetic Core enforces strict hardware recipes (`recipe_id`):
- **Apple Silicon macOS:** Chromium on Apple M1/M2 enforces ARM64 architecture, 8 CPU cores, Apple GPU renderers, and matching Client Hints bitness.
- **Android Mobile:** Maps exact phone models (Samsung Galaxy S21/S22/S23, Google Pixel 6/7/8, Xiaomi, OnePlus) to their exact GPUs (Adreno / Mali), 8 CPU cores, 5-point multitouch, and accurate screen geometry/DPR.
- **iOS / iPadOS:** Constrains iPhone to 4/6 CPU cores and iPad models to 4/8 CPU cores with matching retina DPR multipliers.
- **Screen Geometry & DPR:** Viewport and screen dimensions strictly constrain eligible GPU recipes to prevent anomalous resolution/GPU pairings.
- **Timezone & Geolocation:** Synthetically generated coordinates are centered around real metropolitan areas matching the assigned timezone.

---

## 3. Anti-Automation & CDP Stealth

Automated browsers are routinely exposed through CDP artifacts, runtime variables, and function modifications:
1. **Playwright Target Ownership Patch:** Playwright's default driver competes with CDP controllers over target resume/detach events. Syntetic Core installs a patched driver (Playwright 1.62.0) that grants explicit target ownership, preventing CDP deadlocks and detectable timing anomalies.
2. **`[native code]` Proxy/WeakMap Masquerade:** All patched JavaScript APIs (e.g. `navigator.webdriver`, `WebGLRenderingContext.prototype.getParameter`, `AudioContext`) are wrapped in a dual Proxy and WeakMap architecture. Inspecting `Function.prototype.toString.call(target)` or checking `target.name` and `.length` returns authentic native function metadata identical to unpatched browsers.
3. **Artifact Cleanup:** Strips `window.cdc_` variables, Chrome runtime flags, and Playwright automation markers before any target document loads.

---

## 4. Early WebWorker Fingerprint Injection

A critical blindspot in conventional scrapers is background WebWorkers. Anti-bot scripts (such as Cloudflare Turnstile and DataDome) instantiate DedicatedWorkers, SharedWorkers, ServiceWorkers, or OffscreenCanvas contexts to query hardware parameters from threads that document-level init scripts cannot reach.

Syntetic Core solves this with a **dedicated CDP worker controller**:
- Recursively auto-attaches to all Worker targets at the moment of creation.
- Pauses worker startup before any worker script executes.
- Injects CPU count, `deviceMemory`, User-Agent, platform, Client Hints, and WebGL offscreen canvas configuration into the worker environment.
- Resumes execution only after the worker's digital fingerprint perfectly matches the parent document.

---

## 5. Persistent Cookies, Storage & Session Warming

Anti-fraud engines assign trust scores based on visitor history. A brand-new browser profile with empty storage is heavily scrutinized and frequently challenged with CAPTCHAs.

Syntetic Core profiles are **persistent by default**:
- Retains `cookies`, `localStorage`, `sessionStorage`, `IndexedDB`, and browser disk cache across runs.
- Enables progressive **profile warming**: visits to search engines, authority sites, and account portals accumulate cookies and trust over days or weeks.
- Profile storage is isolated in `data/profiles/<id>/` protected by atomic OS file locks (`ProfileLock`) and validated with SHA config hashes (`config_hash`).

---

## 6. Human Behavior Emulation (ПФ / Behavioral Factors)

Anti-fraud algorithms analyze cursor kinematics, keyboard intervals, and scrolling dynamics. Syntetic Core includes a production-grade behavioral simulation engine:
- **Mouse Kinematics:** Moves the cursor along natural cubic Bezier curves with non-linear velocity profiles, micro-tremors, and realistic overshoots before snapping to target elements.
- **Human Typing:** Simulates character-by-character typing with lognormally distributed delays, realistic typographical errors, and backspace correction sequences.
- **Inertial Scrolling:** Page scrolls utilize acceleration, smooth deceleration curves, and intermittent pauses replicating real human reading behavior.
- **Presence Simulation:** `session.maintain_presence(seconds)` and `UXActivityDispatcher` generate subtle background cursor drifts, micro-scrolls, and viewport dwell time to simulate active human presence.

---

## 7. Real Host Boundaries & Ethical Scope

While Syntetic Core provides deep fingerprint spoofing and behavioral fidelity, certain physical host properties cannot be completely replaced:
- Physical CPU execution cycles and instruction set benchmarks (e.g., executing x86 instructions while claiming ARM64) remain governed by host hardware.
- Low-level OS kernel networking behaviors (e.g., OS-level TCP window size) belong to the host system.
- WebKit requires Linux or macOS and cannot run on Windows.

Always align proxy geolocation, system timezone, and browser locale to prevent network-level geographic discrepancies.
