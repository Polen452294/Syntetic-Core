"""Bounded independent browser sessions; one profile per task.

python examples/parallel_sessions.py https://example.com https://example.com --limit 2
"""

import argparse
import asyncio
from urllib.parse import urlsplit

from syntetic_core import CoreSettings, SynteticCore


async def main(urls: list[str], limit: int) -> None:
    if not 1 <= limit <= 16:
        raise ValueError("Choose concurrency between 1 and 16 for this example")
    hosts = {urlsplit(url).hostname for url in urls}
    if None in hosts:
        raise ValueError("Every URL must be absolute")
    core = SynteticCore(settings=CoreSettings(allowed_target_hosts=sorted(hosts)))
    await core.capabilities()
    semaphore = asyncio.Semaphore(limit)

    async def collect(url: str) -> str:
        async with semaphore:
            persona = await core.create_profile()  # Generated unique profile ID.
            async with core.session(persona.id) as session:
                await session.goto(url)
                return await session.page.title()

    # TaskGroup cancels siblings and closes contexts if one task fails.
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(collect(url)) for url in urls]
    for url, task in zip(urls, tasks, strict=True):
        print(url, task.result())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--limit", type=int, default=2)
    args = parser.parse_args()
    asyncio.run(main(args.urls, args.limit))
