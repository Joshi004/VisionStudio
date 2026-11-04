"""The trial batch of the Graphics lab (GFX-012): the ten excerpts of Appendix A through every
engine that is still started, and a summary that counts the results per engine (§4.9 of
`Graphics_lab_implementation_phases.md`).

**A trial set** is the ten runs one click makes. Each run's `trial_case_key` is `"<set>:<case>"`
(for example `"3:T05"`), so a set is found by its number and no migration is needed. A trial run
is an ordinary run: it is opened, judged, asked again and deleted like any other.

**How a trial starts.** `start_trial` makes the ten runs, then:

- without a voice, it presses **Make all** on each (`graphics_lab.make_all`): the brief is
  written, and then every built engine that is not retired starts (EXG-008: the two template
  engines are not started any more, so a run makes three calls);
- with a voice, each run's speech is made first. The brief waits for the voice's timing
  (GFX-004), so `time_lab_graphic_words` calls `start_after_timing` when it has stored the timing
  of a trial run, and that starts the brief and then the engines.

The click on **Run the trial** is the click that G-13 asks for: the paid calls it starts are
shown and confirmed before it is sent.

**What the summary counts.** For each run and engine, the render that counts is the newest one
that is not a **Render again** (so what the card shows and what the owner judges). Renders that
repeat another only feed the repeat counts. Nothing here calls a model.

Excerpts are in code: ten short rows are clearer in a diff than a JSON file with a loader.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, LabGraphicRender, LabGraphicRun, Voice
from app.db.session import SessionLocal
from app.jobs import store
from app.services import graphics_engines, graphics_lab

_logger = logging.getLogger(__name__)

OrientationMode = Literal["own", "landscape", "portrait"]
ORIENTATION_MODES: Final = ("own", "landscape", "portrait")

# What each run of a trial asks of the paid model (§4.1): the brief, the block scene and the
# component. The template spec is no longer asked for (EXG-008). With every retry the most is
# 2 + 3 + 3 attempts (a scene and a component may be asked a third time, GFX-009 and GFX-010).
CALLS_PER_RUN: Final = 3
MOST_CALLS_PER_RUN: Final = 8


@dataclass(frozen=True)
class Excerpt:
    """One line of Appendix A, with the orientation it runs in when the trial uses each excerpt's
    own.
    """

    key: str
    domain: str
    text: str
    orientation: Literal["landscape", "portrait"]
    tests: str


# Appendix A as it stands (the companies and numbers are made up). The four portrait excerpts
# make sure a line chart, a vertical flow, benchmark bars and a list are each tried in portrait.
EXCERPTS: Final[tuple[Excerpt, ...]] = (
    Excerpt(
        "T01",
        "Finance",
        "Acme's revenue has exploded. It made 12 billion dollars in 2023, 19 billion in 2024, "
        "and 31 billion in 2025. That's more than double in two years.",
        "landscape",
        "Bars, a derived percent change, a beat per year",
    ),
    Excerpt(
        "T02",
        "Finance",
        "Northwind's stock closed at 84 dollars on Friday, down 6.5 percent in a single day, "
        "its worst drop since March.",
        "landscape",
        "A KPI with a negative change",
    ),
    Excerpt(
        "T03",
        "Finance",
        "Over the last five quarters, Globex's operating margin went from 18 percent to 21, "
        "then 24, dipped to 22, and reached 27 percent this quarter.",
        "portrait",
        "A line through five points, an axis that does not start at zero",
    ),
    Excerpt(
        "T04",
        "Finance",
        "Initech trades at 45 times earnings, while its closest rival, Umbrella, trades at just "
        "19 times. Investors pay more than twice as much for every dollar Initech earns.",
        "landscape",
        "A comparison of multiples, a derived ratio",
    ),
    Excerpt(
        "T05",
        "AI",
        "A large language model works in three steps. It splits your text into tokens, turns "
        "each token into a vector, and then predicts the next token, one at a time.",
        "landscape",
        "A three-step flow",
    ),
    Excerpt(
        "T06",
        "AI",
        "Retrieval augmented generation adds one step before the answer: your question searches "
        "your documents, the best matches are added to the prompt, and only then does the model "
        "write its reply.",
        "portrait",
        "A four-step flow with longer labels",
    ),
    Excerpt(
        "T07",
        "AI",
        "On the coding benchmark, the new model scored 71 percent, up from 48 percent for the "
        "previous version, and ahead of the 64 percent of its closest competitor.",
        "portrait",
        "Benchmark bars with an emphasis",
    ),
    Excerpt(
        "T08",
        "AI",
        "Attention lets every word look at every other word in the sentence, so 'it' can learn "
        "that it means 'the animal' and not 'the street'.",
        "landscape",
        "A concept with no numbers: no template should fit",
    ),
    Excerpt(
        "T09",
        "General",
        "There are three reasons this matters: it is cheaper, it is faster, and it works offline.",
        "portrait",
        "A list that builds item by item",
    ),
    Excerpt(
        "T10",
        "General",
        "Here is the part nobody talks about.",
        "landscape",
        "A very short line (the 3 s minimum), a statement card",
    ),
)
EXCERPT_BY_KEY: Final = {excerpt.key: excerpt for excerpt in EXCERPTS}


class GraphicsTrialConflictError(Exception):
    """A trial that cannot start now. The message is meant for the user (HTTP 409)."""


# --- Case keys ------------------------------------------------------------------------------

_CASE_KEY = re.compile(r"([1-9][0-9]{0,8}):(T[0-9]{2})")


def case_key(set_no: int, key: str) -> str:
    """The `trial_case_key` of an excerpt in a set: `"3:T05"`."""
    return f"{set_no}:{key}"


def parse_case_key(value: str | None) -> tuple[int, str] | None:
    """The set and the excerpt key of a `trial_case_key`, or None when it is not one."""
    found = _CASE_KEY.fullmatch(value) if value is not None else None
    return (int(found.group(1)), found.group(2)) if found is not None else None


# --- Cost -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class TrialCost:
    """What a trial will do, shown before it starts."""

    runs: int
    paid_calls: int
    most_paid_calls: int
    # Speeches on the GPU server (each is then timed by Parakeet): one per run with a voice.
    speeches: int


def trial_cost(*, with_voice: bool) -> TrialCost:
    runs = len(EXCERPTS)
    return TrialCost(
        runs=runs,
        paid_calls=runs * CALLS_PER_RUN,
        most_paid_calls=runs * MOST_CALLS_PER_RUN,
        speeches=runs if with_voice else 0,
    )


# --- Starting a trial -----------------------------------------------------------------------


@dataclass(frozen=True)
class TrialSet:
    set_no: int
    created_at: datetime
    runs: int


async def list_sets(session: AsyncSession) -> list[TrialSet]:
    """The trial sets, newest first."""
    statement = select(LabGraphicRun.trial_case_key, LabGraphicRun.created_at).where(
        LabGraphicRun.trial_case_key.is_not(None)
    )
    found: dict[int, tuple[datetime, int]] = {}
    for key, created_at in (await session.execute(statement)).all():
        parsed = parse_case_key(key)
        if parsed is None:
            continue
        first, count = found.get(parsed[0], (created_at, 0))
        found[parsed[0]] = (min(first, created_at), count + 1)
    return [
        TrialSet(set_no=set_no, created_at=first, runs=count)
        for set_no, (first, count) in sorted(found.items(), reverse=True)
    ]


def _run_busy(row: graphics_lab.RunRow) -> bool:
    """True while a trial run's voice or brief is still being made (its engines may follow)."""
    if row.state in ("making_voice", "writing_brief"):
        return True
    # The speech is timed and the brief not asked for yet: the hook is about to start it.
    return row.state == "new" and row.run.speech_run_id is not None and row.run.last_error is None


