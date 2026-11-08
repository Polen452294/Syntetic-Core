# Codex and Claude Code skill

English · [Russian translation](ru/AGENT_SKILLS.md)

The shared skill is [skills/syntetic-core/SKILL.md](../skills/syntetic-core/SKILL.md).
It teaches an agent to use the existing core for persistent browser automation,
device selection, parsing, environment checks, and task-authorized IP rotation.
It includes a runtime launcher, focused references, a wheel, and runtime constraints.
It does not require an MCP server or API/model key.

## Install for your account

From the project root, using its virtual environment:

```powershell
.\.venv\Scripts\python.exe tools/install_agent_skills.py
```

Or with an activated environment on any supported OS:

```bash
python tools/install_agent_skills.py --agent both
```

Default locations:

| Consumer | Skill directory |
|---|---|
| Verified Codex desktop/CLI catalog on this machine | `~/.codex/skills/syntetic-core` |
| Claude Code personal skills | `~/.claude/skills/syntetic-core` |

`CODEX_HOME` and `CLAUDE_CONFIG_DIR` are respected for their corresponding directories.
Use `--agent codex` or `--agent claude` to install only one consumer. For Codex, use
`--codex-location desktop` (the default), `modern` for `~/.agents/skills`, or `both`.
The default matches the catalog verified on this machine. Current official Codex
documentation describes `~/.agents/skills`; use `modern` when that is your client's
skill location. Some builds read both and can show duplicate copies. The installer
never removes earlier copies.

Installation records source-owned files and a pointer to this checkout. Re-running
updates an unchanged managed installation. It refuses to overwrite unrelated skills
or locally modified managed files. It does not change agent permissions or settings.

## Invocation

Codex:

```text
Use $syntetic-core to build a persistent Android browser parser for my authorized site.
```

Claude Code:

```text
/syntetic-core Build a browser parser with a reusable profile and JSON output.
```

The name/description also allow automatic selection when the assigned task matches.
If a newly installed skill is not visible, start a new session or restart the client.
Claude Code was not found on PATH during setup on this machine; its personal skill
files can still be installed without installing the Claude Code application.

## Runtime resolution

Run the following relative to the installed skill directory:

```bash
python scripts/runtime.py info
python scripts/runtime.py cli --profiles /absolute/task/profiles doctor
python scripts/runtime.py python /absolute/path/to/task.py
```

The helper uses an explicit `SYNTETIC_CORE_HOME`, the recorded checkout, an enclosing
checkout, or a bootstrapped skill runtime. It preserves arguments and the working
directory without a shell. `info` only locates files; it does not launch browsers.

If the checkout is unavailable, the skill can install its bundled wheel independently:

```bash
python scripts/runtime.py setup
python scripts/runtime.py cli prepare --engine chromium
```

The default isolated environment is `~/.cache/syntetic-core/skill-runtime`.
Use `setup --venv /absolute/path` and set `SYNTETIC_CORE_SKILL_RUNTIME` for a custom
location. Python 3.12+ is required for setup. No browsers or provider calls run as
part of skill installation; browser preparation is an explicit subsequent command.

## Distributing and updating

The source ZIP and sdist include `skills/syntetic-core`. Copy that folder into the
appropriate consumer's skills directory, or run the installer from the source project.
The separate `dist/syntetic-core-skill.zip` contains just the portable skill folder.
No credentials or profile storage are included. The bundled wheel must be refreshed
when releasing changes to the core. Browser binaries are installed separately.

For development, validate `SKILL.md`, run `tests/test_agent_skills.py`, and exercise
the helper's `info`, argument forwarding, and installation into an isolated home
before updating personal installations. Core behavior is covered by the existing
unit/browser suites.

Discovery and invocation follow the official [Codex skills documentation](https://learn.chatgpt.com/docs/build-skills)
and [Claude Code skills documentation](https://code.claude.com/docs/en/skills).
