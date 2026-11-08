"""Provider-neutral example. Configure environment before running.

Required: PROXY_SERVER, PROXY_USERNAME, PROXY_PASSWORD, ROTATION_API_URL,
ROTATION_AUTHORIZATION. The endpoint/method/body must match your provider contract.
"""

import argparse
import asyncio
import os
from urllib.parse import urlsplit

from pydantic import SecretStr

from syntetic_core import CoreSettings, HttpRotationProvider, ProxyConfig, SynteticCore


async def main(args: argparse.Namespace) -> None:
    target, probe_host = urlsplit(args.url).hostname, urlsplit(args.probe_url).hostname
    if target is None or probe_host is None:
        raise ValueError("Absolute target and probe URLs are required")
    proxy = ProxyConfig(
        id="mobile-1",
        server=os.environ["PROXY_SERVER"],
        username=SecretStr(os.environ["PROXY_USERNAME"]),
        password=SecretStr(os.environ["PROXY_PASSWORD"]),
        kind="mobile",
    )
    core = SynteticCore(
        settings=CoreSettings(
            allowed_target_hosts=[target, probe_host, *args.resource_host],
            proxies=[proxy],
            proxy_required=True,
        )
    )
    provider = HttpRotationProvider(
        url=SecretStr(os.environ["ROTATION_API_URL"]),
        method=args.method,
        headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
    )
    await core.rotate_ip(proxy.id, provider, probe_url=args.probe_url)
    print("Provider rotation confirmed through the assigned proxy")
    persona = await core.create_profile(family="android", proxy_id=proxy.id)
    async with core.session(persona.id) as session:
        await session.goto(args.url)
        print(await session.page.title())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--probe-url", default="https://api.ipify.org?format=json")
    parser.add_argument("--method", choices=["GET", "POST", "PUT", "PATCH"], default="POST")
    parser.add_argument("--resource-host", action="append", default=[])
    asyncio.run(main(parser.parse_args()))