async def start_trial(
    session: AsyncSession, voice_id: int | None, orientation: OrientationMode
) -> tuple[int, list[int]]:
    """Makes the ten runs of a new trial set and starts them. Commits. Returns the set's number
    and the runs' ids.

    Raises GraphicsLabInputError for an unknown orientation mode or voice, or a line that is too
    long (before anything is made), and GraphicsTrialConflictError while the newest set is still
    making its voices or briefs (a second click would pay for a second set).
    """
    if orientation not in ORIENTATION_MODES:
        raise graphics_lab.GraphicsLabInputError(
            "Choose each excerpt's own orientation, landscape or portrait."
        )
    if voice_id is not None and await session.get(Voice, voice_id) is None:
        raise graphics_lab.GraphicsLabInputError("That voice does not exist.")
    for excerpt in EXCERPTS:
        await graphics_lab.check_line_fits(session, excerpt.text)

    sets = await list_sets(session)
    if sets:
        for row in await graphics_lab.trial_runs(session, sets[0].set_no):
            if _run_busy(row):
                raise GraphicsTrialConflictError(
                    f"Trial set {sets[0].set_no} is still being made. Start another when its "
                    "voices and briefs are done."
                )
    set_no = sets[0].set_no + 1 if sets else 1

    run_ids: list[int] = []
    for excerpt in EXCERPTS:
        try:
            row = await graphics_lab.create_run(
                session,
                excerpt.text,
                excerpt.orientation if orientation == "own" else orientation,
                voice_id,
                trial_case_key=case_key(set_no, excerpt.key),
            )
        except graphics_lab.GraphicsLabInputError as exc:
            if not run_ids:
                raise
            raise graphics_lab.GraphicsLabInputError(
                f"The run for {excerpt.key} could not be made: {exc} "
                f"The {len(run_ids)} runs before it were made (set {set_no})."
            ) from exc
        run_ids.append(row.run.id)
    _logger.info("trial set %d: %d runs made, voice=%s", set_no, len(run_ids), voice_id)

    if voice_id is None:
        for run_id in run_ids:
            await _start_run(session, run_id, make_all=True)
    return set_no, run_ids


