#!/usr/bin/env python3
"""Temporary helper: starts the Music Lab trial cases in cases.json (standard library only).

    python3 trigger.py list                    # the cases and how many runs each starts
    python3 trigger.py run E2                  # start one or more cases, then wait for them
    python3 trigger.py run --group E           # start every case of a group
    python3 trigger.py run E2 --dry-run        # print what would be sent, send nothing
    python3 trigger.py run E2 --force          # start a case again (default: skip if done)
    python3 trigger.py run A1 --no-wait        # do not wait for the audio
    python3 trigger.py status                  # refresh results.json from the app
    python3 trigger.py tracker                 # copy run ids and statuses into TRACKER.md

An "edit" case ("type": "edit" in cases.json) edits an earlier run or a join of two runs: its
"source" is {"run": N} or {"join": {"runs": [a, b], "gap_s": 0, "tail_s": 0}}. A join is made
once and its id is kept in results.json under "_joins", so a second case can reuse it.

It only calls the app's own Music Lab endpoints. Nothing is deleted. Every run is a paid GPU job.
The base URL can be changed with the MUSIC_LAB_URL environment variable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASES_FILE = HERE / "cases.json"
RESULTS_FILE = HERE / "results.json"
TRACKER_FILE = HERE / "TRACKER.md"
BASE = os.environ.get("MUSIC_LAB_URL", "http://localhost:5480").rstrip("/")

ACTIVE = ("queued", "running")
POLL_SECONDS = 10
DRAFT_TIMEOUT_S = 300
RUN_TIMEOUT_S = 40 * 60

SAO, SA3, LTX = "stable-audio-open", "stable-audio-3", "ltx-audio"


# --- HTTP ---------------------------------------------------------------------------------


def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"{method} {path} failed: {exc.reason}") from exc


# --- Files --------------------------------------------------------------------------------


def load_cases() -> dict[str, Any]:
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


def load_results() -> dict[str, Any]:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return {}


def save_results(results: dict[str, Any]) -> None:
    RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


# --- Building a request -------------------------------------------------------------------


def case_by_id(config: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in config["cases"]:
        if case["id"] == case_id:
            return case
    raise SystemExit(f"No case {case_id}.")


def model_id(item: Any) -> str:
    return item if isinstance(item, str) else item["model"]


def plain_brief(config: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """The brief without the case tag: the story context, then the case's own parts."""
    if "brief_from" in case:
        brief = plain_brief(config, case_by_id(config, case["brief_from"]))
    else:
        brief = dict(config["stories"][case["story"]])
        brief.update(case["brief"])
    for key, value in case.get("brief_patch", {}).items():
        if value is None:
            brief.pop(key, None)
        else:
            brief[key] = value
    return brief


