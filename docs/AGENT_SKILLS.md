# Codex and Claude Code Agent Skill

English · [Russian translation](ru/AGENT_SKILLS.md)

The shared agent skill is [skills/syntetic-core/SKILL.md](../skills/syntetic-core/SKILL.md).
It equips AI coding assistants (Codex and Claude Code) with the knowledge and tools to operate Syntetic Core for undetectable browser automation, anti-fraud / anti-bot bypass (Cloudflare, Akamai, DataDome, Yandex), full fingerprint spoofing (Canvas, WebGL, Audio, Client Hints), persistent cookie storage, early WebWorker patching, human behavioral simulation (ПФ), and mobile proxy rotation.

---

## Installation

From the project root using its virtual environment:

```powershell
.\.venv\Scripts\python.exe tools/install_agent_skills.py --agent both
```

Or with an activated virtual environment on any supported OS:

```bash
python tools/install_agent_skills.py --agent both
```

### Default Target Directories:

| Consumer | Target Skill Path |
|---|---|
| Codex CLI / Desktop | `~/.codex/skills/syntetic-core` |
| Claude Code | `~/.claude/skills/syntetic-core` |

Use `--agent codex` or `--agent claude` to install for a single client. For modern Codex directory layouts, pass `--codex-location modern` (`~/.agents/skills`).

---

## Invocation Prompts

### Codex:
```text
Use $syntetic-core to run an anti-detect browser session with persistent cookies, Canvas/WebGL fingerprint spoofing, and human typing on my target site.
```

### Claude Code:
```text
/syntetic-core Simulate an authentic human browser session on Android with mobile proxy rotation and persistent profile.
```

---

## Runtime Management

The skill includes helper scripts allowing agents to resolve the runtime or bootstrap an isolated environment without manual intervention:

```bash
# Check runtime location and capabilities
python scripts/runtime.py info

# Prepare Chromium and apply the CDP worker patch
python scripts/runtime.py cli prepare --engine chromium

# Verify anti-detect features
python scripts/runtime.py cli doctor

# Execute an automation script
python scripts/runtime.py python path/to/script.py
```