async def _start_run(session: AsyncSession, run_id: int, *, make_all: bool) -> None:
    """Starts the brief of a trial run (and, with `make_all`, every engine after it). A failure
    is kept on the run, so one run never stops the others.
    """
    try:
        if make_all:
            await graphics_lab.make_all(session, run_id)
        else:
            await graphics_lab.start_brief(session, run_id, then_start_engines=True)
    except (
        graphics_lab.GraphicsLabConflictError,
        graphics_lab.GraphicsLabInputError,
    ) as exc:
        await session.rollback()
        run = await session.get(LabGraphicRun, run_id)
        if run is not None:
            run.last_error = f"The trial could not start this run: {exc}"[: store.ERROR_MAX_CHARS]
            await session.commit()


async def start_after_timing(run_id: int) -> bool:
    """Called (best effort) by the timing job once it has stored a run's timing. For a run of a
    trial that has no brief job yet, starts the brief and then the engines. Returns True when it
    did. Any other run is left alone: its brief is the owner's click.
    """
    async with SessionLocal() as session:
        run = await session.get(LabGraphicRun, run_id)
        if (
            run is None
            or parse_case_key(run.trial_case_key) is None
            or run.brief_job_id is not None
            or run.brief is not None
        ):
            return False
        await _start_run(session, run_id, make_all=False)
        started = await session.get(LabGraphicRun, run_id)
        return started is not None and started.brief_job_id is not None


# --- The summary ----------------------------------------------------------------------------

OutcomeKind = Literal["video", "no_fit", "failed", "working", "not_started"]
OUTCOME_KINDS: Final = ("video", "no_fit", "failed", "working", "not_started")


@dataclass(frozen=True)
class Outcome:
    """What became of one engine on one run (its counted render)."""

    kind: OutcomeKind
    render_id: int | None = None
    attempt: int | None = None
    verdict: str | None = None


