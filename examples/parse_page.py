"""python examples/parse_page.py https://example.com --profile catalog"""

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from syntetic_core import CoreSettings, SynteticCore


async def main(args: argparse.Namespace) -> None:
    host = urlsplit(args.url).hostname
    if host is None:
        raise ValueError("An absolute HTTP(S) URL is required")
    core = SynteticCore(settings=CoreSettings(allowed_target_hosts=[host, *args.resource_host]))
    try:
        core.load_profile(args.profile)
    except FileNotFoundError:
        await core.create_profile(args.profile, family=args.family)
    async with core.session(args.profile) as session:
        response = await session.goto(args.url)
        if response is None or response.status >= 400:
            raise RuntimeError("Target returned an unsuccessful navigation")
        await session.page.locator("body").wait_for(state="visible")
        result = {
            "title": await session.page.title(),
            "headings": await session.page.locator("h1, h2").all_text_contents(),
            "links": await session.page.locator("a[href]").evaluate_all(
                "nodes => nodes.map(a => ({text:a.textContent.trim(),url:a.href}))"
            ),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(result['links'])} links to {args.output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--profile", default="catalog")
    parser.add_argument("--family", choices=["desktop", "android", "ios"], default="desktop")
    parser.add_argument("--resource-host", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("data/page.json"))
    asyncio.run(main(parser.parse_args()))
