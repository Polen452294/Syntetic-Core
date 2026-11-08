"""Explicit setup, capability inspection, profile creation and a small browser probe."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from syntetic_core._engine.browser.playwright_worker_control import install
from syntetic_core._engine.config import Settings
from syntetic_core.core import SynteticCore


async def run(args: argparse.Namespace) -> None:
    settings = Settings(allowed_target_hosts=args.allow_host or [])
    core = SynteticCore(args.profiles, settings=settings)
    if args.command == "doctor":
        print(json.dumps(await core.capabilities(), ensure_ascii=False, indent=2))
    elif args.command == "create":
        persona = await core.create_profile(args.id, family=args.family, backend=args.backend)
        print(
            json.dumps(
                {
                    "id": persona.id,
                    "engine": persona.browser_engine,
                    "fingerprint_id": persona.fingerprint_id,
                },
                indent=2,
            )
        )
    elif args.command == "open":
        async with core.session(args.id) as session:
            await session.goto(args.url)
            print(
                json.dumps(
                    {"title": await session.page.title(), "engine": session.persona.browser_engine},
                    ensure_ascii=False,
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(prog="syntetic-core")
    parser.add_argument("--profiles", type=Path, default=Path("data/profiles"))
    parser.add_argument("--allow-host", action="append", default=[])
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="Install Playwright runtime and checked driver patch")
    prepare.add_argument("--engine", choices=["chromium", "webkit"], default="chromium")
    sub.add_parser("doctor", help="Run real local runtime and optional feature checks")
    create = sub.add_parser("create")
    create.add_argument("--id")
    create.add_argument("--family", choices=["desktop", "android", "ios"], default="desktop")
    create.add_argument("--backend", choices=["playwright", "camoufox"], default="playwright")
    browse = sub.add_parser("open")
    browse.add_argument("id")
    browse.add_argument("url")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            subprocess.run([sys.executable, "-m", "playwright", "install", args.engine], check=True)
            install()
        else:
            asyncio.run(run(args))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        # Configs and provider errors may carry credentials. Show only the exception class.
        print(
            f"Syntetic Core failed ({type(exc).__name__}); see docs/TROUBLESHOOTING.md",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