@dataclass
class EngineSummary:
    key: str
    label: str
    runs: int = 0
    videos: int = 0
    no_fit: int = 0
    failed: int = 0
    working: int = 0
    not_started: int = 0
    # The three below are out of `videos`.
    checks_passed: int = 0
    no_layout_warning: int = 0
    numbers_traced: int = 0
    median_render_s: float | None = None
    median_tokens: int | None = None
    repeats_identical: int = 0
    repeats_differing: int = 0
    repeats_not_compared: int = 0
    verdict_good: int = 0
    verdict_usable: int = 0
    verdict_bad: int = 0
    verdict_none: int = 0


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    case: str
    domain: str
    line_text: str
    orientation: str
    state: str
    last_error: str | None
    outcomes: dict[str, Outcome]


@dataclass(frozen=True)
class TrialSummary:
    set_no: int
    created_at: datetime
    with_voice: bool
    active: bool
    engines: list[EngineSummary]
    runs: list[RunSummary] = field(default_factory=list)


def _is_working(row: graphics_lab.RenderRow) -> bool:
    return any(
        job is not None and job.status in store.ACTIVE_STATUSES
        for job in (row.input_job, row.render_job)
    )


def _job_failed(job: Job | None) -> bool:
    return job is not None and job.status in ("failed", "cancelled")


def outcome_of(row: graphics_lab.RenderRow | None) -> Outcome:
    """What a counted render came to. No render at all is `not_started`."""
    if row is None:
        return Outcome("not_started")
    render = row.render
    ids = {"render_id": render.id, "attempt": render.attempt, "verdict": render.verdict}
    if _is_working(row):
        return Outcome("working", **ids)
    if render.media_path is not None:
        return Outcome("video", **ids)
    spec = render.input if isinstance(render.input, dict) else {}
    if "template" in spec and spec["template"] is None:
        return Outcome("no_fit", **ids)
    checks = spec.get("checks")
    code_failed = isinstance(checks, dict) and checks.get("passed") is False
    if render.last_error is not None or _job_failed(row.input_job) or _job_failed(row.render_job):
        return Outcome("failed", **ids)
    if code_failed:
        return Outcome("failed", **ids)
    return Outcome("not_started", **ids)


def _counted(row: graphics_lab.RunRow, engine_key: str) -> graphics_lab.RenderRow | None:
    """The newest render of the engine that does not repeat another (the rows are newest first)."""
    return next(
        (
            render_row
            for render_row in row.renders
            if render_row.render.engine == engine_key and render_row.render.repeat_of is None
        ),
        None,
    )


def _metrics(render: LabGraphicRender) -> dict[str, Any]:
    return render.metrics if isinstance(render.metrics, dict) else {}


def _checks_passed(metrics: dict[str, Any]) -> bool:
    checks = metrics.get("checks")
    return isinstance(checks, dict) and all(
        checks.get(name) is True for name in ("frames", "size", "fps")
    )


def _tokens(row: graphics_lab.RenderRow) -> int | None:
    call = graphics_lab.input_call_of(row.input_job)
    if call is None or (call.prompt_tokens is None and call.completion_tokens is None):
        return None
    return (call.prompt_tokens or 0) + (call.completion_tokens or 0)


def _count_video(summary: EngineSummary, row: graphics_lab.RenderRow, engine_key: str) -> None:
    """Adds one counted render that has a video to the engine's checks and verdicts."""
    metrics = _metrics(row.render)
    if _checks_passed(metrics):
        summary.checks_passed += 1
    if metrics.get("layout_problems") == 0:
        summary.no_layout_warning += 1
    # Only the generated component can show a number nothing traced: the other engines refuse
    # one before they draw (G-7), so every video of theirs counts.
    if engine_key != "generated_component" or metrics.get("untraced_numbers") == 0:
        summary.numbers_traced += 1
    verdict = row.render.verdict
    if verdict == "good":
        summary.verdict_good += 1
    elif verdict == "usable":
        summary.verdict_usable += 1
    elif verdict == "bad":
        summary.verdict_bad += 1
    else:
        summary.verdict_none += 1


