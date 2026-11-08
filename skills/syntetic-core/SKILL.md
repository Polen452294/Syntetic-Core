---
name: syntetic-core
description: Use Syntetic Core for Python browser automation, dynamic-page scraping, persistent device profiles, Android/iOS emulation, environment checks, and provider-controlled proxy IP rotation. Apply when these capabilities are requested or fit the assigned browser task; not for unrelated HTTP-only scraping.
---

# Syntetic Core

Use the bundled Syntetic Core browser engine rather than rebuilding its fingerprint
or device emulation layers. This skill works with Codex and Claude Code. Instructions
and examples are English; the project's Russian documentation is separate.

## Find the runtime

Run `python scripts/runtime.py info` relative to this skill directory. It resolves
an explicit `SYNTETIC_CORE_HOME`, the installation's project pointer, the containing
checkout, or a previously bootstrapped runtime. It reports absolute interpreter and
documentation paths without starting browsers or contacting providers.

Use that interpreter for generated task scripts. Alternatively run
`python scripts/runtime.py python path/to/task.py` or
`python scripts/runtime.py cli --profiles /absolute/task/profiles doctor`.
Quote skill and interpreter paths that contain spaces. Keep the caller's working
directory; choose an explicit absolute profile root for each task.

If no runtime is available, run `python scripts/runtime.py setup` with Python 3.12+.
It creates an isolated environment outside the skill and installs the bundled wheel
with its runtime constraints. Browser preparation is separate:
`python scripts/runtime.py cli prepare --engine chromium`. Do not patch a driver
while its browser sessions are active. Read [runtime.md](references/runtime.md) for
platform setup, limitations, and advanced documentation locations.

## Build the assigned workflow

- Use `SynteticCore`, `CoreSettings`, and the regular Playwright page/context APIs.
  Read [workflows.md](references/workflows.md) for a persistent parsing example,
  device selection, and the provider extension contract.
- Explicitly authorize exact target and required resource hosts. Local/private test
  hosts additionally require `trusted_local_target_hosts`.
- Create a profile once, then load/reuse its ID for persistent cookies/localStorage.
  Use separate IDs for concurrent browser tasks. Use `fresh=True` and `base_url`
  only for an intended single-use new/cold profile.
- Generate profiles against real local capabilities. Desktop Camoufox, Android
  Chromium, and iOS WebKit are distinct modes. Windows WebKit is prohibited;
  unsupported modes must fail rather than silently switching engines.
- Preserve saved recipe, seed, engine, identity files, and profile hash. Changing
  identity requires a new profile, not editing or deleting individual identity files.
- Use `async with core.session(...)` for cleanup. `session.goto()` checks the
  environment; after custom navigation/popup handling, call `check_environment()`
  at relevant checkpoints. Bound overall task concurrency in the calling script.

## IP rotation, when part of the task

Use `ProxyConfig`, `HttpRotationProvider`, or a custom `RotationProvider`. Rotate
between sessions with `core.rotate_ip(...)`, not during an active session. Map ports
sharing a physical modem to the same channel ID. Confirm a changed public IP through
the assigned proxy; a provider API success response is insufficient. Never fall
back to a direct connection after proxy failure.

Provider URLs, methods, authentication, and JSON success fields come from that
provider's actual API contract. Keep credentials in the task's environment/secret
store, not profile JSON, generated examples, logs, or skill files. Use only provider
operations and external destinations within the user's assigned task; this skill
does not authorize purchases, balance changes, or unrelated traffic.

## Verification and reporting

Check useful task outcomes: HTTP status, required DOM content, extracted records,
state persistence where requested, and explicit failures. Use a local fixture for
integration changes before external visits. Report which engine/device was used,
what data was produced, and any unverified provider or platform assumptions.

The engine emulates observable APIs, not a physical device or full target OS. It
does not guarantee site acceptance or human indistinguishability. Chromium Worker
coverage does not extend automatically to Firefox/WebKit. The extracted launch
policy retains `--no-sandbox`; use a trusted/isolated executor appropriate to the
content. The standalone core does not include the source platform's distributed
controller, database, incubation, resource supervisor, or S3 workflow.
