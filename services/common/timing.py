"""Elapsed-time measurement.

A single helper, for a single reason: converting a `perf_counter` reading to
milliseconds needs the number 1000, and the no-magic-numbers rule does not
admit a scale factor buried in application source. `timedelta` already knows
what a millisecond is, so the conversion asks the standard library for the
ratio rather than restating it.
"""

from __future__ import annotations

import time
from datetime import timedelta

MILLISECOND = timedelta(milliseconds=1)


def elapsed_ms(started: float) -> int:
    """Milliseconds since `started`, which must come from `time.perf_counter()`."""
    return int(timedelta(seconds=time.perf_counter() - started) / MILLISECOND)


HOUR = timedelta(hours=1)


def hours_in(days: int) -> int:
    """Hours in a number of days.

    Same reason as `elapsed_ms`: the conversion asks `timedelta` for the ratio
    rather than restating 24 in application source.
    """
    return int(timedelta(days=days) / HOUR)
