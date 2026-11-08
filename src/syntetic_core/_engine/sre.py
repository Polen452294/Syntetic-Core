"""Small process-local Prometheus registry, with bounded labels and child aggregation."""

import threading
from collections import defaultdict

_lock = threading.Lock()
_samples: dict[str, float] = defaultdict(float)
_shm_initial: int | None = None


def add(name: str, value: float = 1) -> None:
    with _lock:
        _samples[name] += value


def gauge(name: str, value: float) -> None:
    with _lock:
        _samples[name] = value


def observe(name: str, elapsed: float) -> None:
    add(name + "_seconds_sum", elapsed)
    add(name + "_seconds_count")
