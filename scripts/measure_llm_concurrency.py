"""How many paid-API (Bitdeer) calls ran at the same time, from the backend's log. Read-only.

Every call logs one line when it ends ("outbound POST ... -> 200 in 7391 ms"), so its start is
the end time minus the duration. The script rebuilds how many were open at each moment.

    docker logs visio-studio-backend-1 > /tmp/backend.log 2>&1
    python3 scripts/measure_llm_concurrency.py /tmp/backend.log

Also prints the pipeline's "made N" lines and the dispatcher's tick lines when the log has them.
"""

from __future__ import annotations

import re
import statistics
import sys
from collections import Counter
from datetime import datetime

BITDEER_LINE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d+) INFO app\.core\.outbound: "
    r"outbound POST https://api-inference\.bitdeer\.ai\S* -> (\S+) in (\d+) ms"
)
PIPELINE_LINE = re.compile(r"pipeline pass [\d.]+ s: .*made (\d+), deferred (\d+)")
TICK_LINE = re.compile(r"dispatcher tick ([\d.]+) s:")


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def main(path: str) -> None:
    calls: list[tuple[float, float, str]] = []  # start, end, status
    made: list[int] = []
    deferred: list[int] = []
    ticks: list[float] = []
    with open(path, encoding="utf-8", errors="replace") as log:
        for line in log:
            match = BITDEER_LINE.match(line)
            if match:
                end = (
                    datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S").timestamp()
                    + int(match[2]) / 1000
                )
                calls.append((end - int(match[4]) / 1000, end, match[3]))
                continue
            match = PIPELINE_LINE.search(line)
            if match:
                made.append(int(match[1]))
                deferred.append(int(match[2]))
                continue
            match = TICK_LINE.search(line)
            if match:
                ticks.append(float(match[1]))

    if not calls:
        print("no Bitdeer calls in this log")
        return

    durations = [end - start for start, end, _status in calls]
    print(f"calls: {len(calls)}  statuses: {dict(Counter(status for *_x, status in calls))}")
    print(
        f"duration s: p50 {_percentile(durations, 0.5):.1f}  p90 {_percentile(durations, 0.9):.1f}"
        f"  max {max(durations):.1f}  mean {statistics.mean(durations):.1f}"
    )

    events = sorted([(start, 1) for start, _e, _s in calls] + [(end, -1) for _s, end, _x in calls])
    open_now = 0
    peak = 0
    seconds_at: Counter[int] = Counter()
    previous = events[0][0]
    for stamp, change in events:
        seconds_at[open_now] += stamp - previous
        previous = stamp
        open_now += change
        peak = max(peak, open_now)
    window = events[-1][0] - events[0][0]
    busy = sum(value for level, value in seconds_at.items() if level > 0)
    print(
        f"window {window / 60:.1f} min, peak concurrent {peak}, busy {100 * busy / window:.0f}% of the window"
    )
    print("  (levels that held at least 1% of the busy time)")
    for level in sorted(seconds_at):
        if level > 0 and seconds_at[level] >= 0.01 * busy:
            print(
                f"  {level:3d} at once: {seconds_at[level]:7.0f} s ({100 * seconds_at[level] / busy:.0f}% of busy time)"
            )

    if made:
        print(f"pipeline passes that made or deferred work: {len(made)}")
        print(f"  jobs made per pass: median {statistics.median(made)}, max {max(made)}")
        print(
            f"  targets deferred per pass: median {statistics.median(deferred)}, max {max(deferred)}"
        )
    if ticks:
        print(
            f"dispatcher ticks: {len(ticks)}, p50 {_percentile(ticks, 0.5):.1f} s, p90 {_percentile(ticks, 0.9):.1f} s"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: measure_llm_concurrency.py LOGFILE")
    main(sys.argv[1])
