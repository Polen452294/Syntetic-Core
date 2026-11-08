"""Shared bounded interaction pacing."""

import math
import random

from syntetic_core._engine.personas import BehaviorConfig


def _sample_pause_ms(
    minimum: int,
    maximum: int,
    config: BehaviorConfig,
    rng: random.Random,
) -> int:
    """Short runs with a right tail, truncated to the caller's timing budget."""
    if minimum == maximum:
        return minimum
    span = maximum - minimum
    mu = math.log(span * config.pause_median_ratio)
    # Reject rather than clamp: clipping would create a spike at maximum.
    # median_ratio <= 1 guarantees at least 50% acceptance per draw.
    while True:
        offset = rng.lognormvariate(mu, config.pause_sigma)
        if offset <= span:
            return minimum + round(offset)
