"""Standalone event sink boundary for the copied live-condition engine."""

from typing import Any, Protocol


class EventSink(Protocol):
    async def emit(self, event_type: str, **kwargs: Any) -> None: ...
