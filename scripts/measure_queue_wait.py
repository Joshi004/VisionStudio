"""How long jobs wait before they start, by job type. Read-only.

The database is opened with `mode=ro`, so nothing is written. It is meant to run inside the
backend container, where the database is at /data/app.db:

    docker cp scripts/measure_queue_wait.py visio-studio-backend-1:/tmp/measure_queue_wait.py
    docker exec visio-studio-backend-1 python /tmp/measure_queue_wait.py [--since 2026-11-02]

Wait is `started_at - created_at`; run is `finished_at - started_at`. A job that was put back in
the queue and started again shows its whole wait.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime

DEFAULT_DB = "/data/app.db"


def _seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--since", default="1970-01-01", help="only jobs created on or after")
    args = parser.parse_args()

    connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT type, provider, created_at, started_at, finished_at FROM job "
        "WHERE created_at >= ? AND started_at IS NOT NULL",
        (args.since,),
    ).fetchall()

    waits: dict[tuple[str, str], list[float]] = defaultdict(list)
    runs: dict[tuple[str, str], list[float]] = defaultdict(list)
    for job_type, provider, created, started, finished in rows:
        wait = _seconds(created, started)
        run = _seconds(started, finished)
        if wait is not None:
            waits[(job_type, provider)].append(wait)
        if run is not None:
            runs[(job_type, provider)].append(run)

    print(f"{len(rows)} jobs since {args.since}")
    print(
        f"{'type':34} {'provider':8} {'n':>5} {'wait p50':>9} {'wait p90':>9} {'wait max':>9} {'run avg':>8}"
    )
    for key, values in sorted(waits.items(), key=lambda item: -len(item[1])):
        run_values = runs.get(key, [])
        run_avg = f"{statistics.mean(run_values):8.1f}" if run_values else f"{'-':>8}"
        print(
            f"{key[0]:34} {key[1]:8} {len(values):5d} {_percentile(values, 0.5):9.1f} "
            f"{_percentile(values, 0.9):9.1f} {max(values):9.1f} {run_avg}"
        )

    for provider in ("llm", "gpu"):
        pooled = [w for (_t, p), values in waits.items() if p == provider for w in values]
        if pooled:
            print(
                f"ALL {provider}: n={len(pooled)} wait p50 {_percentile(pooled, 0.5):.1f} s, "
                f"p90 {_percentile(pooled, 0.9):.1f} s"
            )


if __name__ == "__main__":
    main()