def tagged_brief(config: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    brief = plain_brief(config, case)
    brief["description"] = f"[{case['id']}] {brief['description']}"
    return brief


def shared_fields(case: dict[str, Any], model: str) -> dict[str, Any]:
    """The same description for every sound-effect or ambience model, written the way each
    model wants it, so the models are compared on equal terms."""
    shared = case["shared"]
    text = shared["text"]
    duration = shared.get("durations", {}).get(model, shared.get("duration"))
    if model == SAO:
        return {
            "prompt": text,
            "negative_prompt": shared.get("negative", "Low quality, music, speech."),
            "duration": duration,
        }
    if model == SA3:
        return {"prompt": "TrackType: SFX. " + text, "duration": duration}
    if model == LTX:
        return {
            "prompt": text,
            "negative_prompt": shared.get("negative", "music, speech, voices, distortion, clipping"),
            "duration": duration,
        }
    raise SystemExit(f"Case {case['id']}: no shared prompt rule for {model}.")


def fields_for(config: dict[str, Any], case: dict[str, Any], item: Any) -> dict[str, Any]:
    model = model_id(item)
    if isinstance(item, dict) and "fields" in item:
        return item["fields"]
    if isinstance(item, dict) and "fields_from" in item:
        source = case_by_id(config, item["fields_from"])
        for other in source["models"]:
            if model_id(other) == model:
                return fields_for(config, source, other)
        raise SystemExit(f"Case {case['id']}: {item['fields_from']} has no {model}.")
    if "shared" in case:
        return shared_fields(case, model)
    raise SystemExit(f"Case {case['id']}: no fields for {model}.")


# --- Prompt drafts ------------------------------------------------------------------------


def draft(model: str, kind: str, brief: dict[str, Any]) -> tuple[dict[str, Any], list[str], int]:
    job = call("POST", "/api/lab/music/prompt-drafts", {"model": model, "kind": kind, "brief": brief})
    job_id = job["id"]
    print(f"  prompt draft for {model}: job {job_id}")
    deadline = time.time() + DRAFT_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(3)
        job = call("GET", f"/api/jobs/{job_id}")
        if job["status"] == "succeeded":
            output = job.get("output") or {}
            return output["fields"], list(output.get("warnings") or []), job_id
        if job["status"] in ("failed", "cancelled"):
            raise SystemExit(f"Prompt draft job {job_id} {job['status']}: {job.get('error')}")
    raise SystemExit(f"Prompt draft job {job_id} did not finish in {DRAFT_TIMEOUT_S} s.")


# --- Running a case -----------------------------------------------------------------------


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    job = run.get("job") or {}
    return {
        "id": run["id"],
        "model": run["model"],
        "seed": (run.get("params") or {}).get("seed"),
        "job_id": job.get("id"),
        "status": job.get("status"),
        "error": job.get("error"),
        "duration_s": run.get("duration_s"),
        "url": run.get("url"),
    }


def join_key(join: dict[str, Any]) -> str:
    return json.dumps(join, sort_keys=True)


def source_ids(case: dict[str, Any], results: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    """`source_run_id` or `source_id` of an edit case. A join is made once and then reused."""
    source = case["source"]
    if "run" in source:
        return {"source_run_id": source["run"], "source_id": None}
    join = source["join"]
    key = join_key(join)
    known = results.get("_joins", {}).get(key)
    if known is not None:
        print(f"  using the join already made (source {known})")
        return {"source_run_id": None, "source_id": known}
    if dry_run:
        print(f"  would join runs {join['runs']} (gap {join.get('gap_s', 0)} s, tail {join.get('tail_s', 0)} s)")
        return {"source_run_id": None, "source_id": "<the join>"}
    made = call(
        "POST",
        "/api/lab/music/sources/join",
        {"run_ids": join["runs"], "gap_s": join.get("gap_s", 0), "tail_s": join.get("tail_s", 0)},
    )
    print(f"  joined runs {join['runs']}: source {made['id']} ({made['duration_s']:.1f} s)")
    results.setdefault("_joins", {})[key] = made["id"]
    save_results(results)
    return {"source_run_id": None, "source_id": made["id"]}


def start_edit(
    config: dict[str, Any], case: dict[str, Any], results: dict[str, Any], dry_run: bool
) -> dict[str, Any] | None:
    body = {
        "operation": case["operation"],
        "model": case["model"],
        "kind": case["kind"],
        "description": f"[{case['id']}] {case['description']}",
        **source_ids(case, results, dry_run),
        "fields": case["fields"],
        "variants": case.get("variants", 1),
        "seed": case.get("seed", config["defaults"]["seed"]),
    }
    if dry_run:
        print(json.dumps(body, indent=2, ensure_ascii=False))
        return None
    runs = call("POST", "/api/lab/music/edits", body)
    print(f"  started {len(runs)} edit(s): " + ", ".join(f"{r['id']} ({r['model']})" for r in runs))
    return {
        "title": case["title"],
        "triggered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "group_key": runs[0]["group_key"] if runs else None,
        "runs": [run_summary(r) for r in runs],
        "drafts": {},
    }


def start_case(
    config: dict[str, Any], case: dict[str, Any], dry_run: bool, results: dict[str, Any]
) -> dict[str, Any] | None:
    print(f"[{case['id']}] {case['title']}")
    if case.get("type") == "edit":
        return start_edit(config, case, results, dry_run)
    models = []
    drafts: dict[str, Any] = {}
    for item in case["models"]:
        model = model_id(item)
        entry: dict[str, Any] = {"model": model}
        if case.get("draft"):
            if dry_run:
                print(f"  would draft the fields for {model}")
                continue
            fields, warnings, job_id = draft(model, case["kind"], plain_brief(config, case))
            entry["fields"] = fields
            entry["prompt_job_id"] = job_id
            drafts[model] = {"prompt_job_id": job_id, "warnings": warnings, "fields": fields}
        else:
            entry["fields"] = fields_for(config, case, item)
        models.append(entry)

    body = {
        "kind": case["kind"],
        "brief": tagged_brief(config, case),
        "models": models,
        "variants": case.get("variants", 1),
        "seed": case.get("seed", config["defaults"]["seed"]),
    }
    if dry_run:
        print(json.dumps(body, indent=2, ensure_ascii=False))
        return None

    runs = call("POST", "/api/lab/music/runs", body)
    print(f"  started {len(runs)} run(s): " + ", ".join(f"{r['id']} ({r['model']})" for r in runs))
    return {
        "title": case["title"],
        "triggered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "group_key": runs[0]["group_key"] if runs else None,
        "runs": [run_summary(r) for r in runs],
        "drafts": drafts,
    }


def case_entries(results: dict[str, Any]) -> dict[str, Any]:
    """The triggered cases of results.json (keys that start with "_" are bookkeeping)."""
    return {case_id: entry for case_id, entry in results.items() if not case_id.startswith("_")}


def refresh(results: dict[str, Any], case_ids: list[str] | None = None) -> None:
    for case_id, entry in case_entries(results).items():
        if case_ids is not None and case_id not in case_ids:
            continue
        entry["runs"] = [run_summary(call("GET", f"/api/lab/music/runs/{r['id']}")) for r in entry["runs"]]


def wait_for(results: dict[str, Any], case_ids: list[str]) -> None:
    deadline = time.time() + RUN_TIMEOUT_S
    while True:
        refresh(results, case_ids)
        save_results(results)
        active = [
            r["id"]
            for case_id in case_ids
            for r in results[case_id]["runs"]
            if r["status"] in ACTIVE
        ]
        print(f"  waiting: {len(active)} run(s) still active {active}")
        if not active:
            return
        if time.time() > deadline:
            print("  gave up waiting; run `status` later.")
            return
        time.sleep(POLL_SECONDS)


def print_outcome(results: dict[str, Any], case_ids: list[str]) -> None:
    for case_id in case_ids:
        for r in results[case_id]["runs"]:
            tail = f" error: {r['error']}" if r["error"] else f" {r['duration_s']} s"
            print(f"  {case_id} run {r['id']} {r['model']}: {r['status']}{tail}")


# --- Tracker ------------------------------------------------------------------------------


def runs_block(case_id: str, entry: dict[str, Any] | None) -> str:
    start, end = f"<!-- RUNS:{case_id} -->", f"<!-- /RUNS:{case_id} -->"
    if entry is None:
        body = "Not triggered yet."
    else:
        lines = [
            f"Group key `{entry['group_key']}`, triggered {entry['triggered_at']}. "
            f"In the Music Lab, look for the group whose description starts with `[{case_id}]`.",
            "",
            "| Run | Model | Seed | Status | Length (s) | Error |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in entry["runs"]:
            length = "" if r["duration_s"] is None else f"{r['duration_s']:.1f}"
            error = (r["error"] or "").replace("\n", " ").replace("|", "/")
            lines.append(f"| {r['id']} | {r['model']} | {r['seed']} | {r['status']} | {length} | {error} |")
        for model, info in entry.get("drafts", {}).items():
            warnings = "; ".join(info["warnings"]) or "none"
            lines.append("")
            lines.append(f"Prompt draft for {model} (job {info['prompt_job_id']}), warnings: {warnings}")
        body = "\n".join(lines)
    return f"{start}\n{body}\n{end}"


def update_tracker(results: dict[str, Any], config: dict[str, Any]) -> None:
    text = TRACKER_FILE.read_text(encoding="utf-8")
    for case in config["cases"]:
        case_id = case["id"]
        start, end = f"<!-- RUNS:{case_id} -->", f"<!-- /RUNS:{case_id} -->"
        first, last = text.find(start), text.find(end)
        if first == -1 or last == -1:
            print(f"  TRACKER.md has no marker for {case_id}; skipped")
            continue
        text = text[:first] + runs_block(case_id, results.get(case_id)) + text[last + len(end):]
    TRACKER_FILE.write_text(text, encoding="utf-8")
    print("TRACKER.md updated.")


# --- Commands -----------------------------------------------------------------------------


def run_count(config: dict[str, Any], case: dict[str, Any]) -> int:
    models = 1 if case.get("type") == "edit" else len(case["models"])
    return models * case.get("variants", 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("cases", nargs="*")
    run.add_argument("--group")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--force", action="store_true")
    run.add_argument("--no-wait", action="store_true")
    sub.add_parser("status")
    sub.add_parser("tracker")
    args = parser.parse_args()

    config = load_cases()
    results = load_results()

    if args.command == "list":
        total = 0
        for case in config["cases"]:
            count = run_count(config, case)
            total += count
            done = "done" if case["id"] in case_entries(results) else "    "
            print(f"{done} {case['id']:4} {case['kind']:8} {count} run(s)  {case['title']}")
        print(f"total {total} runs")
        return

    if args.command == "status":
        refresh(results)
        save_results(results)
        print_outcome(results, list(case_entries(results)))
        return

    if args.command == "tracker":
        refresh(results)
        save_results(results)
        update_tracker(results, config)
        return

    chosen = [case_by_id(config, c) for c in args.cases]
    if args.group:
        chosen += [c for c in config["cases"] if c["group"] == args.group]
    if not chosen:
        raise SystemExit("Name a case or use --group.")

    started: list[str] = []
    for case in chosen:
        if case["id"] in results and not args.force and not args.dry_run:
            print(f"[{case['id']}] already triggered; skipped (use --force to start it again)")
            continue
        entry = start_case(config, case, args.dry_run, results)
        if entry is not None:
            if case["id"] in results:
                # Keep the earlier attempt on record.
                entry["earlier_attempts"] = results[case["id"]].get("earlier_attempts", []) + [
                    {"group_key": results[case["id"]]["group_key"], "runs": results[case["id"]]["runs"]}
                ]
            results[case["id"]] = entry
            save_results(results)
            started.append(case["id"])

    if started and not args.no_wait:
        wait_for(results, started)
    if started:
        print_outcome(results, started)


if __name__ == "__main__":
    sys.exit(main())
