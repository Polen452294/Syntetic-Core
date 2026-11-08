# API and operation

English · [Russian translation](ru/USAGE.md)

## SynteticCore

```python
core = SynteticCore(
    profile_root="data/profiles",
    settings=CoreSettings(...),
    proxy_channels={"port-1": "modem-A", "port-2": "modem-A"},
)
```

Use one instance with one asyncio event loop. Settings are copied on construction.
Proxy configuration and credentials belong in application settings, not `profile.json`.
Do not mutate settings concurrently with active sessions.

### capabilities(refresh=False)

Asynchronously checks real local runtimes and optional API groups. Returns a copy
of the manifest. Initial discovery may take minutes. Unavailable engines are marked
as unavailable, not replaced with another engine. Use `refresh=True` after an
intentional environment change; updating a browser may break an existing profile's
identity binding.

### create_profile(...)

```python
persona = await core.create_profile(
    "job-001",                # Optional; a UUID is generated if omitted.
    family="android",         # desktop / android / ios
    backend="playwright",     # playwright / camoufox
    proxy_id="mobile-1",       # Optional exact ID from Settings.proxies.
    locale="ru-RU",
    timezone_id="Europe/Moscow",
    fresh=False,
)
```

Camoufox supports desktop profiles. iOS requires Playwright/WebKit on an eligible
host. A profile is created once. Duplicate IDs raise `FileExistsError`; a missing
compatible runtime raises `RuntimeCompatibilityError`. Arbitrary paths and IDs
containing `/` are rejected. The returned `BrowserPersona` can be inspected;
mutating it does not overwrite the saved profile.

The wrapper defaults to persistent use with `visit_state=None`. `fresh=True`
retains the source new/cold contract for a single-use visit.

### load_profile(id)

Synchronously reads configuration and validates the ID, fingerprint, and hash.
For high-volume workflows, use `asyncio.to_thread`. Loading does not launch a
browser or resume a previous session. Invalid profiles are not repaired automatically.

### session(id, base_url=None)

An async context manager that closes the browser context and gateway on normal
exit or exception. One profile cannot be opened concurrently twice. A busy lock
raises `ProfileLockedError`; the core does not silently wait or create a temporary profile.

`base_url` is required when explicit new/returning visitor conditions need
permissions and storage/cache preparation. For a normal persistent profile,
use `async with core.session(id)` followed by `session.goto(url)`.

### BrowserSession

| Field/method | Purpose |
|---|---|
| `page` | Main Playwright Page |
| `context` | Playwright BrowserContext; new tabs inherit shared init scripts |
| `persona` | Saved configuration snapshot for this session |
| `connection` | Observed environment, runtime, and transport |
| `behavior` | Extracted InteractionBehavior |
| `goto(url)` | URL authorization, DOMContentLoaded, environment check |
| `check_environment(page=None)` | Recheck identity and CDP controller health |
| `maintain_presence(seconds)` | Explicit UX activity when the task needs it |

When using `page.goto` directly or handling popups, call `check_environment(page)`
at appropriate checkpoints. Network authorization applies to the entire context;
consistency checks do not automatically follow every custom user action.

## Settings

| Field | Meaning |
|---|---|
| `allowed_target_hosts` | Exact target and resource hosts |
| `trusted_local_target_hosts` | Explicit permission for local/private fixture hosts |
| `browser_headless` | Headless/headful mode for discovery and new profiles |
| `browser_start_timeout` | Session preparation budget; default 30 s |
| `navigation_timeout` | Navigation timeout; default 15 s |
| `action_timeout` | Playwright action timeout; default 10 s |
| `camoufox_install_path` | Absolute path to the pinned build |
| `experimental_arm64` | Explicit ARM64 opt-in for real runtime checks |
| `proxies`, `proxy_required` | Proxy configuration and missing-upstream rejection |
| `network_probe_url` | Additional browser network verification in the factory |
| `traffic_optimizer_enabled` | Explicit resource-filter activation |
| `traffic_optimization_level` | `disabled` / `metadata_only` / `strict` |
| `block_stylesheets` | CSS filtering together with enabled optimization |

Other `_engine.config.Settings` fields remain for compatibility with extracted
low-level components. Distributed/archive/shared-storage modes are rejected because
the corresponding services are not included in this standalone core.

Environment variables use the `SYNTETIC_CORE_` prefix and `__` nesting separator:

```powershell
$env:SYNTETIC_CORE_BROWSER_START_TIMEOUT="60"
$env:SYNTETIC_CORE_ALLOWED_TARGET_HOSTS='["example.com","static.example.com"]'
```

Pass arrays and objects as JSON strings. `.env` is not read automatically, preventing
accidental loading of a neighboring project's configuration. Load credentials through
your application or pass `CoreSettings(...)` explicitly.

## Concurrency and retries

Use `asyncio.Semaphore` to limit browser concurrency and a separate profile ID for
each parallel task. See `examples/parallel_sessions.py`. A single physical proxy/modem
channel is serialized by its local lock. Distinct channels can execute concurrently
within the caller's overall limit.

Do not automatically repeat side-effecting actions after an uncertain network result.
The core does not guarantee exactly-once execution. For scraping, track HTTP status,
required DOM readiness, and empty extraction results separately.

## Low-level features

`BrowserPersona`, `BrowserExperiment`, `BrowserContextFactory`, `VisitExperiment`,
sensor helpers, and identity replay remain available under `_engine`. They require
explicit configuration and compatibility validation. Public `session()` rejects
personas with timeline experiments rather than claiming execution without a
coordinator. Extracted YAML models do not imply the old full Run/ScenarioRunner,
queue, search workflow, or incubation pipeline is included.

When using the factory directly, supply a verified manifest, stable hash, valid
origin permissions, the same channel policy, and guaranteed context cleanup.

## Backups

Finish active sessions before copying an entire profile, including identity files
and browser-data. Cookies alone are not a replacement for the full identity.
Browser builds and native configuration may depend on the host/installation path;
automatic migration across OSes or browser versions is not provided.
