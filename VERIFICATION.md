# Standalone project verification

English · [Russian translation](docs/ru/VERIFICATION.md)

Date: November 8, 2026. Platform: Windows x86-64, Python 3.12.

- Installed independently in the project's own `.venv`.
- Unit/regression suite: **149 passed**.
- Real Chromium test: **1 passed**, 26.86 s. Covered runtime discovery, Android profile
  creation, local navigation, document/Worker CPU and RAM consistency, touch=5,
  webdriver=false, and persistent localStorage across session reopening.
- mypy: passed for the three public API/CLI modules.
- Ruff and formatting checks: passed for the 96 Python files checked at that stage.
- Wheel and sdist: successfully built with `python -m build`.
- Imported a separately installed wheel under Python `-I`; confirmed JavaScript and
  WebKit media resources were included. The same wheel passed 149 unit tests.
- Repeated the real browser test from the wheel after pinning runtime dependencies:
  **1 passed**, 29.88 s. Package imports did not use the source `src` directory.
- `pip check`, relative README/docs links, and SHA-256 validation of 63 extracted
  engine/resource files passed.

The browser test uses only a local HTTP fixture. Provider rotation tests use mocks
covering API rejection/timeout, changed-IP confirmation, busy-channel exclusion,
shared modem IDs, credentials, and cancellation. No new paid provider API calls were made.

Linux/macOS/ARM64, a standalone Camoufox build, WebKit, and real IP providers have not
yet completed independent acceptance in this project. Historical source-system
evidence is not presented as new standalone-package test results.

## Agent skill integration

- Current unit/regression suite after skill integration: **159 passed**, one browser
  test deselected; includes 10 runtime resolution/launcher/installer tests.
- Skill frontmatter validator, Ruff, formatting (103 Python files), mypy, and
  documentation link/language checks passed. The 63 engine/resource hashes remain unchanged.
- Codex CLI 0.146.0 `skills/list` found `syntetic-core` in the personal `.codex/skills`
  catalog with `enabled=true`.
- Claude Code personal skill files were installed; live Claude invocation was not
  tested because the executable was not found on PATH.
- The skill bundles its runtime wheel and constraints; installation itself does not
  start a browser or contact an IP provider. Core browser tests were not repeated
  for this integration because the engine and public API were unchanged.
