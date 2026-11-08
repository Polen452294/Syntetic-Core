"""Inline the shared callable facade into each independently ordered init script."""

from functools import cache
from pathlib import Path


@cache
def _source() -> str:
    return Path(__file__).with_suffix(".js").read_text(encoding="utf-8")


def native_script(script: str) -> str:
    return script.replace("__NATIVE_FUNCTIONS__", _source())