def _count_repeats(summary: EngineSummary, rows: list[graphics_lab.RunRow], key: str) -> None:
    for run_row in rows:
        for render_row in run_row.renders:
            render = render_row.render
            if render.engine != key or render.repeat_of is None:
                continue
            repeat = _metrics(render).get("repeat")
            if not isinstance(repeat, dict):
                continue
            differing = repeat.get("differing")
            if isinstance(differing, int) and not isinstance(differing, bool):
                if differing == 0:
                    summary.repeats_identical += 1
                else:
                    summary.repeats_differing += 1
            else:
                summary.repeats_not_compared += 1


def summarize_rows(set_no: int, rows: list[graphics_lab.RunRow]) -> TrialSummary:
    """The counts and medians of §4.9 for the runs of one set. Pure: it reads the rows only."""
    # A retired engine (EXG-008) is counted only in a set that has a render of it: an old set
    # keeps its columns, a new one has none to show.
    with_renders = {render_row.render.engine for run_row in rows for render_row in run_row.renders}
    summaries = {
        key: EngineSummary(key=key, label=engine.label)
        for key, engine in graphics_engines.ENGINES.items()
        if not engine.retired or key in with_renders
    }
    seconds: dict[str, list[float]] = {key: [] for key in summaries}
    tokens: dict[str, list[int]] = {key: [] for key in summaries}
    runs: list[RunSummary] = []
    active = False

    for run_row in rows:
        parsed = parse_case_key(run_row.run.trial_case_key)
        case = parsed[1] if parsed is not None else "?"
        excerpt = EXCERPT_BY_KEY.get(case)
        outcomes: dict[str, Outcome] = {}
        active = active or _run_busy(run_row)
        for key, summary in summaries.items():
            counted = _counted(run_row, key)
            outcome = outcome_of(counted)
            outcomes[key] = outcome
            summary.runs += 1
            if outcome.kind == "video":
                summary.videos += 1
            elif outcome.kind == "no_fit":
                summary.no_fit += 1
            elif outcome.kind == "failed":
                summary.failed += 1
            elif outcome.kind == "working":
                summary.working += 1
            else:
                summary.not_started += 1
            if counted is None:
                continue
            active = active or outcome.kind == "working"
            used = _tokens(counted)
            if used is not None:
                tokens[key].append(used)
            if outcome.kind == "video":
                _count_video(summary, counted, key)
                render_s = _metrics(counted.render).get("render_s")
                if isinstance(render_s, int | float) and not isinstance(render_s, bool):
                    seconds[key].append(float(render_s))
        runs.append(
            RunSummary(
                run_id=run_row.run.id,
                case=case,
                domain=excerpt.domain if excerpt is not None else "",
                line_text=run_row.run.line_text,
                orientation=run_row.run.orientation,
                state=run_row.state,
                last_error=run_row.run.last_error,
                outcomes=outcomes,
            )
        )

    for key, summary in summaries.items():
        _count_repeats(summary, rows, key)
        if seconds[key]:
            summary.median_render_s = round(statistics.median(seconds[key]), 1)
        if tokens[key]:
            summary.median_tokens = round(statistics.median(tokens[key]))

    created = min((row.run.created_at for row in rows), default=datetime.min)
    return TrialSummary(
        set_no=set_no,
        created_at=created,
        with_voice=any(row.run.speech_run_id is not None for row in rows),
        active=active,
        engines=list(summaries.values()),
        runs=runs,
    )


async def summarize(session: AsyncSession, set_no: int) -> TrialSummary | None:
    """The summary of a trial set, or None when no run belongs to it."""
    rows = await graphics_lab.trial_runs(session, set_no)
    return summarize_rows(set_no, rows) if rows else None
