"""The takes of a story project's music cues and hits (MUSIC-010, `Music_implementation_phases.md`
Section 4.8, MD-10, MD-22, MD-23).

MUSIC-009 wrote, for every cue of the newest music plan that has something to generate, the
cue's items (the cue itself, then each hit it asked for) with several prompt wordings each. This
module makes the audio:

1. **Takes.** `start_run` makes one take for each wording of an item. A take is a Music lab run
   (`music_lab.add_run`: the lab's `lab_music` job, player and measurements are the take's own)
   plus a `music_take` row that says which cue, item and detail it was made for.
2. **Check and selection.** When a take's audio is stored (`on_audio_stored`, called by the
   `lab_music` job), it is measured (MUSIC-003) and checked (`check_take`). In an automatic run
   the first take of an item that passes is selected (`selected_by` is `auto`, MD-10). The claim
   is one atomic `UPDATE`, so two takes stored at the same moment cannot both win, a locked item
   is never changed and an owner's choice is never replaced.
3. **Retries.** A take that fails its check, while the item has no selection, is made again with
   the same prompt and a new seed, up to `music_take_max_retries` in one round.
4. **The owner.** `select` a take (even one that failed its check), `reject` it with a note (the
   `rewrite_music_prompt` job asks the model for a new wording from the note, and a new take is
   made, MD-23) or `lock` the selected one. A locked item is never regenerated, and its lock is
   carried over to the matching cue of a later plan version (`match_score`).

Nothing about being selected, rejected, locked or out of date is stored as a flag that can go
stale: the selected take is the newest-selected one that is not rejected, and whether a take is
out of date is worked out when it is read (the detail of its cue has changed since it was made).
This module creates rows and jobs. It never calls the GPU server or the language model itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, cast

from sqlalchemy import CursorResult, and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import settings as settings_service
from app.db.models import Job, LabMusicRun, MusicCue, MusicPlan, MusicTake, Project
from app.db.session import SessionLocal
from app.db.state_memo import memoized_state
from app.db.types import utcnow
from app.jobs import store
from app.providers import music_generator
from app.services import (
    audio_measurements,
    music_bible,
    music_cue_writer,
    music_cues,
    music_lab,
    music_models,
    music_themes,
)
from app.services import music_plan_writer as plan_writer
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "rewrite_music_prompt"
SELECTED_AUTO: Final = "auto"
SELECTED_OWNER: Final = "owner"

# The lab's kind of sound for each kind of cue.
LAB_KIND: Final[dict[str, music_models.MusicKind]] = {
    plan_writer.KIND_SCORE: "score",
    plan_writer.KIND_BED: "ambience",
    plan_writer.KIND_POINT: "sfx",
    plan_writer.KIND_HIT: "sfx",
}

# The technical check (Planning decides). Module constants, like the theme check's.
MAX_TRAILING_SILENCE_S: Final = 3.0
# Lock matching across plan versions (Planning decides, owner's choice 2026-10-25): a span must
# overlap the old one by at least this part of the longer of the two, a moment must be this close.
MIN_OVERLAP: Final = 0.5
MOMENT_TOLERANCE_S: Final = 2.0
# A span a little longer than the take's audio still fits (the plan's seconds are rounded).
LENGTH_TOLERANCE_S: Final = 0.05

BRIEF_MAX_CHARS: Final = 1900
NOTE_MAX_CHARS: Final = music_cue_writer.NOTE_MAX_CHARS

MUSIC_OFF_MESSAGE: Final = music_cues.MUSIC_OFF_MESSAGE
REPLACE_MESSAGE: Final = (
    "You chose a take that was made for an older version of its cue. Making the music again "
    "makes new takes, and a new one that passes its check replaces your choice, so it has to be "
    "confirmed."
)
LOCKED_MESSAGE: Final = "This cue is locked. Unlock it first."
BUSY_MESSAGE: Final = "A prompt for this cue is being rewritten, or its takes are being made. Wait."

TakeStatus = Literal["generating", "checking", "passed", "check_failed", "failed"]

# One backend process, so a module lock makes "count the retries, then add one" atomic.
_retry_lock = asyncio.Lock()


class MusicTakeError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- Pure helpers --------------------------------------------------------------------------


def detail_sha(detail: Any) -> str:
    """A hash of a cue's detail: which version of it a take was made for."""
    text = json.dumps(detail, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fold(text: object) -> str | None:
    return " ".join(text.split()).casefold() if isinstance(text, str) and text.strip() else None


def _cue_snapshot(cue: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    start = end = at = None
    if cue["kind"] in plan_writer.SPAN_KINDS:
        start, end = float(detail["start"]["seconds"]), float(detail["end"]["seconds"])
    else:
        at = float(detail["at"]["seconds"])
    return {
        "role": music_cue_writer.ROLE_CUE,
        "kind": cue["kind"],
        "theme_id": cue.get("theme_id"),
        "emotion": _fold(cue.get("emotion")),
        "start_s": start,
        "end_s": end,
        "at_s": at,
        "end_style": cue.get("end_style"),
    }


def snapshot_of(
    cue: dict[str, Any], detail: dict[str, Any], item: dict[str, Any]
) -> dict[str, Any]:
    """What lock matching reads about an item: its kind, theme and emotion, and its span or its
    moment. A hit also carries its cue's snapshot, so a hit matches only inside a matching cue.
    """
    parent = _cue_snapshot(cue, detail)
    if item["role"] != music_cue_writer.ROLE_HIT:
        return parent
    hit_id = str(item["id"]).split("/", 1)[1]
    hit = next(entry for entry in detail["hit_requests"] if entry["id"] == hit_id)
    return {
        "role": music_cue_writer.ROLE_HIT,
        "kind": plan_writer.KIND_HIT,
        "theme_id": None,
        "emotion": None,
        "start_s": None,
        "end_s": None,
        "at_s": float(hit["at"]["seconds"]),
        "end_style": None,
        "parent": parent,
    }


def match_score(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    new_span_s: float | None = None,
    old_audio_s: float | None = None,
) -> float | None:
    """How well an old locked take's snapshot matches a new item's, from 0.5 up to 1, or None
    when it does not match (Planning decides, owner's choice):

    - the same role and kind, theme and emotion;
    - a span overlaps the old one by at least half of the longer of the two, and is no longer
      than the take's audio (`new_span_s` and `old_audio_s`, when given);
    - a moment (a point sound, or a hit inside a matching cue) is within `MOMENT_TOLERANCE_S`.
    """
    if old["role"] != new["role"] or old["kind"] != new["kind"]:
        return None
    if old["theme_id"] != new["theme_id"] or old["emotion"] != new["emotion"]:
        return None
    if old["role"] == music_cue_writer.ROLE_HIT:
        if match_score(old["parent"], new["parent"]) is None:
            return None
        gap = abs(float(old["at_s"]) - float(new["at_s"]))
        return 1.0 - gap / (2 * MOMENT_TOLERANCE_S) if gap <= MOMENT_TOLERANCE_S else None
    if old["at_s"] is not None and new["at_s"] is not None:
        gap = abs(float(old["at_s"]) - float(new["at_s"]))
        return 1.0 - gap / (2 * MOMENT_TOLERANCE_S) if gap <= MOMENT_TOLERANCE_S else None
    if old["start_s"] is None or new["start_s"] is None:
        return None
    old_start, old_end = float(old["start_s"]), float(old["end_s"])
    new_start, new_end = float(new["start_s"]), float(new["end_s"])
    longest = max(old_end - old_start, new_end - new_start)
    if longest <= 0:
        return None
    overlap = max(0.0, min(old_end, new_end) - max(old_start, new_start))
    ratio = overlap / longest
    if ratio < MIN_OVERLAP:
        return None
    if (
        new_span_s is not None
        and old_audio_s is not None
        and new_span_s > old_audio_s + LENGTH_TOLERANCE_S
    ):
        return None
    return ratio


def check_take(
    measurement: dict[str, Any], *, requested_s: float, kind: str, end_style: str | None
) -> dict[str, Any]:
    """Whether a take passes the technical check (§4.8), from its MUSIC-003 measurement. Pure.

    A score or an ambience bed must be at least 90% of the length asked for, start within 1 s of
    silence, not clip, have no silence of more than 3 s inside it (these are the theme check's)
    and end within 3 s of silence; where the plan asked for a musical ending it must end with a
    decay. A point sound or a hit is short and may hold silence, so only its length and clipping
    are checked. Returns `{passed, problems, facts}`; `facts` are the numbers the panel and the
    rewrite of a rejected prompt show.
    """
    loudness = measurement.get("loudness")
    loudness = loudness if isinstance(loudness, dict) else {}
    loudest = measurement.get("loudest_moment")
    ending = measurement.get("ending")
    ending = ending if isinstance(ending, dict) else {}
    duration = float(measurement.get("duration_s") or 0.0)
    trailing = float(measurement.get("trailing_silence_s") or 0.0)
    facts = {
        "duration_s": round(duration, 2),
        "leading_silence_s": round(float(measurement.get("leading_silence_s") or 0.0), 2),
        "trailing_silence_s": round(trailing, 2),
        "integrated_lufs": loudness.get("integrated_lufs"),
        "true_peak_dbtp": loudness.get("true_peak_dbtp"),
        "loudest_moment_s": loudest.get("time_s") if isinstance(loudest, dict) else None,
        "ending_kind": ending.get("kind"),
    }
    if kind in (plan_writer.KIND_SCORE, plan_writer.KIND_BED):
        problems = list(
            music_themes.check_recording(measurement, requested_s=requested_s)["problems"]
        )
        if trailing > MAX_TRAILING_SILENCE_S:
            problems.append(f"It ends with {trailing:.1f} s of silence.")
        if end_style == "musical_ending" and ending.get("kind") != "decay":
            problems.append(
                "The plan asks for a musical ending, but the take is cut off at its end."
            )
    else:
        problems = []
        if duration < requested_s * music_themes.MIN_LENGTH_FRACTION:
            problems.append(f"It is {duration:.1f} s long, and {requested_s:g} s were asked for.")
        if loudness.get("clipping"):
            problems.append("It clips (the sound reaches full scale).")
    return {"passed": not problems, "problems": problems, "facts": facts}


def _failed_check(message: str) -> dict[str, Any]:
    return {"passed": False, "problems": [message], "facts": None}


def blocking_selection(
    rows: list[MusicTake],
    *,
    sha: str,
    round_start: datetime | None,
    exclude_id: int | None = None,
) -> MusicTake | None:
    """The take that stops a new take of an item from being selected or retried: a locked one,
    or one that is selected, not rejected and made for the same detail (after `round_start`,
    the moment the take it replaces was rejected, when there is one). The same rule as the SQL
    of `_claim`.
    """
    for row in rows:
        if row.id == exclude_id or row.rejected_at is not None or row.selected_at is None:
            continue
        if row.locked_at is not None:
            return row
        if row.detail_sha256 == sha and (round_start is None or row.selected_at >= round_start):
            return row
    return None


# --- Reading the state ---------------------------------------------------------------------


@dataclass(frozen=True)
class TakeView:
    row: MusicTake
    run: music_lab.RunRow | None
    # A locked take of an earlier plan version that matches this item.
    inherited: bool
    # Made for the detail the cue has now.
    current: bool
    selected: bool = False

    @property
    def usable(self) -> bool:
        return self.run is not None and self.run.run.path is not None

    @property
    def status(self) -> TakeStatus:
        if self.usable:
            check = self.row.check_result
            if not isinstance(check, dict):
                return "checking"
            return "passed" if check.get("passed") else "check_failed"
        job = self.run.job if self.run is not None else None
        if job is not None and job.status in store.ACTIVE_STATUSES:
            return "generating"
        return "failed"

    @property
    def active(self) -> bool:
        return self.status in ("generating", "checking")

    @property
    def problems(self) -> list[str]:
        check = self.row.check_result
        if isinstance(check, dict) and isinstance(check.get("problems"), list):
            return [str(problem) for problem in check["problems"]]
        job = self.run.job if self.run is not None else None
        if self.status == "failed":
            return [(job.error if job is not None and job.error else "The take was not made.")]
        return []


@dataclass(frozen=True)
class ItemView:
    """One thing to generate (a cue, or one of its hits) and where its takes stand."""

    cue_view: music_cues.CueView
    item: dict[str, Any]
    takes: list[TakeView]
    # The take that is used: the newest selected one that is not rejected, or a locked take
    # carried over from an earlier plan version.
    selection: TakeView | None
    locked: bool
    # Why the selection is out of date, in plain words.
    reasons: list[str]
    needs_confirmation: bool
    # Why nothing can be made now, or None.
    blocked_reason: str | None
    round: int
    retries_used: int
    rewrite_job: Job | None
    active: bool
    pending_retry: bool
    done: bool
    # What a run starts next: `generate`, `regenerate` (the cue's detail changed), `retry`, or
    # None.
    action: str | None
    # Why it got nowhere (no take passed its check, a rewrite failed), or None.
    last_error: str | None

    @property
    def item_id(self) -> str:
        return str(self.item["id"])

    @property
    def out_of_date(self) -> bool:
        return bool(self.reasons)


@dataclass(frozen=True)
class MusicTakesState:
    """What the story workspace shows."""

    plan: MusicPlan | None
    items: list[ItemView]
    blocked_reason: str | None
    music_enabled: bool
    max_retries: int
    wordings: int


def _selection(takes: list[TakeView]) -> TakeView | None:
    chosen = [t for t in takes if t.row.selected_at is not None and t.row.rejected_at is None]
    if not chosen:
        return None
    return max(chosen, key=lambda t: (t.row.selected_at, t.row.id))  # type: ignore[arg-type,return-value]


def _round_start(row: MusicTake, rows_by_id: dict[int, MusicTake]) -> datetime | None:
    """When the take this one replaces was rejected, for a take made after a rejection."""
    feedback = row.feedback if isinstance(row.feedback, dict) else None
    if feedback is None:
        return None
    rejected = rows_by_id.get(feedback.get("of_take_id"))  # type: ignore[arg-type]
    return rejected.rejected_at if rejected is not None else None


async def _rewrite_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest `rewrite_music_prompt` job of each item, by `plan_id/item_id`."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.asc())
        .execution_options(populate_existing=True)
    )
    found: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        key = job.input.get("item_key") if isinstance(job.input, dict) else None
        if isinstance(key, str):
            found[key] = job
    return found


def _item_key(plan_id: int, item_id: str) -> str:
    return f"{plan_id}/{item_id}"


def _new_span(cue_view: music_cues.CueView, item: dict[str, Any]) -> float | None:
    if item["role"] == music_cue_writer.ROLE_HIT:
        return None
    assert cue_view.row is not None
    span = cue_view.row.detail.get("span_s")
    return float(span) if isinstance(span, int | float) else None


def _match_inherited(
    entries: list[tuple[music_cues.CueView, dict[str, Any]]],
    own_keys: set[str],
    old_locked: list[MusicTake],
    runs: dict[int, music_lab.RunRow],
) -> dict[str, MusicTake]:
    """Which locked take of an earlier plan version belongs to which item of the newest plan.
    Only an item with no takes of its own takes one. Each lock matches at most one item, the
    one it matches best (a later plan's lock before an earlier one's on a tie).
    """
    pairs: list[tuple[float, int, int, str, MusicTake]] = []
    for take in old_locked:
        run = runs.get(take.lab_run_id) if take.lab_run_id is not None else None
        audio = run.run.duration_s if run is not None else None
        for view, item in entries:
            key = str(item["id"])
            if key in own_keys or view.row is None:
                continue
            new = snapshot_of(view.cue, view.row.detail, item)
            score = match_score(
                take.cue_snapshot, new, new_span_s=_new_span(view, item), old_audio_s=audio
            )
            if score is not None:
                pairs.append((score, take.plan_id, take.id, key, take))
    pairs.sort(key=lambda p: (-p[0], -p[1], p[2]))
    matched: dict[str, MusicTake] = {}
    used: set[int] = set()
    for _score, _plan, _id, key, take in pairs:
        if key in matched or take.id in used:
            continue
        matched[key] = take
        used.add(take.id)
    return matched


def _build_item(
    *,
    plan_id: int,
    view: music_cues.CueView,
    item: dict[str, Any],
    rows: list[MusicTake],
    inherited: MusicTake | None,
    runs: dict[int, music_lab.RunRow],
    rewrite_job: Job | None,
    max_retries: int,
    global_block: str | None,
) -> ItemView:
    assert view.row is not None
    sha = detail_sha(view.row.detail)
    rows_by_id = {row.id: row for row in rows}

    def run_of(row: MusicTake) -> music_lab.RunRow | None:
        return runs.get(row.lab_run_id) if row.lab_run_id is not None else None

    takes = [
        TakeView(row, run_of(row), inherited=False, current=row.detail_sha256 == sha)
        for row in rows
    ]
    selection = _selection(takes)
    locked = any(t.row.locked_at is not None and t.row.rejected_at is None for t in takes)
    if not takes and inherited is not None:
        selection = TakeView(inherited, run_of(inherited), inherited=True, current=True)
        locked = True
    if selection is not None:
        takes = [
            TakeView(t.row, t.run, t.inherited, t.current, selected=t.row.id == selection.row.id)
            for t in takes
        ]
        if selection.inherited:
            selection = TakeView(selection.row, selection.run, True, True, selected=True)
        else:
            chosen_id = selection.row.id
            selection = next(t for t in takes if t.row.id == chosen_id)

    reasons: list[str] = []
    if selection is not None and not selection.inherited:
        if not selection.current:
            reasons.append("The cue was detailed again after this take was made.")
        reasons.extend(view.reasons)
    done = selection is not None and (locked or not reasons)
    needs_confirmation = bool(
        selection is not None
        and not locked
        and not done
        and selection.row.selected_by == SELECTED_OWNER
    )

    current_takes = [t for t in takes if t.current and not t.inherited]
    round_no = max((t.row.round for t in current_takes), default=0)
    in_round = [t for t in current_takes if t.row.round == round_no]
    retried = {t.row.retry_of_id for t in current_takes if t.row.retry_of_id is not None}
    retries_used = sum(1 for t in in_round if t.row.retry_of_id is not None)
    failed = [
        t
        for t in in_round
        if t.status in ("failed", "check_failed")
        and t.row.rejected_at is None
        and t.row.id not in retried
    ]
    start_of_round = (
        _round_start(in_round[0].row, rows_by_id)
        if in_round and in_round[0].row.feedback is not None
        else None
    )
    blocked_by_selection = blocking_selection(rows, sha=sha, round_start=start_of_round)

    rewrite_active = rewrite_job is not None and rewrite_job.status in store.ACTIVE_STATUSES
    active = rewrite_active or any(t.active for t in takes)
    pending_retry = (
        not locked
        and blocked_by_selection is None
        and not active
        and retries_used < max_retries
        and bool(failed)
        and not inherited
    )

    action: str | None = None
    if not locked and not done and not active:
        if pending_retry:
            action = "retry"
        elif not takes:
            action = "generate"
        elif not current_takes:
            action = "regenerate"

    block: str | None = None
    if action is not None:
        if global_block is not None:
            block = global_block
        elif view.blocked_reason is not None:
            block = view.blocked_reason
        elif not view.done:
            block = (
                "The cue is being detailed."
                if view.active
                else "Detail the cue first: its detail is missing or out of date."
            )

    if selection is not None and not done and not active and not locked and action is None:
        block = "The cue is out of date: detail it again first."

    last_error: str | None = None
    dead_end = (
        bool(current_takes)
        and selection is None
        and not done
        and not active
        and not locked
        and action is None
    )
    if dead_end:
        rejected_without_new = [
            t
            for t in in_round
            if t.row.rejected_at is not None
            and not any(
                isinstance(o.row.feedback, dict) and o.row.feedback.get("of_take_id") == t.row.id
                for o in takes
            )
        ]
        if (
            rewrite_job is not None
            and rewrite_job.status in ("failed", "cancelled")
            and (rejected_without_new)
        ):
            last_error = (
                f"The prompt could not be rewritten: {rewrite_job.error or 'the job failed'}. "
                "Make the music again to start a new round."
            )
        else:
            problems = next((t.problems for t in reversed(failed) if t.problems), [])
            last_error = "No take passed its check" + (
                f": {' '.join(problems)}" if problems else "."
            )

    return ItemView(
        cue_view=view,
        item=item,
        takes=takes,
        selection=selection,
        locked=locked,
        reasons=reasons,
        needs_confirmation=needs_confirmation,
        blocked_reason=block,
        round=round_no,
        retries_used=retries_used,
        rewrite_job=rewrite_job,
        active=active,
        pending_retry=pending_retry,
        done=bool(done),
        action=action,
        last_error=last_error,
    )


@memoized_state
async def state(session: AsyncSession, project: Project) -> MusicTakesState:
    """The project's takes with where they stand. Worked out on every read."""
    cues = await music_cues.state(session, project)
    max_retries = await settings_service.get_int(
        session, settings_service.MUSIC_TAKE_MAX_RETRIES_KEY
    )
    plan = cues.plan
    if plan is None or not project.music_enabled:
        return MusicTakesState(
            None, [], cues.blocked_reason, project.music_enabled, max_retries, cues.wordings
        )

    statement = (
        select(MusicTake)
        .where(MusicTake.project_id == project.id)
        .order_by(MusicTake.id.asc())
        .execution_options(populate_existing=True)
    )
    all_rows = list((await session.execute(statement)).scalars())
    own = [row for row in all_rows if row.plan_id == plan.id]
    old_locked = [
        row
        for row in all_rows
        if row.plan_id != plan.id and row.locked_at is not None and row.rejected_at is None
    ]
    run_ids = {row.lab_run_id for row in all_rows if row.lab_run_id is not None}
    runs = await music_lab.get_runs(session, run_ids)
    rewrite_jobs = await _rewrite_jobs(session, project.id)

    entries: list[tuple[music_cues.CueView, dict[str, Any]]] = []
    for view in cues.cues:
        if view.makes_audio and view.row is not None and view.row.items:
            entries.extend((view, item) for item in view.row.items)

    by_item: dict[str, list[MusicTake]] = defaultdict(list)
    for row in own:
        by_item[row.item_id].append(row)
    inherited = _match_inherited(entries, set(by_item), old_locked, runs)

    views = [
        _build_item(
            plan_id=plan.id,
            view=view,
            item=item,
            rows=by_item.get(str(item["id"]), []),
            inherited=inherited.get(str(item["id"])),
            runs=runs,
            rewrite_job=rewrite_jobs.get(_item_key(plan.id, str(item["id"]))),
            max_retries=max_retries,
            global_block=cues.blocked_reason,
        )
        for view, item in entries
    ]
    return MusicTakesState(plan, views, cues.blocked_reason, True, max_retries, cues.wordings)


def find_item(current: MusicTakesState, take_id: int) -> tuple[ItemView, TakeView] | None:
    """The item and the take view of a take, among the newest plan's items (a locked take that
    an item inherited counts).
    """
    for item in current.items:
        for take in item.takes:
            if take.row.id == take_id:
                return item, take
        if item.selection is not None and item.selection.inherited:
            if item.selection.row.id == take_id:
                return item, item.selection
    return None


# --- Starting takes ------------------------------------------------------------------------


def _seed() -> int:
    return secrets.randbelow(music_models.SEED_MAX + 1)


async def _partition(session: AsyncSession, model: music_models.MusicModel) -> str:
    try:
        return await music_lab.generation_partition(session, model)
    except music_lab.MusicLabInputError as exc:
        raise MusicTakeError(str(exc)) from exc


async def _add_take(
    session: AsyncSession,
    *,
    project: Project,
    plan_id: int,
    view: music_cues.CueView,
    item: dict[str, Any],
    fields: dict[str, Any],
    wording: int | None,
    round_no: int,
    retry_of_id: int | None,
    feedback: dict[str, Any] | None,
    partition: str,
    seed: int | None = None,
) -> tuple[MusicTake, int | None]:
    """Adds one take and its Music lab run and GPU job, and flushes. Returns the take and the
    id of the GPU job. Does not commit.
    """
    assert view.row is not None
    model: music_models.MusicModel = item["model"]
    seed = _seed() if seed is None else seed
    description = f"Take of '{item['id']}': {item.get('description') or view.cue['summary']}"
    try:
        brief = music_lab.clean_brief(
            LAB_KIND[item["kind"]], {"description": description[:BRIEF_MAX_CHARS]}
        )
    except music_lab.MusicLabInputError as exc:
        raise MusicTakeError(str(exc)) from exc
    body = music_generator.build_body(model, fields, seed=seed, partition=partition)
    made = await music_lab.add_run(
        session,
        model=model,
        kind=LAB_KIND[item["kind"]],
        brief=brief,
        fields=fields,
        seed=seed,
        body=body,
        group_key=f"cue:{plan_id}/{item['id']}",
        project_id=project.id,
    )
    take = MusicTake(
        project_id=project.id,
        plan_id=plan_id,
        cue_id=str(item["cue_id"]),
        item_id=str(item["id"]),
        cue_row_id=view.row.id,
        detail_sha256=detail_sha(view.row.detail),
        round=round_no,
        wording=wording,
        retry_of_id=retry_of_id,
        lab_run_id=made.run.id,
        seed=seed,
        fields=fields,
        requested_s=float(fields.get("duration") or item.get("requested_s") or 0.0),
        cue_snapshot=snapshot_of(view.cue, view.row.detail, item),
        feedback=feedback,
    )
    session.add(take)
    await session.flush()
    return take, made.job.id if made.job is not None else None


async def _start_view(
    session: AsyncSession, project: Project, current: MusicTakesState, view: ItemView, mode: str
) -> list[int]:
    """Adds the takes `mode` asks for on one item, and flushes. Returns the GPU job ids.

    `round`: a new round with a take for every wording of the cue's detail (the first takes,
    after the detail changed, or when the owner asks for more). `retry`: another take, with the
    same fields and a new seed, for each failed take of the round that has none yet, up to the
    setting. Does not commit.
    """
    assert current.plan is not None
    item = view.item
    partition = await _partition(session, item["model"])
    job_ids: list[int] = []
    if mode == "retry":
        current_takes = [t for t in view.takes if t.current and t.row.round == view.round]
        retried = {t.row.retry_of_id for t in current_takes}
        budget = current.max_retries - view.retries_used
        for take in current_takes:
            if budget <= 0:
                break
            if (
                take.status not in ("failed", "check_failed")
                or take.row.rejected_at is not None
                or take.row.id in retried
            ):
                continue
            made, job_id = await _add_take(
                session,
                project=project,
                plan_id=current.plan.id,
                view=view.cue_view,
                item=item,
                fields=take.row.fields,
                wording=take.row.wording,
                round_no=take.row.round,
                retry_of_id=take.row.id,
                feedback=take.row.feedback,
                partition=partition,
            )
            budget -= 1
            if job_id is not None:
                job_ids.append(job_id)
        return job_ids

    round_no = max((t.row.round for t in view.takes), default=0) + 1
    for number, wording in enumerate(item["wordings"], start=1):
        _made, job_id = await _add_take(
            session,
            project=project,
            plan_id=current.plan.id,
            view=view.cue_view,
            item=item,
            fields=wording["fields"],
            wording=number,
            round_no=round_no,
            retry_of_id=None,
            feedback=None,
            partition=partition,
        )
        if job_id is not None:
            job_ids.append(job_id)
    return job_ids


async def start_run(
    session: AsyncSession,
    project: Project,
    *,
    item_id: str | None = None,
    confirm_replace_owner: bool = False,
) -> tuple[int, ...]:
    """Makes the takes that are missing: for every item that needs them, or for the one
    `item_id`. Commits. Returns the ids of the GPU jobs it queued (none when everything is done
    or already being made). Raises MusicTakeError.

    Without `item_id` only items that have no takes, whose takes are for an older detail of the
    cue, or that have a failed take to retry are started. With one, an item that is done gets a
    new round too (more takes to choose from, none of which replaces the selection), unless it
    is locked. A new round over an out-of-date take the owner selected needs
    `confirm_replace_owner`.
    """
    await settle(project.id)
    current = await state(session, project)
    if not current.music_enabled:
        raise MusicTakeError(MUSIC_OFF_MESSAGE)
    if current.plan is None or current.blocked_reason is not None:
        raise MusicTakeError(current.blocked_reason or music_cues.NO_PLAN_MESSAGE)

    todo: list[tuple[ItemView, str]] = []
    if item_id is not None:
        view = next((v for v in current.items if v.item_id == item_id), None)
        if view is None:
            raise MusicTakeError(f"The music plan has no item '{item_id}' to make.")
        if view.locked:
            raise MusicTakeError(LOCKED_MESSAGE)
        if view.active:
            return ()
        if view.cue_view.blocked_reason is not None:
            raise MusicTakeError(view.cue_view.blocked_reason)
        if not view.cue_view.done:
            raise MusicTakeError("Detail the cue first: its detail is missing or out of date.")
        todo.append((view, "retry" if view.pending_retry else "round"))
    else:
        for view in current.items:
            if view.action is None or view.blocked_reason is not None:
                continue
            todo.append((view, "retry" if view.action == "retry" else "round"))

    if any(v.needs_confirmation and mode == "round" for v, mode in todo) and not (
        confirm_replace_owner
    ):
        raise MusicTakeError(REPLACE_MESSAGE)

    job_ids: list[int] = []
    for view, mode in todo:
        job_ids.extend(await _start_view(session, project, current, view, mode))
    await session.commit()
    return tuple(job_ids)


# --- When a take's audio is stored ---------------------------------------------------------


async def _check_run(session: AsyncSession, run: LabMusicRun, take: MusicTake) -> dict[str, Any]:
    if run.path is None or run.sha256 is None:
        return _failed_check("The run made no recording.")
    try:
        path = get_storage().get_path(run.path)
        measurement = await audio_measurements.measure(session, path, run.sha256)
    except (StorageError, audio_measurements.MeasurementError) as exc:
        return _failed_check(str(exc))
    snapshot = take.cue_snapshot if isinstance(take.cue_snapshot, dict) else {}
    return check_take(
        measurement,
        requested_s=take.requested_s,
        kind=str(snapshot.get("kind") or plan_writer.KIND_SCORE),
        end_style=snapshot.get("end_style"),
    )


async def _newest_plan_id(session: AsyncSession, project_id: int) -> int | None:
    statement = (
        select(MusicPlan.id)
        .where(MusicPlan.project_id == project_id)
        .order_by(MusicPlan.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def _claim(session: AsyncSession, take: MusicTake, round_start: datetime | None) -> bool:
    """Selects the take for an automatic run, only while nothing blocks it: no locked take of
    the item, and no take of the item that is selected, not rejected and made for the same
    detail (after `round_start`, for a take made after a rejection). One `UPDATE`, so two takes
    stored at the same moment cannot both win and an owner's choice is never replaced.
    """
    other = aliased(MusicTake)
    same_version = other.detail_sha256 == take.detail_sha256
    if round_start is not None:
        same_version = and_(same_version, other.selected_at >= round_start)
    blocking = (
        select(other.id)
        .where(
            other.plan_id == take.plan_id,
            other.item_id == take.item_id,
            other.id != take.id,
            other.rejected_at.is_(None),
            other.selected_at.is_not(None),
            or_(same_version, other.locked_at.is_not(None)),
        )
        .exists()
    )
    statement = (
        update(MusicTake)
        .where(
            MusicTake.id == take.id,
            MusicTake.selected_at.is_(None),
            MusicTake.rejected_at.is_(None),
            ~blocking,
        )
        .values(selected_at=utcnow(), selected_by=SELECTED_AUTO)
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], await session.execute(statement))
    await session.commit()
    return result.rowcount == 1


async def _claim_take(take_id: int) -> bool:
    async with SessionLocal() as session:
        take = await session.get(MusicTake, take_id)
        if take is None or take.rejected_at is not None or take.selected_at is not None:
            await session.commit()
            return False
        feedback = take.feedback if isinstance(take.feedback, dict) else None
        if feedback is not None and not feedback.get("claim", True):
            await session.commit()
            return False  # the owner rejected a take that was not the selected one
        item_id = take.item_id
        if await _newest_plan_id(session, take.project_id) != take.plan_id:
            await session.commit()
            return False  # a later plan has replaced this one
        round_start: datetime | None = None
        if feedback is not None:
            rejected = await session.get(MusicTake, feedback.get("of_take_id"))
            round_start = rejected.rejected_at if rejected is not None else None
        claimed = await _claim(session, take, round_start)
    if claimed:
        _logger.info("music take %d of %s selected", take_id, item_id)
    return claimed


async def _retry(take_id: int) -> bool:
    """Makes a failed take again when the item still has nothing selected and the round has
    retries left. True when it queued a job.
    """
    async with _retry_lock, SessionLocal() as session:
        take = await session.get(MusicTake, take_id)
        if take is None or take.rejected_at is not None or take.selected_at is not None:
            await session.commit()
            return False
        project = await session.get(Project, take.project_id)
        if project is None or not project.music_enabled:
            await session.commit()
            return False
        try:
            current = await state(session, project)
            if current.plan is None or current.plan.id != take.plan_id:
                await session.commit()
                return False
            view = next((v for v in current.items if v.item_id == take.item_id), None)
            if view is None or view.action != "retry" or view.blocked_reason is not None:
                await session.commit()
                return False
            job_ids = await _start_view(session, project, current, view, "retry")
            await session.commit()
        except MusicTakeError:
            await session.rollback()
            _logger.exception("music take %d: the retry could not be started", take_id)
            return False
    return bool(job_ids)


async def on_audio_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_music` job has stored its audio. When the run is a take,
    measures it and stores the check. A take that passed is selected when nothing blocks it
    (D-5, MD-10); one that failed is made again while the item has nothing selected and the
    round has retries left. Returns True when it queued jobs. Does nothing (False) for a run
    that is no take.
    """
    async with SessionLocal() as session:
        take = (
            (await session.execute(select(MusicTake).where(MusicTake.lab_run_id == run_id)))
            .scalars()
            .first()
        )
        run = await session.get(LabMusicRun, run_id)
        if take is None or run is None:
            await session.commit()
            return False
        if take.check_result is None:
            take.check_result = await _check_run(session, run, take)
        passed = bool(take.check_result.get("passed"))
        take_id = take.id
        await session.commit()
    if passed:
        await _claim_take(take_id)
        return False
    return await _retry(take_id)


async def settle(project_id: int) -> bool:
    """Checks the takes whose audio is stored but that have no check (the hook of
    `on_audio_stored` failed or the app stopped in between), so that they can be selected or
    retried. Cheap when there is nothing to do. Returns True when it queued jobs.
    """
    async with SessionLocal() as session:
        statement = (
            select(MusicTake.lab_run_id)
            .join(LabMusicRun, LabMusicRun.id == MusicTake.lab_run_id)
            .where(
                MusicTake.project_id == project_id,
                MusicTake.check_result.is_(None),
                LabMusicRun.path.is_not(None),
            )
        )
        run_ids = [run_id for run_id in (await session.execute(statement)).scalars() if run_id]
        await session.commit()
    queued = False
    for run_id in run_ids:
        try:
            queued = await on_audio_stored(run_id) or queued
        except Exception:
            _logger.exception("music take of run %d could not be settled", run_id)
    return queued


# --- The owner's actions -------------------------------------------------------------------


async def _find(
    session: AsyncSession, project: Project, take_id: int
) -> tuple[MusicTakesState, ItemView, TakeView]:
    await settle(project.id)
    current = await state(session, project)
    found = find_item(current, take_id)
    if found is None:
        raise MusicTakeError("That is not a take of the newest music plan.")
    return current, found[0], found[1]


async def select_take(session: AsyncSession, project: Project, take_id: int) -> None:
    """The owner selects a take: any take with audio made for the cue's current detail, even
    one that failed its check. Stops the item's automatic retries. Commits. Raises
    MusicTakeError.
    """
    _current, item, take = await _find(session, project, take_id)
    if take.inherited or item.locked:
        raise MusicTakeError(LOCKED_MESSAGE)
    if take.row.rejected_at is not None:
        raise MusicTakeError("That take was rejected.")
    if not take.usable:
        raise MusicTakeError("That take has no recording yet.")
    if not take.current:
        raise MusicTakeError("That take was made for an older version of the cue.")
    row = await session.get(MusicTake, take_id)
    assert row is not None
    row.selected_at = utcnow()
    row.selected_by = SELECTED_OWNER
    await session.commit()


async def reject(session: AsyncSession, project: Project, take_id: int, note: str) -> int:
    """The owner rejects a take with a note. The model rewrites the cue's prompt from the note
    (`rewrite_music_prompt`), and a new take is made from it (MD-23). Commits. Returns the id of
    the job. A take whose rewrite failed can be rejected again to ask again. Raises
    MusicTakeError.
    """
    text = (note or "").strip()
    if not text:
        raise MusicTakeError("Say what is wrong with the take: the note is what the model reads.")
    if len(text) > NOTE_MAX_CHARS:
        raise MusicTakeError(f"The note must be at most {NOTE_MAX_CHARS:,} characters.")
    current, item, take = await _find(session, project, take_id)
    if take.inherited or item.locked:
        raise MusicTakeError(LOCKED_MESSAGE)
    if item.rewrite_job is not None and item.rewrite_job.status in store.ACTIVE_STATUSES:
        raise MusicTakeError(BUSY_MESSAGE)
    if not take.usable:
        raise MusicTakeError("That take has no recording yet, so there is nothing to reject.")
    if not take.current:
        raise MusicTakeError("That take was made for an older version of the cue.")
    already_answered = any(
        isinstance(other.row.feedback, dict) and other.row.feedback.get("of_take_id") == take_id
        for other in item.takes
    )
    if take.row.rejected_at is not None and already_answered:
        raise MusicTakeError("That take was already rejected and a new take was made from it.")
    cue_view = item.cue_view
    if not cue_view.done:
        raise MusicTakeError("Detail the cue first: its detail is missing or out of date.")
    if current.plan is None or cue_view.row is None:
        raise MusicTakeError(music_cues.NO_PLAN_MESSAGE)
    bible = await music_bible.latest(session, project.id)
    if bible is None:
        raise MusicTakeError("Write the Music Bible first.")
    partition = await _partition(session, item.item["model"])

    row = await session.get(MusicTake, take_id)
    assert row is not None
    was_selected = item.selection is not None and item.selection.row.id == take_id
    previous, following, joins = music_cue_writer.lane_neighbours(
        current.plan.content, cue_view.cue
    )
    is_hit = item.item["role"] == music_cue_writer.ROLE_HIT
    item_key = _item_key(current.plan.id, item.item_id)
    row.rejected_at = utcnow()
    row.reject_note = text
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "item_key": item_key,
            "take_id": take_id,
            "plan_id": current.plan.id,
            "cue_id": item.item["cue_id"],
            "item_id": item.item_id,
            "cue_row_id": cue_view.row.id,
            "detail_sha256": row.detail_sha256,
            "round": row.round + 1,
            "claim": was_selected,
            "bible": bible.content,
            "cue": cue_view.cue,
            "detail": cue_view.row.detail,
            "item": {**item.item, "wordings": []},
            "previous": None if is_hit else music_cue_writer.neighbour_view(previous, None),
            "following": None if is_hit else music_cue_writer.neighbour_view(following, None),
            "joins": [] if is_hit else joins,
            "rejected_fields": row.fields,
            "facts": music_cue_writer.facts_text(row.check_result),
            "note": text,
            "avoid": music_cues.avoid_list(bible.content),
            "partition": partition,
            "seed": _seed(),
        },
        commit=False,
        dedupe_key="item_key",
    )
    if not created:
        await session.rollback()
        raise MusicTakeError(BUSY_MESSAGE)
    await session.commit()
    return job.id


async def save_feedback_take(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    task_take_id: int,
    plan_id: int,
    cue_id: str,
    item_id: str,
    cue_row_id: int | None,
    sha: str,
    round_no: int,
    claim: bool,
    item: dict[str, Any],
    cue: dict[str, Any],
    detail: dict[str, Any],
    fields: dict[str, Any],
    seed: int,
    partition: str,
) -> MusicTake:
    """Adds the take made from a rewritten prompt, with its run and GPU job. Flushes but does not
    commit: the job commits it together with finishing itself, so a job is never "succeeded"
    without its result. Raises MusicTakeError when the plan or the cue's detail has changed in
    the meantime (the wording was written for the old one).
    """
    if await _newest_plan_id(session, project_id) != plan_id:
        raise MusicTakeError("The music plan was replaced while the prompt was being rewritten.")
    rejected = await session.get(MusicTake, task_take_id)
    if rejected is None:
        raise MusicTakeError("The rejected take is gone.")
    project = await session.get(Project, project_id)
    assert project is not None
    row = (
        (
            await session.execute(
                select(MusicCue)
                .where(MusicCue.plan_id == plan_id, MusicCue.cue_id == cue_id)
                .order_by(MusicCue.version.desc())
                .limit(1)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .first()
    )
    if row is None or detail_sha(row.detail) != sha:
        raise MusicTakeError("The cue was detailed again while the prompt was being rewritten.")
    view = music_cues.CueView(
        cue=cue,
        makes_audio=True,
        row=row,
        job=None,
        reasons=[],
        blocked_reason=None,
        done=True,
        active=False,
    )
    take, _job_id = await _add_take(
        session,
        project=project,
        plan_id=plan_id,
        view=view,
        item=item,
        fields=fields,
        wording=None,
        round_no=round_no,
        retry_of_id=None,
        feedback={
            "of_take_id": task_take_id,
            "note": rejected.reject_note,
            "job_id": job_id,
            "claim": claim,
        },
        partition=partition,
        seed=seed,
    )
    assert item_id == take.item_id
    return take


async def lock(session: AsyncSession, project: Project, take_id: int) -> None:
    """Locks the selected take of an item: it is never regenerated, and stays selected when the
    plan changes while its cue still exists. Commits. Raises MusicTakeError.
    """
    _current, item, take = await _find(session, project, take_id)
    if take.row.rejected_at is not None or not take.selected:
        raise MusicTakeError("Only the selected take of a cue can be locked. Select it first.")
    if take.row.locked_at is not None:
        return
    if not take.usable:
        raise MusicTakeError("That take has no recording yet.")
    row = await session.get(MusicTake, take_id)
    assert row is not None
    row.locked_at = utcnow()
    await session.commit()
    _logger.info("music take %d of %s locked", take_id, item.item_id)


async def unlock(session: AsyncSession, project: Project, take_id: int) -> None:
    """Removes the lock of a take (also one an item carried over from an earlier plan). Commits.
    Raises MusicTakeError.
    """
    _current, _item, take = await _find(session, project, take_id)
    if take.row.locked_at is None:
        return
    row = await session.get(MusicTake, take_id)
    assert row is not None
    row.locked_at = None
    await session.commit()
