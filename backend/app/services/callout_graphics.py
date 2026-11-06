"""The graphics of the callouts of a motion explainer: the generated component of each callout, the
jobs that make it, and where each stands (CMO-003, `Callouts_motion_implementation_phases.md`
§4.5).

It follows `shot_graphics` for a callout. Each try at a callout's component is a row of
`callout_graphic` (an **attempt**) and nothing is replaced. An attempt is made in two steps:

1. A paid job (`write_callout_component`) asks the model for the code and saves it as the row's
   `input`, after the static and browser checks and the repairs those need.
2. A local job (`render_callout_preview`) has the motion service draw the code at its nominal zone
   on a grey backdrop (an H.264 file a browser plays), checks the file and stores it.

**The match key** (`match_key`) is a hash of the callout's unit, phrase, type and number of items
or sides. An attempt serves every callout of every plan version with the same key, so an edit of a
callout's words (which keeps the unit, the phrase and the shape) keeps its code.

**What an attempt is drawn from.** `resolve_callout` works out the resolved callout with code:
the parts (the texts, their roles and colours, and the frame each appears at on the estimated
script), the video's colours and fonts, the callout look, the length, and the zones it is drawn
and checked at. It is recorded on the row (`inputs.resolved`) with its hash, so an attempt is
**current** when its hash is the one worked out now. New words or a new graphics look change the
hash: the callout is then made again from the code it already has, with no model call. A new
callout look, a new shape, or **Ask again** is a new model call.

**When callout graphics can be made.** The project's `callout_style` is `motion` (a continuous
explainer with graphics and callouts on), its callout plan is current and not being written, and
its callout look exists, is current and is not being written.

**What a start does** (`start_callout` and `start_all`): nothing while a job of the component is
waiting or running, nothing when it has a current preview, nothing when it failed outright with
the current callout look; a new attempt with the code it already has when only the words or the
colours changed; the preview again when the code has none; otherwise a new model call.

**Repairs** work as for graphic shots (EXG-006): a **chain** starts at an attempt that is not a
repair and may spend at most the setting `graphics_component_repairs` repair asks. A failed check
is repaired inside the job that wrote the component. A failed preview is repaired by a **new
attempt** (`queue_repair`) with `repair_of` set. A chain that runs out leaves its newest attempt
`failed_outright`.

**The version a callout uses** (the rule, §4.5, with the component only): the newest current
component with a preview; when the component failed outright, a box (today's text box); otherwise
nothing yet. A callout is **done** when the rule gives a component or a box.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import CalloutGraphic, Job, Project
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import (
    callout_look,
    callout_plan,
    callout_plan_writer,
    callout_render,
    graphic_theme,
    graphics_lab,
    graphics_render,
    graphics_resolve,
)
from app.services.callout_plan_writer import ScriptUnit

COMPONENT: Final = "generated_component"
ENGINES: Final = (COMPONENT,)
ENGINE_LABELS: Final = {COMPONENT: "Generated component"}

WRITE_JOB_TYPES: Final = {COMPONENT: "write_callout_component"}
PREVIEW_JOB_TYPE: Final = "render_callout_preview"
# One write job of a kind per callout at a time; one preview job per attempt.
WRITE_DEDUPE_KEY: Final = "callout_graphic_key"
PREVIEW_DEDUPE_KEY: Final = "callout_graphic_id"

# The colour under a callout in its preview (CMO-001: a card, its shadow and its text read well).
BACKDROP: Final = "#808080"
# What the motion service draws at most for a callout (`CALLOUT_MAX_FRAMES`).
MAX_FRAMES: Final = 1800
# The smallest zone the motion service draws.
MIN_SIDE_PX: Final = 64

# What a version used by the video is: the component, or today's text box (§4.5).
USED_BOX: Final = "box"
USED_CHOSEN: Final = "chosen"
USED_DEFAULT: Final = "default"
USED_COMPONENT_FAILED: Final = "component_failed"

# Engine and callout statuses. `none`: nothing was made. `writing`: the model call is waiting or
# running. `rendering`: the preview is being drawn. `ready`: a current preview. `out_of_date`: a
# preview that is not current. `failed`: nothing usable and nothing running. (A callout adds
# `working`.)
Status = str

PLAN_MISSING_MESSAGE: Final = "Write the callout plan first: the graphics are made from it."
PLAN_BEING_WRITTEN_MESSAGE: Final = "The callout plan is being written."
PLAN_OUT_OF_DATE_MESSAGE: Final = "The callout plan is out of date. Run it again first."
LOOK_MISSING_MESSAGE: Final = "Write the callout look first: every callout uses it."
LOOK_BEING_WRITTEN_MESSAGE: Final = "The callout look is being written."
LOOK_OUT_OF_DATE_MESSAGE: Final = "The callout look is out of date. Write it again first."
THEME_MISSING_MESSAGE: Final = "Design the graphics look first: every callout uses its colours."
NO_UNIT_MESSAGE: Final = (
    "This callout's line is no longer in the script. Write the callout plan again."
)
BEING_MADE_MESSAGE: Final = "The graphics of this callout are already being made."
ENGINE_BUSY_MESSAGE: Final = "This version is already being made."
STOPPED_MESSAGE: Final = "It stopped before a preview was made."
NOT_FOUND_MESSAGE: Final = "There is no such callout in the callout plan."
OFF_CALLOUT_MESSAGE: Final = "This callout is turned off."

THEME_REASON: Final = "The graphics look was written again since this callout was drawn."
OTHER_REASON: Final = "The words, the timing or the size this callout was drawn for have changed."
LOOK_REASON: Final = "The callout look was written again since this callout was made."


class CalloutGraphicsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- The match key and the resolved callout --------------------------------------------------


def shape_of(callout: dict[str, Any]) -> int:
    """How many texts the callout shows beyond its type: its items or sides, else 1."""
    if callout["type"] == callout_plan_writer.TYPE_LIST:
        return len(callout["items"])
    if callout["type"] == callout_plan_writer.TYPE_COMPARISON:
        return len(callout["sides"])
    return 1


def _sha256(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def match_key(callout: dict[str, Any]) -> str:
    """The key that says which attempts serve a callout (§4.5): its unit, phrase, type and number
    of items or sides. The words are not in it.
    """
    return _sha256(
        {
            "scene_id": callout["scene_id"],
            "unit_id": callout["unit_id"],
            "phrase": callout["phrase"],
            "type": callout["type"],
            "count": shape_of(callout),
        }
    )


def resolved_sha256(resolved: dict[str, Any]) -> str:
    """A hash of a resolved callout: two attempts with the same hash are drawn from the same."""
    return _sha256(resolved)


@dataclass(frozen=True)
class _Piece:
    """One text of a callout and the phrase it is placed by."""

    text: str
    role: str
    phrase: str


def _pieces(callout: dict[str, Any]) -> list[_Piece]:
    kind = callout["type"]
    if kind == callout_plan_writer.TYPE_COMPARISON:
        return [_Piece(s["text"], s["role"], s["phrase"]) for s in callout["sides"]]
    if kind == callout_plan_writer.TYPE_LIST:
        return [_Piece(i["text"], callout["role"], i["phrase"]) for i in callout["items"]]
    return [_Piece(callout["text"], callout["role"], callout["phrase"])]


def _even(value: float) -> int:
    return max(MIN_SIDE_PX, round(value / 2) * 2)


def zones_of(kind: str, layout: str, width: int, height: int) -> list[dict[str, Any]]:
    """The zones a callout is checked at, the first being the preview's (§4.5). A title has its
    own; in portrait there is one; in landscape a callout can land beside the presenter or over
    B-roll, so both are checked.
    """
    if kind == callout_plan_writer.TYPE_SECTION_TITLE:
        choices = [("title", False)]
    elif layout == callout_render.LAYOUT_PORTRAIT:
        choices = [("portrait", False)]
    else:
        choices = [("presenter", True), ("broll", False)]
    zones: list[dict[str, Any]] = []
    for placement, on_presenter in choices:
        zone = callout_render.zone_box(kind, on_presenter, layout, width, height)
        zones.append(
            {
                "placement": placement,
                "width": _even(zone.width),
                "height": _even(zone.bottom - zone.top),
            }
        )
    return zones


def _frames_of(callout: dict[str, Any], unit: ScriptUnit, fps: int) -> tuple[int, int, list[int]]:
    """The nominal length of a callout, the frame its exit fade starts at, and the frame each part
    appears at, worked out like `callout_render._times` on the estimated script.
    """
    starts: list[float] = []
    for piece in _pieces(callout):
        span = callout_plan_writer.locate_phrase(unit.words, piece.phrase)
        share = span[0] / len(unit.words) if span is not None and unit.words else 0.0
        starts.append(unit.start_s + unit.seconds * share)
    if callout["type"] == callout_plan_writer.TYPE_LIST:
        # The items build up in the order they are written, never earlier than the one before.
        latest_start = starts[0]
        for index, start in enumerate(starts):
            latest_start = max(latest_start, start)
            starts[index] = latest_start
    first = min(starts)
    if callout["type"] == callout_plan_writer.TYPE_SECTION_TITLE:
        length_s = callout_render.SECTION_TITLE_MS / 1000
    else:
        length_s = max(callout_render.MIN_SHOW_MS / 1000, unit.start_s + unit.seconds - first)
    frames = max(1, min(round(length_s * fps), MAX_FRAMES))
    exit_frame = frames - round(callout_render.FADE_MS * fps / 1000)
    latest = max(0, exit_frame - round(callout_render.MIN_PART_MS * fps / 1000))
    return (
        frames,
        exit_frame,
        [max(0, min(round((start - first) * fps), latest)) for start in starts],
    )


def resolve_callout(
    *,
    callout: dict[str, Any],
    unit: ScriptUnit,
    theme_content: dict[str, Any],
    theme_version: int,
    look_content: dict[str, Any],
    look_version: int,
    width: int,
    height: int,
    fps: int,
) -> dict[str, Any]:
    """The resolved callout of one callout (§4.5). Pure. `theme_content` is the graphics look's
    `content["theme"]` and `look_content` the callout look's `content["look"]`. It is what the
    model is told, what the checks and the preview draw, and what an attempt records. Raises
    CalloutGraphicsError.
    """
    try:
        colours, _notes = graphics_resolve.theme_for(theme_content)
    except (KeyError, ValueError) as exc:
        raise CalloutGraphicsError(f"The graphics look cannot be read: {exc}") from exc
    theme = {
        key: colours[key]
        for key in ("surface", "text", "muted", "accent", "positive", "negative", "number")
    }
    role_colours = {
        callout_render.ROLE_ACCENT: colours["accent"],
        "number": colours["number"],
        "negative": colours["negative"],
        "positive": colours["positive"],
    }
    pieces = _pieces(callout)
    frames, exit_frame, part_frames = _frames_of(callout, unit, fps)
    layout = callout_render.style_for(width, height).layout
    return {
        "kind": callout["type"],
        "frame_height": height,
        "fps": fps,
        "frames": frames,
        "exit_frame": exit_frame,
        "parts": [
            {
                "id": f"p{number}",
                "text": piece.text,
                "role": piece.role,
                "colour": role_colours.get(piece.role, colours["accent"]),
                "frame": frame,
            }
            for number, (piece, frame) in enumerate(zip(pieces, part_frames, strict=True), start=1)
        ],
        "theme": theme,
        "fonts": dict(graphics_lab.FONTS),
        "look": {key: str(value) for key, value in look_content.items()},
        "zones": zones_of(callout["type"], layout, width, height),
        "look_version": look_version,
        "theme_version": theme_version,
    }


# --- What the state reads --------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptEntry:
    """One attempt of the component, with its jobs."""

    row: CalloutGraphic
    input_job: Job | None
    preview_job: Job | None
    # `writing` or `rendering` while a job of the attempt is waiting or running, else None.
    stage: str | None
    # Its preview is drawn from the resolved callout worked out now.
    current: bool
    # Why it has no preview, or None.
    error: str | None

    @property
    def has_preview(self) -> bool:
        return self.row.preview_path is not None

    @property
    def look_id(self) -> int | None:
        return _recorded_id(self.row, "look")


@dataclass(frozen=True)
class EngineEntry:
    """One version of a callout: its attempts, newest first, and where it stands."""

    key: str
    status: Status
    attempts: list[AttemptEntry]
    # The newest attempt that has a preview drawn from what is current now.
    best: AttemptEntry | None
    # Nothing more will be tried for this component and it has no current preview.
    failed_outright: bool
    # Why the newest attempt has no preview, when it has none.
    last_error: str | None

    @property
    def label(self) -> str:
        return ENGINE_LABELS[self.key]

    @property
    def newest(self) -> AttemptEntry | None:
        return self.attempts[0] if self.attempts else None


@dataclass(frozen=True)
class UsedGraphic:
    """What the story render draws for a callout (§4.5), and why. `engine` is `USED_BOX` when the
    component failed outright.
    """

    engine: str
    attempt: AttemptEntry | None
    because: str


@dataclass(frozen=True)
class CalloutEntry:
    """One callout of the newest plan and where its graphics stand."""

    callout: dict[str, Any]
    match_key: str
    enabled: bool
    status: Status
    # Why the preview is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str]
    # The resolved callout worked out now and its hash, or None when it cannot be.
    resolved: dict[str, Any] | None
    resolved_sha256: str | None
    engines: list[EngineEntry]
    # The callout has what the rule picks (a current component, or a box).
    done: bool
    used: UsedGraphic | None
    last_error: str | None
    # Why nothing can be made for this callout now, or None.
    refusal: str | None
    # `refusal`, or that the component is being made. `can_run` is whether Make may be pressed.
    can_run: bool
    blocked_reason: str | None
    # What the model is told about the callout besides its parts: the line, the mood. None when
    # nothing can be made now.
    material: dict[str, Any] | None
    look: Any
    theme: Any
    plan: Any


@dataclass(frozen=True)
class CalloutGraphicsState:
    """What the callout panel shows."""

    entries: list[CalloutEntry]
    blocked_reason: str | None
    wanted: bool
    # The callout look's version and whether it is current.
    look_version: int | None
    look_current: bool


def _recorded_id(row: CalloutGraphic, key: str) -> int | None:
    recorded = row.inputs.get(key) if isinstance(row.inputs, dict) else None
    value = recorded.get("id") if isinstance(recorded, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _failure(job: Job | None) -> str | None:
    if job is None:
        return None
    if job.status == "failed":
        return job.error or "the job failed"
    if job.status == "cancelled":
        return "the job was cancelled"
    return None


def _attempt(row: CalloutGraphic, jobs: dict[int, Job], current_sha: str | None) -> AttemptEntry:
    input_job = jobs.get(row.input_job_id) if row.input_job_id is not None else None
    preview_job = jobs.get(row.preview_job_id) if row.preview_job_id is not None else None
    stage: str | None = None
    if input_job is not None and input_job.status in store.ACTIVE_STATUSES:
        stage = "writing"
    elif preview_job is not None and preview_job.status in store.ACTIVE_STATUSES:
        stage = "rendering"
    recorded = row.inputs.get("resolved_sha256") if isinstance(row.inputs, dict) else None
    error: str | None = None
    if row.preview_path is None and stage is None:
        error = row.last_error or _failure(preview_job) or _failure(input_job) or STOPPED_MESSAGE
    return AttemptEntry(
        row=row,
        input_job=input_job,
        preview_job=preview_job,
        stage=stage,
        current=current_sha is not None and recorded == current_sha,
        error=error,
    )


def _engine(
    key: str,
    rows: list[CalloutGraphic],
    jobs: dict[int, Job],
    sha: str | None,
    look_id: int | None,
) -> EngineEntry:
    attempts = [
        _attempt(row, jobs, sha) for row in sorted(rows, key=lambda row: row.attempt, reverse=True)
    ]
    best = next((a for a in attempts if a.has_preview and a.current), None)
    newest = attempts[0] if attempts else None
    # A failure counts only while it was made under the current callout look: a new look gives
    # the callout a new try.
    outright = (
        newest is not None
        and newest.row.failed_outright
        and best is None
        and newest.look_id == look_id
    )
    status: Status
    if any(a.stage is not None for a in attempts):
        status = "writing" if any(a.stage == "writing" for a in attempts) else "rendering"
    elif best is not None:
        status = "ready"
    elif outright:
        status = "failed"
    elif any(a.has_preview for a in attempts):
        status = "out_of_date"
    elif newest is not None and newest.row.failed_outright:
        status = "out_of_date"
    elif newest is not None:
        status = "failed"
    else:
        status = "none"
    return EngineEntry(
        key=key,
        status=status,
        attempts=attempts,
        best=best,
        failed_outright=outright,
        last_error=newest.error if newest is not None and best is None else None,
    )


def _used(engine: EngineEntry) -> UsedGraphic | None:
    """What the render draws (§4.5, with the component only): the component when it has a current
    preview, a box when it failed outright, else nothing yet.
    """
    if engine.best is not None:
        return UsedGraphic(engine.key, engine.best, USED_DEFAULT)
    if engine.failed_outright:
        return UsedGraphic(USED_BOX, None, USED_COMPONENT_FAILED)
    return None


def _out_of_date_reasons(engines: list[EngineEntry], look: Any, theme: Any) -> list[str]:
    reasons: list[str] = []
    for engine in engines:
        newest = engine.newest
        if engine.status != "out_of_date" or newest is None:
            continue
        row = newest.row
        if look is not None and newest.look_id != look.id:
            reason = LOOK_REASON
        elif theme is not None and _recorded_id(row, "theme") != theme.id:
            reason = THEME_REASON
        else:
            reason = OTHER_REASON
        if reason not in reasons:
            reasons.append(reason)
    return reasons


async def _rows_by_key(
    session: AsyncSession, project_id: int
) -> dict[tuple[str, str], list[CalloutGraphic]]:
    statement = (
        select(CalloutGraphic)
        .where(CalloutGraphic.project_id == project_id)
        .order_by(CalloutGraphic.id)
        .execution_options(populate_existing=True)
    )
    grouped: dict[tuple[str, str], list[CalloutGraphic]] = {}
    for row in (await session.execute(statement)).scalars():
        grouped.setdefault((row.match_key, row.engine), []).append(row)
    return grouped


async def _jobs_of(session: AsyncSession, rows: list[CalloutGraphic]) -> dict[int, Job]:
    ids = {
        job_id
        for row in rows
        for job_id in (row.input_job_id, row.preview_job_id)
        if job_id is not None
    }
    if not ids:
        return {}
    statement = select(Job).where(Job.id.in_(ids)).execution_options(populate_existing=True)
    return {job.id: job for job in (await session.execute(statement)).scalars()}


def _blocked(
    project: Project,
    plan_state: callout_plan.CalloutPlanState,
    look_state: callout_look.CalloutLookState,
    theme_state: graphic_theme.GraphicThemeState,
) -> str | None:
    """Why no callout graphics can be made now (or at all for this project), or None."""
    if not callout_look.wanted(project):
        return callout_look.OFF_MESSAGE
    if plan_state.job is not None and plan_state.job.status in store.ACTIVE_STATUSES:
        return PLAN_BEING_WRITTEN_MESSAGE
    if plan_state.latest is None:
        return plan_state.blocked_reason or PLAN_MISSING_MESSAGE
    if plan_state.out_of_date:
        return PLAN_OUT_OF_DATE_MESSAGE
    if look_state.job is not None and look_state.job.status in store.ACTIVE_STATUSES:
        return LOOK_BEING_WRITTEN_MESSAGE
    if look_state.latest is None:
        return LOOK_MISSING_MESSAGE
    if look_state.out_of_date:
        return LOOK_OUT_OF_DATE_MESSAGE
    if theme_state.latest is None:
        return THEME_MISSING_MESSAGE
    return None


def _prepare(
    project: Project,
    callout: dict[str, Any],
    units: dict[tuple[str, str], ScriptUnit],
    theme: Any,
    look: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """The resolved callout and what the job needs (the line and the mood), or why it cannot be
    worked out.
    """
    unit = units.get((callout["scene_id"], callout["unit_id"]))
    if unit is None:
        return None, None, NO_UNIT_MESSAGE
    try:
        resolved = resolve_callout(
            callout=callout,
            unit=unit,
            theme_content=theme.content["theme"],
            theme_version=theme.version,
            look_content=look.content["look"],
            look_version=look.version,
            width=project.out_width,
            height=project.out_height,
            fps=project.fps,
        )
    except CalloutGraphicsError as exc:
        return None, None, str(exc)
    material = {"line": unit.text, "mood": str(theme.content["theme"].get("mood") or "")}
    return resolved, material, None


async def _build(session: AsyncSession, project: Project) -> CalloutGraphicsState:
    plan_state = await callout_plan.state(session, project)
    look_state = await callout_look.state(session, project)
    theme_state = await graphic_theme.state(session, project)
    blocked = _blocked(project, plan_state, look_state, theme_state)
    wanted = callout_look.wanted(project)
    look = look_state.latest
    theme = theme_state.latest
    if not wanted or plan_state.latest is None:
        return CalloutGraphicsState(
            entries=[],
            blocked_reason=blocked,
            wanted=wanted,
            look_version=look.version if look is not None else None,
            look_current=look is not None and not look_state.out_of_date,
        )

    plan = plan_state.latest
    units = {(unit.scene_id, unit.unit_id): unit for unit in plan_state.script}
    grouped = await _rows_by_key(session, project.id)
    jobs = await _jobs_of(session, [row for rows in grouped.values() for row in rows])

    entries: list[CalloutEntry] = []
    for callout in plan.content["callouts"]:
        key = match_key(callout)
        enabled = bool(callout.get("enabled"))
        prepared: dict[str, Any] | None = None
        material: dict[str, Any] | None = None
        problem: str | None = None
        if enabled and blocked is None and look is not None and theme is not None:
            prepared, material, problem = _prepare(project, callout, units, theme, look)
        sha = resolved_sha256(prepared) if prepared is not None else None
        engines = (
            [
                _engine(
                    engine,
                    grouped.get((key, engine), []),
                    jobs,
                    sha,
                    look.id if look is not None else None,
                )
                for engine in ENGINES
            ]
            if enabled
            else []
        )
        entries.append(
            _callout_entry(
                callout,
                key,
                enabled,
                blocked,
                problem,
                prepared,
                sha,
                material,
                engines,
                look,
                theme,
                plan,
            )
        )
    return CalloutGraphicsState(
        entries=entries,
        blocked_reason=blocked,
        wanted=True,
        look_version=look.version if look is not None else None,
        look_current=look is not None and not look_state.out_of_date,
    )


def _callout_entry(
    callout: dict[str, Any],
    key: str,
    enabled: bool,
    blocked: str | None,
    problem: str | None,
    prepared: dict[str, Any] | None,
    sha: str | None,
    material: dict[str, Any] | None,
    engines: list[EngineEntry],
    look: Any,
    theme: Any,
    plan: Any,
) -> CalloutEntry:
    refusal = OFF_CALLOUT_MESSAGE if not enabled else (blocked if blocked is not None else problem)
    used = _used(engines[0]) if engines else None
    working = any(e.status in ("writing", "rendering") for e in engines)
    reasons: list[str] = []
    errors: list[str] = []
    status: Status
    if working:
        status = "working"
    elif used is not None and used.engine != USED_BOX:
        status = "ready"
    else:
        reasons = _out_of_date_reasons(engines, look, theme)
        errors = [
            f"{e.label}: {e.last_error}"
            for e in engines
            if e.status == "failed" and e.last_error is not None
        ]
        if any(e.status == "out_of_date" for e in engines):
            status = "out_of_date"
        elif errors:
            status = "failed"
        else:
            status = "none"
    can_block = refusal if refusal is not None else (BEING_MADE_MESSAGE if working else None)
    return CalloutEntry(
        callout=callout,
        match_key=key,
        enabled=enabled,
        status=status,
        reasons=reasons,
        resolved=prepared,
        resolved_sha256=sha,
        engines=engines,
        done=used is not None,
        used=used,
        last_error="; ".join(errors) if errors else None,
        refusal=refusal,
        can_run=can_block is None,
        blocked_reason=can_block,
        material=material if refusal is None else None,
        look=look,
        theme=theme,
        plan=plan,
    )


@memoized_state
async def state(session: AsyncSession, project: Project) -> CalloutGraphicsState:
    """The callouts of the newest plan with where the graphics of each stand. Worked out on every
    read; nothing here is stored but the attempts.
    """
    return await _build(session, project)


# --- Starting ---------------------------------------------------------------------------------


def graphic_key(match: str, engine: str) -> str:
    return f"{match}/{engine}"


def _attempt_inputs(entry: CalloutEntry, rerender_of: int | None = None) -> dict[str, Any]:
    assert entry.resolved is not None and entry.look is not None and entry.theme is not None
    inputs: dict[str, Any] = {
        "resolved": entry.resolved,
        "resolved_sha256": entry.resolved_sha256,
        "plan": {"id": entry.plan.id, "version": entry.plan.version},
        "look": {"id": entry.look.id, "version": entry.look.version},
        "theme": {"id": entry.theme.id, "version": entry.theme.version},
    }
    if rerender_of is not None:
        inputs["rerender_of"] = rerender_of
    return inputs


async def queue_preview(session: AsyncSession, row: CalloutGraphic) -> Job:
    """Queues the job that draws the preview of an attempt from the code it holds and links it
    as the attempt's `preview_job_id`. No commit: the caller commits it together with the row.
    Two presses on one attempt make one job.
    """
    job, _created = await store.create_job(
        session,
        project_id=row.project_id,
        type=PREVIEW_JOB_TYPE,
        provider="local",
        input={PREVIEW_DEDUPE_KEY: row.id},
        commit=False,
        dedupe_key=PREVIEW_DEDUPE_KEY,
    )
    row.preview_job_id = job.id
    row.last_error = None
    return job


async def _next_attempt(session: AsyncSession, project_id: int, match: str, engine: str) -> int:
    statement = select(func.max(CalloutGraphic.attempt)).where(
        CalloutGraphic.project_id == project_id,
        CalloutGraphic.match_key == match,
        CalloutGraphic.engine == engine,
    )
    return ((await session.execute(statement)).scalar_one_or_none() or 0) + 1


async def _new_row(
    session: AsyncSession,
    project: Project,
    entry: CalloutEntry,
    engine: str,
    *,
    input: Any = None,
    rerender_of: int | None = None,
    repair_of: int | None = None,
) -> CalloutGraphic:
    row = CalloutGraphic(
        project_id=project.id,
        plan_id=entry.plan.id,
        callout_id=entry.callout["id"],
        match_key=entry.match_key,
        engine=engine,
        attempt=await _next_attempt(session, project.id, entry.match_key, engine),
        repair_of=repair_of,
        input=input,
        inputs=_attempt_inputs(entry, rerender_of),
    )
    session.add(row)
    await session.flush()
    return row


async def _write(
    session: AsyncSession,
    project: Project,
    entry: CalloutEntry,
    engine: str,
    *,
    repair_of: int | None = None,
    repair: dict[str, Any] | None = None,
) -> Job | None:
    """A new attempt that asks the model for the code. None when a job of this kind is already
    waiting or running for the callout. `repair_of` and `repair` make it the repair of a
    component whose preview failed (see `queue_repair`).
    """
    assert entry.material is not None and entry.resolved is not None
    row = await _new_row(session, project, entry, engine, repair_of=repair_of)
    job_input: dict[str, Any] = {
        WRITE_DEDUPE_KEY: graphic_key(entry.match_key, engine),
        PREVIEW_DEDUPE_KEY: row.id,
        "callout_id": entry.callout["id"],
        "line": entry.material["line"],
        "mood": entry.material["mood"],
        "orientation": project.orientation,
        "resolved": entry.resolved,
    }
    if repair is not None:
        job_input["repair"] = repair
    job, created = await store.create_job(
        session,
        project_id=project.id,
        type=WRITE_JOB_TYPES[engine],
        provider="llm",
        input=job_input,
        commit=False,
        dedupe_key=WRITE_DEDUPE_KEY,
    )
    if not created:
        await session.delete(row)
        await session.flush()
        return None
    row.input_job_id = job.id
    return job


async def _again_from(
    session: AsyncSession,
    project: Project,
    entry: CalloutEntry,
    engine: str,
    source: CalloutGraphic,
) -> Job:
    """A new attempt that has the code of `source` and no model call: its preview checks the code
    again and draws it from what is current now.
    """
    row = await _new_row(session, project, entry, engine, input=source.input, rerender_of=source.id)
    return await queue_preview(session, row)


async def repair_limit(session: AsyncSession) -> int:
    """How many repair asks one chain of attempts may spend (the setting, 0 to 3)."""
    return await settings_service.get_int(session, settings_service.GRAPHICS_COMPONENT_REPAIRS_KEY)


async def repairs_used(session: AsyncSession, row: CalloutGraphic) -> int:
    """The repair asks spent by the chain `row` belongs to, up to and including `row`: the asks
    recorded on each attempt (`input.checks.repairs`) along `repair_of`. An attempt that no model
    call wrote (the new-words and new-colours attempts, which copy an earlier input) has spent
    none, whatever input it holds.
    """
    used = 0
    seen: set[int] = set()
    current: CalloutGraphic | None = row
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if current.input_job_id is not None and isinstance(current.input, dict):
            checks = current.input.get("checks")
            count = checks.get("repairs") if isinstance(checks, dict) else None
            if isinstance(count, int) and not isinstance(count, bool):
                used += count
        current = (
            await session.get(CalloutGraphic, current.repair_of)
            if current.repair_of is not None
            else None
        )
    return used


def _find(state_: CalloutGraphicsState, callout_id: str) -> CalloutEntry:
    for entry in state_.entries:
        if entry.callout["id"] == callout_id:
            return entry
    raise CalloutGraphicsError(NOT_FOUND_MESSAGE)


def _find_key(state_: CalloutGraphicsState, match: str) -> CalloutEntry | None:
    return next((entry for entry in state_.entries if entry.match_key == match), None)


async def queue_repair(
    session: AsyncSession,
    project: Project,
    row: CalloutGraphic,
    errors: list[str],
    repairs_before: int,
) -> Job | None:
    """The repair of a component whose preview failed: a new attempt, with `repair_of` set to
    `row`, and a write job that is given the code and the errors. No commit: the caller commits
    it with the failure it records.

    None when nothing can be repaired now: the attempt has no code, or the callout has moved on
    (it has a refusal, or its words, colours, size or look are no longer the ones `row` was drawn
    from, so the next Make starts from what is current), or a write job of the callout is already
    waiting. The caller has checked the budget.
    """
    code = graphics_render.code_of(row.input)
    if code is None or row.engine != COMPONENT:
        return None
    entry = _find_key(await _build(session, project), row.match_key)
    recorded = row.inputs.get("resolved_sha256") if isinstance(row.inputs, dict) else None
    if (
        entry is None
        or entry.refusal is not None
        or recorded is None
        or entry.resolved_sha256 != recorded
    ):
        return None
    repair = {
        "of": row.id,
        "code": code,
        "errors": errors,
        "stage": "render",
        "repairs_before": repairs_before,
    }
    return await _write(session, project, entry, COMPONENT, repair_of=row.id, repair=repair)


async def _start_engine(
    session: AsyncSession, project: Project, entry: CalloutEntry, engine: EngineEntry
) -> Job | None:
    if engine.status in ("writing", "rendering", "ready") or engine.failed_outright:
        return None
    source = next((a for a in engine.attempts if a.row.input is not None), None)
    if source is None:
        return await _write(session, project, entry, engine.key)
    if not source.current:
        # Only the words or the colours changed: the same code is drawn again. A new callout look
        # is a new model call.
        if entry.look is not None and source.look_id == entry.look.id:
            return await _again_from(session, project, entry, engine.key, source.row)
        return await _write(session, project, entry, engine.key)
    if source.has_preview:
        return None
    return await queue_preview(session, source.row)


async def _start_entry(session: AsyncSession, project: Project, entry: CalloutEntry) -> list[Job]:
    jobs: list[Job] = []
    for engine in entry.engines:
        job = await _start_engine(session, project, entry, engine)
        if job is not None:
            jobs.append(job)
    return jobs


async def start_callout(session: AsyncSession, project: Project, callout_id: str) -> list[Job]:
    """Makes what is missing for one callout (see the module note): the jobs it queued, in one
    transaction, committed. A callout that has everything makes none. Raises
    CalloutGraphicsError when its graphics cannot be made now.
    """
    entry = _find(await _build(session, project), callout_id)
    if not entry.can_run:
        raise CalloutGraphicsError(entry.blocked_reason or BEING_MADE_MESSAGE)
    jobs = await _start_entry(session, project, entry)
    await session.commit()
    return jobs


async def start_all(session: AsyncSession, project: Project) -> list[Job]:
    """Makes what is missing for every callout that is turned on: the jobs queued, in one
    transaction, committed. A callout that cannot be made now, or that is being made, is left
    out. Raises CalloutGraphicsError when nothing can be made for the project now.
    """
    built = await _build(session, project)
    if built.blocked_reason is not None:
        raise CalloutGraphicsError(built.blocked_reason)
    jobs: list[Job] = []
    for entry in built.entries:
        if entry.enabled and entry.can_run:
            jobs.extend(await _start_entry(session, project, entry))
    await session.commit()
    return jobs


async def ask_again(session: AsyncSession, project: Project, callout_id: str, engine: str) -> Job:
    """A paid model call for one version, as a new attempt. Commits. Raises CalloutGraphicsError
    when it cannot be asked now.
    """
    if engine not in ENGINES:
        raise CalloutGraphicsError(f"'{engine}' is not one of the versions of a callout.")
    entry = _find(await _build(session, project), callout_id)
    if entry.refusal is not None:
        raise CalloutGraphicsError(entry.refusal)
    if next(e for e in entry.engines if e.key == engine).status in ("writing", "rendering"):
        raise CalloutGraphicsError(ENGINE_BUSY_MESSAGE)
    job = await _write(session, project, entry, engine)
    if job is None:
        raise CalloutGraphicsError(ENGINE_BUSY_MESSAGE)
    await session.commit()
    return job
