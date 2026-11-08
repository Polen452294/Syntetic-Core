"""Per-session TCP pacing. TLS/HTTP bytes are produced by the browser unchanged."""

import asyncio
from time import monotonic

from syntetic_core._engine.browser_experiments import NetworkCondition


class NetworkPacer:
    def __init__(self) -> None:
        self.condition = NetworkCondition()
        self.next_slot = {"bytes_sent": 0.0, "bytes_received": 0.0}
        self.lock = asyncio.Lock()
        self.changed = asyncio.Event()

    def set(self, condition: NetworkCondition) -> None:
        self.changed.set()
        self.changed = asyncio.Event()
        self.condition = condition
        self.next_slot = dict.fromkeys(self.next_slot, 0.0)

    async def wait(self, size: int, direction: str) -> None:
        condition = self.condition
        if condition.offline:
            raise ConnectionResetError("Planned test network outage")
        rate = (
            (condition.upload_kbps if direction == "bytes_sent" else condition.download_kbps)
            * 1000
            / 8
        )
        async with self.lock:
            now = monotonic()
            start = max(now, self.next_slot[direction])
            end = start + size / rate if rate else now
            self.next_slot[direction] = end
        delay = max(0, end - now)
        if delay:
            changed = self.changed
            try:
                await asyncio.wait_for(changed.wait(), timeout=delay)
            except TimeoutError:
                return
            await self.wait(size, direction)
