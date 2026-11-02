"""Scheduler health numbers, kept in memory for the last few minutes.

They answer one question: where does the time go between "a job is wanted" and "a job is
running"? The dispatcher, the story pipeline run, the database pool and an event-loop
watcher each record numbers here. `GET /api/jobs/diagnostics` shows them.

- A series is a list of recent samples (a time and a number). `summary()` gives the count,
  median, 90th percentile and maximum of the samples inside the window.
- A counter only counts up since the process started.
- Nothing is written to the database or to disk, and the numbers are lost with the process.

Series names in use:

- `tick_s`, `tick_read_s`, `tick_polls_s`, `tick_start_s`: one dispatcher tick, and its parts.
- `tick_started`: how many queued jobs one tick started.
- `poll_s:<job type>`: how long one poll of that kind of job took (the story pipeline run is
  polled inside the tick, so a slow run shows here).
- `pipeline_evaluate_s`, `pipeline_apply_s`: the two halves of one pipeline run poll.
- `pipeline_made`, `pipeline_deferred`: jobs one poll made, and targets it left for the next.
- `queue_wait_s:<pool>`: how long a job waited from creation to being claimed.
- `loop_lag_s`: how late the event loop woke a task that asked for 0.5 s of sleep.
- `pool_hold_s`: how long a database connection was held. `pool_in_use`: connections held
  at each checkout.

Counters: `pool_timeouts` (a database connection was not free in time).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Final

from sqlalchemy.exc import TimeoutError as PoolTimeoutError

_logger = logging.getLogger(__name__)

# Samples older than this are left out of the summary.
WINDOW_S: Final = 600.0
# The most samples kept per series (older ones drop out first).
MAX_SAMPLES: Final = 5000
LOOP_CHECK_S: Final = 0.5
# A lag above this is logged: the event loop was blocked for that long.
LOOP_LAG_WARN_S: Final = 2.0

_series: dict[str, deque[tuple[float, float]]] = {}
_counters: dict[str, int] = {}
_loop_task: asyncio.Task[None] | None = None


def record(name: str, value: float) -> None:
    """Adds one sample to a series."""
    samples = _series.get(name)
    if samples is None:
        samples = _series[name] = deque(maxlen=MAX_SAMPLES)
    samples.append((time.monotonic(), float(value)))


def incr(name: str, amount: int = 1) -> None:
    _counters[name] = _counters.get(name, 0) + amount


def note_exception(exc: BaseException) -> None:
    """Counts an exception that says the database pool had no free connection in time."""
    if isinstance(exc, PoolTimeoutError):
        incr("pool_timeouts")


def _percentile(sorted_values: list[float], fraction: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * fraction))]


def summary() -> dict[str, Any]:
    """`{"window_s", "series": {name: {count, p50, p90, max}}, "counters": {name: n}}`."""
    cutoff = time.monotonic() - WINDOW_S
    series: dict[str, dict[str, float]] = {}
    for name, samples in sorted(_series.items()):
        values = sorted(value for stamp, value in samples if stamp >= cutoff)
        if not values:
            continue
        series[name] = {
            "count": len(values),
            "p50": round(_percentile(values, 0.5), 3),
            "p90": round(_percentile(values, 0.9), 3),
            "max": round(values[-1], 3),
        }
    return {
        "window_s": int(WINDOW_S),
        "series": series,
        "counters": dict(sorted(_counters.items())),
    }


async def _watch_loop() -> None:
    """Sleeps a short time over and over. How much later than asked it wakes is how long the
    event loop was busy with something else.
    """
    while True:
        asked = time.monotonic()
        await asyncio.sleep(LOOP_CHECK_S)
        lag = time.monotonic() - asked - LOOP_CHECK_S
        record("loop_lag_s", max(lag, 0.0))
        if lag > LOOP_LAG_WARN_S:
            _logger.warning("event loop was blocked for about %.1f s", lag)


def start_loop_watch() -> None:
    global _loop_task
    if _loop_task is None:
        _loop_task = asyncio.create_task(_watch_loop(), name="loop-lag-watch")


async def stop_loop_watch() -> None:
    global _loop_task
    task, _loop_task = _loop_task, None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
