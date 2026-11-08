# Device emulation: data, application, and limits

English · [Russian translation](ru/EMULATION.md)

## Four distinct layers

1. **Physical host:** Windows/Linux/macOS, CPU architecture, real hardware.
2. **Browser engine:** actual Chromium, modified Firefox/Camoufox, or WebKit.
3. **Target configuration:** desktop/Android/iOS, device model, OS, and linked recipe.
4. **Observable APIs:** values set by the engine, Playwright/CDP, or JavaScript.

Selecting `target_os=macos` on Windows does not run macOS. Linux WebKit with an
iPhone preset is not Safari running on a physical iPhone.

## Capability matrix

| Data group | Camoufox / Firefox | Chromium | WebKit / iOS |
|---|---|---|---|
| Target OS | Native Windows/macOS/Linux fingerprint | CDP UA/platform/Client Hints | Safari UA and iOS/iPadOS preset |
| Screen/viewport/DPR | Native configuration and validation | Playwright/CDP | Playwright and mobile geometry |
| CPU | Consistent native/JS count | CDP and consistent JS/Workers | Observable JS count where supported |
| GPU/WebGL | Native engine catalog | JS WebGL1/2 vendor/renderer, including supported Worker OffscreenCanvas | JS vendor/renderer |
| Fonts | Native font sets | JS FontFaceSet/canvas filtering | Equivalent JS layer |
| Audio | Native seed, sample rate, buffer | Stable JS noise when reading APIs | Where Web Audio is available |
| Cameras/microphones/outputs | Native media presets | Persistent JS lists respecting permissions | Where MediaDevices is available |
| Voices | Native/library/local/none | Host voice subset consistent with language/OS | Where SpeechSynthesis is available |
| RAM | Missing API is not added | Document and WorkerNavigator `deviceMemory` | Missing API is not added |
| Battery | Missing API is not added | Native BatteryManager with emulated document values/events | Missing API is not added |
| Touch | Desktop without touch | Android maxTouchPoints=5, CDP + init script | iOS platform/touch shim |
| Sensors | Document JS when verified | Native Android CDP sensors or JS fallback | Document JS when verified |
| Appearance/accessibility | Engine options | Engine options | Engine options |
| DNT/GPC | Native or verified fallback | Navigator + HTTP headers | Navigator + HTTP headers |
| Geolocation | Only when capability is confirmed | Origin-scoped native API | Origin-scoped native API |
| Shared layers | Canvas text shift, function representation, webdriver | Same, plus mandatory memory/battery | Same, without creating absent APIs |

Each optional group requires successful checks on the selected runtime. This matrix
describes the extracted implementation, not new acceptance results for every OS.

## Coherent recipes

`coherence.version` and `recipe_id` link model, OS, engine, screen, viewport,
orientation, DPR, CPU, GPU, and Client Hints architecture. Phone selection uses the
exact model and `preset_id`; unknown models do not receive an approximate fallback GPU.

Examples of source implementation rules:

- Apple M1/M2 Chromium uses a consistent ARM recipe and CPU count 8.
- Android uses browser CPU count 8 and multitouch 5; GPU is mapped by exact model.
- iPhone/iPad mini 6 use supported browser CPU counts 4/6; M1 iPads use 4/8.
- Camoufox uses one CPU count for its native GPU sampler and JS; macOS recipes exclude 4.
- Screen dimensions multiplied by DPR constrain the eligible GPU recipe.
- Mobile media presets cannot inherit a desktop USB conferencing setup.
- Forced colors requires increased contrast.
- Generated coordinates must be consistent with the timezone.

Desktop target OS selection retains Windows/macOS/Linux weights of 79/16/5 among
available modes. These are catalog weights, not market estimates or guaranteed
small-sample proportions. Read `phone_personas.PHONE_MODELS` and `PHONE_PRESETS`
for catalog sizes; the historical count of 1380 is not an immutable contract.

## Persistence versus per-action randomness

Fingerprint ID, recipe, hardware values, media IDs, Canvas/audio seeds, geometry,
and native configuration are selected once and retained. Pauses, movement, and
individual behavioral actions are sampled during execution.

`config_hash` checks the persona. Separate identity files bind the effective browser
configuration. Derived memory/battery settings for an older Chromium profile do not
rewrite its persona but are stored separately. Changing a saved seed or engine is rejected.

## Mandatory session policy

- Canvas 2D `fillText`/`strokeText` receive a stable shift of up to ±0.02 px. Pixel reads
  remain native; different seeds need not produce different hashes for every image.
- A Proxy/WeakMap layer supplies registered functions/getters with a `[native code]`
  representation. This is JavaScript behavior, not conversion to native implementation.
- `navigator.webdriver` must be exactly `false`; Camoufox is checked in the main world.
- Chromium receives consistent memory/battery values even without explicit
  `persona.emulation` fields.
- Initialization happens before the context is yielded. Missing mandatory layers
  cause startup failure.

## Documents and Workers

Init scripts cover future documents, iframes, and popups; existing frames are handled
during preparation. Camoufox receives the relevant scripts in main and isolated worlds.

Chromium Workers separately receive CPU, `deviceMemory`, UA/platform, and WebGL
configuration. Client Hints are set through CDP. Battery, DOM permissions, font
filtering, document sensors, and Canvas text shifts are not automatically injected
into Worker scripts. Matching document navigator values do not establish complete
Worker coverage.

## Native features

Android supports consistent virtual sensors and periodic motion; foldable presets
support posture/segments for the inner display. Motion frequency is a loop target,
not a real-time guarantee. CPU throttling slows execution but does not model a
specific processor. Text scale may be rounded by the engine.

Before JS emulation, WebKit locally checks WebAudio, MediaDevices, SpeechSynthesis,
and WAV/H.264/AAC decoding. Linux requires the appropriate GStreamer/codecs. The
entire WebKit runtime is prohibited on Windows.

## Properties not fully replaced

Physical RAM, SIM/operator, USB port count, actual CPU performance, real GPU limits,
complete Chromium/WebKit extension sets, every CSS font metric, physical camera and
microphone streams, and the complete target OS stack are not reproduced.

`enumerateDevices` does not create video streams. Voices may be absent. BrowserForge
is not independently applied as an environment injector. TLS/HTTP fingerprints
belong to the installed browser; personas do not arbitrarily randomize them.
HTTP `Device-Memory`/`Sec-CH-Device-Memory` headers are not separately overridden.

Sensors require a secure context, an authorized origin, and applicable Permissions
Policy. Geolocation is generated near a timezone's city center; it is not derived
from the proxy IP. The application/provider must align IP country, timezone, and locale.

## Behavior

The extraction includes per-character typing, bounded lognormal pauses, curved
cursor movement, scrolling, tap paths, and UXActivityDispatcher. Desktop mouse
movement is not applied to phones. `maintain_presence()` is opt-in and unnecessary
for DOM parsing. Synthetic activity does not guarantee how external analytics count a visit.
