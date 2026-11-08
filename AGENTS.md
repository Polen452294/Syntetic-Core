# Development

- Public APIs live in `core.py`, `proxy.py`, and `cli.py`; `_engine` is an extracted implementation.
- Preserve device coherence, stable identity files, runtime admission and native transport.
- Do not mutate existing fingerprints or silently switch engines/proxies after failure.
- No controller/DB/queue dependency should be introduced into the standalone runtime.
- Run unit tests, Ruff, formatting and mypy after relevant changes; browser changes need a real local fixture run.
- Update documentation and extraction provenance when changing imported engine modules.
- `tools/extract_engine.py` overwrites internal modules: use it only in a clean comparison copy.
- Never commit `.env`, credentials, profile storage, model weights or browser binaries.
