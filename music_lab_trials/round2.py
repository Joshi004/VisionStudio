#!/usr/bin/env python3
"""Temporary helper for round 2 (MUSIC-005, Appendix C): starts the cases of round2_cases.json
and writes each case's guide text to the app, so the Music lab's "Round 2 trials" screen shows
what to verify, the source audio, what was done, and the outputs to rate. Standard library only.

    python3 round2.py list                        # the cases, the GPU runs each starts, the state
    python3 round2.py check                       # do the source runs from round 1 have audio?
    python3 round2.py estimate                    # GPU time, from how long round 1's jobs took
    python3 round2.py run --wave 1                # what WOULD start (nothing is sent without --go)
    python3 round2.py run --wave 1 --go           # start wave 1 (paid GPU jobs)
    python3 round2.py run I2-fear K4 --go         # start these cases
    python3 round2.py status                      # refresh, start free local steps that are ready, sync
    python3 round2.py sync                        # write the guides and run ids to the app

Waves: 0 free local files (no GPU), 1 a smoke test of every kind of call, 2 the rest of I plus J
and L, 3 K, 4 M and the L3 summary, 5 deferred (converting a recording to another mood: not run
until the owner asks). A step that needs an earlier run (the rain extension, the K4
crossfades) waits until that run has finished: run the case again later, or use `status` for the
free ones. A step that was started is never started again. Nothing is deleted.

It only calls the app's own Music Lab endpoints (BASE can be changed with MUSIC_LAB_URL).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import trigger

HERE = Path(__file__).resolve().parent
CASES_FILE = HERE / "round2_cases.json"
RESULTS_FILE = HERE / "round2_results.json"
CASE_PATH = "/api/lab/music/trials"
EDIT_OPERATIONS_WITH_WINDOW = ("repaint", "inpaint")


# --- Files --------------------------------------------------------------------------------


def load_config() -> dict[str, Any]:
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


def load_results() -> dict[str, Any]:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return {"_joins": {}, "cases": {}}


def save_results(results: dict[str, Any]) -> None:
    RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


def case_by_id(config: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in config["cases"]:
        if case["id"] == case_id:
            return case
    raise SystemExit(f"No case {case_id}.")


def step_entries(results: dict[str, Any], case_id: str) -> dict[str, Any]:
    return results["cases"].get(case_id, {}).get("steps", {})


def case_run_ids(results: dict[str, Any], case_id: str) -> list[int]:
    """The runs a case started, in step order."""
    entries = step_entries(results, case_id)
    ids: list[int] = []
    for key in sorted(entries, key=int):
        ids += entries[key].get("run_ids", [])
    return ids


def case_source_ids(results: dict[str, Any], case_id: str) -> list[int]:
    """The recordings a case made locally (its join steps), in step order."""
    entries = step_entries(results, case_id)
    return [entries[key]["source_id"] for key in sorted(entries, key=int) if entries[key].get("source_id")]


def gpu_runs(case: dict[str, Any]) -> int:
    return sum(step.get("variants", 1) for step in case["steps"] if step["type"] != "join")


def local_steps(case: dict[str, Any]) -> int:
    return sum(1 for step in case["steps"] if step["type"] == "join")


# --- Resolving references -----------------------------------------------------------------


def run_ref(results: dict[str, Any], ref: Any) -> int | None:
    """A run number, or the run of an earlier case (`{"case_run": [case, index]}`). None when
    that run has not been started yet."""
    if isinstance(ref, int):
        return ref
    case_id, index = ref["case_run"]
    ids = case_run_ids(results, case_id)
    return ids[index] if index < len(ids) else None


def run_is_ready(run_id: int) -> bool:
    run = trigger.call("GET", f"/api/lab/music/runs/{run_id}")
    return run.get("url") is not None


def ensure_join(results: dict[str, Any], join: dict[str, Any], dry_run: bool) -> int | str | None:
    """The id of a join (made once, then reused). None when a run it needs is not ready.
    Joining is local: nothing goes to the GPU server."""
    run_ids = [run_ref(results, ref) for ref in join["runs"]]
    if any(run_id is None for run_id in run_ids):
        return None
    body = {
        "run_ids": run_ids,
        "gap_s": join.get("gap_s", 0),
        "tail_s": join.get("tail_s", 0),
        "crossfade_s": join.get("crossfade_s", 0),
    }
    key = json.dumps(body, sort_keys=True)
    known = results["_joins"].get(key)
    if known is not None:
        return known
    if dry_run:
        print(f"    would join {body}")
        return "<the join>"
    if not all(run_is_ready(run_id) for run_id in run_ids):
        return None
    made = trigger.call("POST", "/api/lab/music/sources/join", body)
    print(f"    joined {body}: source {made['id']} ({made['duration_s']:.1f} s)")
    results["_joins"][key] = made["id"]
    save_results(results)
    return made["id"]


def edit_source(results: dict[str, Any], source: dict[str, Any], dry_run: bool) -> dict[str, Any] | None:
    """`source_run_id` or `source_id` for an edit. None when the source is not ready."""
    if "join" in source:
        source_id = ensure_join(results, source["join"], dry_run)
        return None if source_id is None else {"source_run_id": None, "source_id": source_id}
    run_id = run_ref(results, source if "case_run" in source else source["run"])
    if run_id is None:
        return None
    if not dry_run and not run_is_ready(run_id):
        return None
    return {"source_run_id": run_id, "source_id": None}


# --- Starting a step ----------------------------------------------------------------------


def start_step(
    config: dict[str, Any], case: dict[str, Any], index: int, results: dict[str, Any], dry_run: bool
) -> str:
    """Starts one step. Returns "started", "done" (already started), "waiting" (needs a run that
    is not ready) or "dry"."""
    entries = results["cases"].setdefault(case["id"], {"steps": {}})["steps"]
    if str(index) in entries:
        return "done"
    step = case["steps"][index]
    seed = step.get("seed", config["defaults"]["seed"])
    label = f"[{case['id']}] step {index + 1}: {step['label']}"

    if step["type"] == "join":
        source_id = ensure_join(results, step["join"], dry_run)
        if source_id is None:
            print(f"  {label}: waiting for the run it needs")
            return "waiting"
        if dry_run:
            return "dry"
        entries[str(index)] = {"kind": "local", "source_id": source_id, "run_ids": []}
        print(f"  {label}: made recording {source_id}")
        return "started"

    if step["type"] == "text":
        brief: dict[str, Any] = {"description": f"[{case['id']}] {step['description']}"}
        if step.get("duration_s"):
            brief["duration_s"] = step["duration_s"]
        body: dict[str, Any] = {
            "kind": step["kind"],
            "brief": brief,
            "models": [{"model": step["model"], "fields": step["fields"]}],
            "variants": step.get("variants", 1),
            "seed": seed,
        }
        path = "/api/lab/music/runs"
        operation = None
    else:
        source = edit_source(results, step["source"], dry_run)
        if source is None:
            print(f"  {label}: waiting for the run it needs")
            return "waiting"
        body = {
            "operation": step["operation"],
            "model": step["model"],
            "kind": step["kind"],
            "description": f"[{case['id']}] {step['description']}",
            **source,
            "fields": step["fields"],
            "variants": step.get("variants", 1),
            "seed": seed,
        }
        path = "/api/lab/music/edits"
        operation = step["operation"]

    if dry_run:
        print(f"  {label}: would start {step.get('variants', 1)} GPU run(s)")
        print("    " + json.dumps(body, ensure_ascii=False)[:400])
        return "dry"
    runs = trigger.call("POST", path, body)
    entries[str(index)] = {
        "kind": "runs",
        "run_ids": [run["id"] for run in runs],
        "group_key": runs[0]["group_key"] if runs else None,
        "operation": operation,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_results(results)
    print(f"  {label}: started runs {entries[str(index)]['run_ids']}")
    return "started"


# --- Writing the guides to the app --------------------------------------------------------


def run_labels(case: dict[str, Any], results: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    entries = step_entries(results, case["id"])
    for index, step in enumerate(case["steps"]):
        entry = entries.get(str(index))
        if entry is None:
            continue
        ids = entry.get("run_ids", [])
        for position, run_id in enumerate(ids):
            labels[str(run_id)] = f"{step['label']} {position + 1}" if len(ids) > 1 else step["label"]
    return labels


def collected_runs(config: dict[str, Any], case: dict[str, Any], results: dict[str, Any]) -> tuple[list[int], dict[str, str]]:
    """The runs a case shows, and their labels. A summary case (`runs_from`) shows the repaints
    and inpaints of other cases."""
    if "runs_from" not in case:
        return case_run_ids(results, case["id"]), run_labels(case, results)
    ids: list[int] = []
    labels: dict[str, str] = {}
    for other_id in case["runs_from"]:
        other = case_by_id(config, other_id)
        other_labels = run_labels(other, results)
        for key in sorted(step_entries(results, other_id), key=int):
            entry = step_entries(results, other_id)[key]
            if entry.get("operation") not in EDIT_OPERATIONS_WITH_WINDOW:
                continue
            for run_id in entry["run_ids"]:
                ids.append(run_id)
                labels[str(run_id)] = f"{other_id}: {other_labels.get(str(run_id), '')}"
    return ids, labels


def guide_sources(case: dict[str, Any], results: dict[str, Any], dry_run: bool) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for ref in case["guide"]["sources"]:
        if "join" in ref:
            source_id = ensure_join(results, ref["join"], dry_run)
            if isinstance(source_id, int):
                sources.append({"source_id": source_id, "label": ref["label"]})
            continue
        run_id = run_ref(results, ref if "case_run" in ref else ref["run"])
        if run_id is not None:
            sources.append({"run_id": run_id, "label": ref["label"]})
    return sources


def sync_case(config: dict[str, Any], case: dict[str, Any], results: dict[str, Any], dry_run: bool) -> None:
    guide = case["guide"]
    run_ids, labels = collected_runs(config, case, results)
    source_ids = case_source_ids(results, case["id"])
    source_labels = {}
    entries = step_entries(results, case["id"])
    for index, step in enumerate(case["steps"]):
        entry = entries.get(str(index))
        if step["type"] == "join" and entry and entry.get("source_id"):
            source_labels[str(entry["source_id"])] = step["label"]
    body = {
        "trial_group": case["group"],
        "sort_order": case["order"],
        "title": case["title"],
        "guide": {
            "question": guide["question"],
            "verify": guide["verify"],
            "did": guide["did"],
            "prompt_plain": guide["prompt_plain"],
            "sources": guide_sources(case, results, dry_run),
            "run_labels": labels,
            "source_labels": source_labels,
        },
        "run_ids": run_ids,
        "source_ids": source_ids,
    }
    if dry_run:
        return
    trigger.call("PUT", f"{CASE_PATH}/{case['id']}", body)


def sync_all(config: dict[str, Any], results: dict[str, Any], dry_run: bool = False) -> None:
    for case in config["cases"]:
        sync_case(config, case, results, dry_run)
    if not dry_run:
        print(f"Wrote {len(config['cases'])} cases to the app.")


# --- Commands -----------------------------------------------------------------------------


def parse_time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def all_runs() -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    before = None
    while True:
        path = "/api/lab/music/runs?limit=50" + (f"&before_id={before}" if before else "")
        page = trigger.call("GET", path)
        if not page:
            return runs
        runs += page
        before = page[-1]["id"]


def cmd_list(config: dict[str, Any], results: dict[str, Any]) -> None:
    total = 0
    for case in config["cases"]:
        entries = step_entries(results, case["id"])
        done = f"{len(entries)}/{len(case['steps'])}" if case["steps"] else "-"
        count = gpu_runs(case)
        total += count
        local = f" + {local_steps(case)} local" if local_steps(case) else ""
        print(f"wave {case['wave']}  {case['id']:13} {count:2} GPU run(s){local}  started {done:5} {case['title']}")
    by_wave: dict[int, int] = {}
    for case in config["cases"]:
        by_wave[case["wave"]] = by_wave.get(case["wave"], 0) + gpu_runs(case)
    print(f"total {total} GPU runs. By wave: " + ", ".join(f"{w}: {n}" for w, n in sorted(by_wave.items())))


def cmd_check(config: dict[str, Any]) -> None:
    wanted: set[int] = set()
    for case in config["cases"]:
        for step in case["steps"]:
            source = step.get("source")
            if source and "run" in source:
                wanted.add(source["run"])
            if source and "join" in source:
                wanted.update(r for r in source["join"]["runs"] if isinstance(r, int))
            if step["type"] == "join":
                wanted.update(r for r in step["join"]["runs"] if isinstance(r, int))
        for ref in case["guide"]["sources"]:
            if "run" in ref:
                wanted.add(ref["run"])
    bad = 0
    for run_id in sorted(wanted):
        run = trigger.call("GET", f"/api/lab/music/runs/{run_id}")
        ok = run.get("url") is not None
        bad += 0 if ok else 1
        print(f"run {run_id:3} {run['model']:15} {run.get('duration_s')} s  {'audio ok' if ok else 'NO AUDIO'}")
    print("All source runs have audio." if bad == 0 else f"{bad} source run(s) have no audio.")


def cmd_estimate(config: dict[str, Any]) -> None:
    seconds: dict[str, list[float]] = {}
    for run in all_runs():
        job = run.get("job") or {}
        started, finished = parse_time(job.get("started_at")), parse_time(job.get("finished_at"))
        if job.get("status") == "succeeded" and started and finished:
            seconds.setdefault(run["model"], []).append((finished - started).total_seconds())
    medians = {model: statistics.median(values) for model, values in seconds.items()}
    for model, values in sorted(seconds.items()):
        print(f"{model:18} {len(values):3} earlier runs, median {medians[model]:.0f} s, longest {max(values):.0f} s")
    counts: dict[str, int] = {}
    for case in config["cases"]:
        for step in case["steps"]:
            if step["type"] != "join":
                counts[step["model"]] = counts.get(step["model"], 0) + step.get("variants", 1)
    total = 0.0
    for model, count in sorted(counts.items()):
        per = medians.get(model)
        if per is None:
            print(f"{model:18} {count:3} runs planned, no earlier runs to estimate from")
            continue
        total += per * count
        print(f"{model:18} {count:3} runs planned, about {per * count / 60:.0f} min of GPU time")
    print(f"About {total / 60:.0f} minutes of GPU time in all. Editing and long runs may take longer than text runs.")


def cmd_run(config: dict[str, Any], results: dict[str, Any], args: argparse.Namespace) -> None:
    chosen = [case_by_id(config, case_id) for case_id in args.cases]
    if args.wave is not None:
        chosen += [case for case in config["cases"] if case["wave"] == args.wave]
    if args.group:
        chosen += [case for case in config["cases"] if case["group"] == args.group]
    if not chosen:
        raise SystemExit("Name a case, or use --wave or --group.")
    dry_run = not args.go
    runs = sum(gpu_runs(case) for case in chosen)
    print(("DRY RUN (add --go to start). " if dry_run else "") + f"{len(chosen)} case(s), up to {runs} GPU run(s).")
    for case in chosen:
        print(f"[{case['id']}] {case['title']}")
        for index in range(len(case["steps"])):
            start_step(config, case, index, results, dry_run)
    if not dry_run:
        save_results(results)
        sync_all(config, results)
        print("Open the Music lab, Round 2 trials, to listen and rate.")


def cmd_status(config: dict[str, Any], results: dict[str, Any]) -> None:
    # Free local steps (crossfades) start by themselves once the runs they need are ready.
    for case in config["cases"]:
        for index, step in enumerate(case["steps"]):
            if step["type"] == "join" and str(index) not in step_entries(results, case["id"]):
                started_any = case["id"] in results["cases"] and results["cases"][case["id"]]["steps"]
                if started_any or case["wave"] == 0:
                    start_step(config, case, index, results, dry_run=False)
    save_results(results)
    for case in config["cases"]:
        ids = case_run_ids(results, case["id"])
        counts: dict[str, int] = {}
        for run_id in ids:
            run = trigger.call("GET", f"/api/lab/music/runs/{run_id}")
            job = run.get("job") or {}
            state = "ready" if run.get("url") else job.get("status", "?")
            counts[state] = counts.get(state, 0) + 1
        steps_left = len(case["steps"]) - len(step_entries(results, case["id"]))
        summary = ", ".join(f"{n} {state}" for state, n in sorted(counts.items())) or "not started"
        waiting = f", {steps_left} step(s) not started" if steps_left and case["steps"] else ""
        print(f"{case['id']:13} {summary}{waiting}")
    sync_all(config, results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "check", "estimate", "status", "sync"):
        sub.add_parser(name)
    run = sub.add_parser("run")
    run.add_argument("cases", nargs="*")
    run.add_argument("--wave", type=int)
    run.add_argument("--group")
    run.add_argument("--go", action="store_true", help="really start the jobs (otherwise a dry run)")
    args = parser.parse_args()

    config = load_config()
    results = load_results()
    if args.command == "list":
        cmd_list(config, results)
    elif args.command == "check":
        cmd_check(config)
    elif args.command == "estimate":
        cmd_estimate(config)
    elif args.command == "run":
        cmd_run(config, results, args)
    elif args.command == "status":
        cmd_status(config, results)
    elif args.command == "sync":
        sync_all(config, results)
        save_results(results)


if __name__ == "__main__":
    sys.exit(main())
