# Workflow examples

## Persistent browser parsing

Run with the interpreter reported by `scripts/runtime.py info` or through its
`python` subcommand. Substitute the user's target and output requirements; do not
visit demonstration URLs merely because they appear in this reference.

```python
import asyncio
import json
from pathlib import Path
from syntetic_core import CoreSettings, SynteticCore


async def main():
    core = SynteticCore(
        Path(".syntetic-core/profiles").resolve(),
        settings=CoreSettings(allowed_target_hosts=["example.com"]),
    )
    try:
        core.load_profile("catalog")
    except FileNotFoundError:
        await core.create_profile("catalog", family="desktop")

    async with core.session("catalog") as session:
        response = await session.goto("https://example.com")
        if response is None or response.status >= 400:
            raise RuntimeError("Target navigation failed")
        await session.page.locator("body").wait_for(state="visible")
        records = await session.page.locator("a[href]").evaluate_all(
            "nodes => nodes.map(a => ({text:a.textContent.trim(),url:a.href}))"
        )
    Path("records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


asyncio.run(main())
```

For a local fixture, authorize its host in both `allowed_target_hosts` and
`trusted_local_target_hosts`. Allow exact CDN/resource/redirect hosts as required.
Resource filtering is opt-in and can change rendering or break page behavior.

## Device selection

```python
await core.create_profile("android", family="android", backend="playwright")
await core.create_profile("desktop-firefox", family="desktop", backend="camoufox")
# Only an eligible Linux/macOS host with real WebKit checks:
await core.create_profile("iphone", family="ios", backend="playwright")
```

An unavailable engine is a compatibility error. Capability discovery performs real
local checks on first use and may take minutes. Do not fake manifests. Profiles
default to persistent reuse; `fresh=True` is a single-use new/cold condition and
requires `base_url` when opening its session.

Use `asyncio.Semaphore` and separate profile IDs for parallel tasks. Never open the
same profile concurrently or retry side-effecting actions after an uncertain result
without application-specific handling. `maintain_presence()` is optional UX activity,
not a requirement for scraping.

## Provider-controlled IP rotation

```python
import os
from pydantic import SecretStr
from syntetic_core import CoreSettings, HttpRotationProvider, ProxyConfig, SynteticCore

proxy = ProxyConfig(
    id="mobile-1",
    server=os.environ["PROXY_SERVER"],
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]),
    kind="mobile",
)
core = SynteticCore(
    "/absolute/task/profiles",
    settings=CoreSettings(
        proxies=[proxy],
        proxy_required=True,
        allowed_target_hosts=["example.com", "api.ipify.org"],
    ),
)
provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
    # Set json_body/success_field/success_value according to the provider contract.
)
# Inside the task's async function, between browser sessions:
# result = await core.rotate_ip("mobile-1", provider,
#                               probe_url="https://api.ipify.org?format=json")
```

For custom SDKs, implement `async def rotate(self, proxy: ProxyConfig) -> None`.
Raise on failure; let the core handle locking, deadlines, and independent IP
confirmation. Do not automatically retry a provider rotation request. Keep shared
modem ports mapped to the same `proxy_channels` identifier. OS locks coordinate
only one host/shared local root, not multiple machines.
