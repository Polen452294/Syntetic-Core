# Runtime and documentation

The skill bundles `assets/syntetic_core-0.1.0-py3-none-any.whl` and
`assets/requirements.lock`. It does not bundle credentials, browser executables,
profile data, or a virtual environment.

`scripts/runtime.py info` resolves in this order:

1. Explicit `SYNTETIC_CORE_HOME` project path; invalid explicit configuration fails.
2. `runtime.json` written by the skill installer, when that checkout still exists.
3. An enclosing Syntetic Core source checkout.
4. The isolated skill runtime created by `setup` under the user's cache directory.

An available project needs its own `.venv`. If the checkout/environment is missing,
`setup` can install the bundled wheel instead. The helper never downloads dependencies
or starts a browser merely to discover a runtime. `python` and `cli` subcommands
forward arguments without a shell, preserve the working directory, and remove
ambient PYTHONPATH/PYTHONHOME from the child to avoid cross-project imports.

## Setup

```text
python scripts/runtime.py info
python scripts/runtime.py setup
python scripts/runtime.py cli prepare --engine chromium
python scripts/runtime.py cli doctor
python scripts/runtime.py python /absolute/path/to/task.py
```

`setup --venv /absolute/path` chooses a managed environment explicitly; set
`SYNTETIC_CORE_SKILL_RUNTIME` to that path for subsequent commands. The default
is `~/.cache/syntetic-core/skill-runtime`. `SYNTETIC_CORE_SKILL_RUNTIME` can select
an existing managed environment. A configured project is preferred over this cache.
Preparation requires Python 3.12+ and dependency/browser downloads; it is an explicit
operation. It does not start a model session or call an IP provider.

## Platform constraints

- Playwright is pinned to 1.62.0 and its checked Worker-target ownership patch.
- Windows Chromium is independently tested in the standalone project.
- Camoufox requires the separately installed pinned native build/model data. With
  a source checkout, use `tools/setup_browser.py` and set `camoufox_install_path`.
- iOS/WebKit needs Linux/macOS and verified native media support. It is blocked on
  Windows. Linux ARM64 needs compatible binaries and explicit experimental opt-in.
- Linux system libraries may require `python -m playwright install --with-deps chromium`
  through the resolved interpreter, followed by driver preparation.
- Physical hardware, complete OS behavior, real GPU limits, and all font metrics
  are not reproduced by JavaScript. Sensors and media APIs depend on native support,
  permissions, and secure contexts.
- The package does not provide the original cluster's cgroups/supervisor. Concurrency
  and isolation belong to the calling application/executor.

## Read only what the task needs

When `info` reports a source checkout, read its English documentation:

- `README.md`: first use and available examples.
- `docs/USAGE.md`: lifecycle, timeouts, persistence, fresh profiles.
- `docs/EMULATION.md`: exact data groups and document/Worker boundaries.
- `docs/PROXIES.md`: provider API mapping, IP confirmation, shared channels.
- `docs/INSTALLATION.md`: Camoufox/WebKit/ARM64 setup and launch flags.
- `docs/TROUBLESHOOTING.md`: runtime, identity, lock, and resource failures.
- `VERIFICATION.md`: measured coverage and remaining platform/provider gaps.

For a wheel-only runtime, use [workflows.md](workflows.md), inspect the installed
public API as needed, and obtain the project's source distribution for full docs.
