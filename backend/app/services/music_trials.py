"""The cases of a Music lab trial round (MUSIC-005): the guide text the review screen shows, the
runs and local recordings each case made, and the person's answer.

The trial helper (`music_lab_trials/trigger.py`) writes a case with `save_case` when it starts it.
The runs are ordinary lab runs and keep their own verdict and note; only the case's answer lives
here. This module never calls the GPU server and never deletes anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LabMusicRun, LabMusicSource, LabMusicTrialCase
from app.db.types import utcnow
from app.services import music_lab

_logger = logging.getLogger(__name__)

ANSWERS: Final = ("yes", "partly", "no")
NOTE_MAX_CHARS: Final = 2000
MAX_CASES: Final = 200


class TrialInputError(ValueError):
    """Something the request gets wrong. The message is meant for the user (HTTP 422)."""


@dataclass(frozen=True)
class CaseRow:
    """A case with the runs and recordings it refers to."""

    case: LabMusicTrialCase
    runs: list[music_lab.RunRow]
    # The recordings the case made locally, in the order of `case.source_ids`.
    local_outputs: list[LabMusicSource]
    # The runs and recordings the guide names as the source audio, keyed by id.
    source_runs: dict[int, LabMusicRun]
    source_files: dict[int, LabMusicSource]


def _ids(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]


def _guide_source_ids(guide: object) -> tuple[list[int], list[int]]:
    """The run ids and the recording ids the guide names as the source audio."""
    runs: list[int] = []
    files: list[int] = []
    sources = guide.get("sources") if isinstance(guide, dict) else None
    for item in sources if isinstance(sources, list) else []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("run_id"), int):
            runs.append(item["run_id"])
        if isinstance(item.get("source_id"), int):
            files.append(item["source_id"])
    return runs, files


async def save_case(
    session: AsyncSession,
    case_id: str,
    *,
    trial_group: str,
    sort_order: int,
    title: str,
    guide: dict[str, Any],
    run_ids: list[int],
    source_ids: list[int],
) -> LabMusicTrialCase:
    """Creates the case, or rewrites its guide and its runs. The answer is never touched.
    Commits. Raises TrialInputError when a run or a recording does not exist.
    """
    guide_runs, guide_files = _guide_source_ids(guide)
    if run_ids or guide_runs:
        found = await session.execute(
            select(LabMusicRun.id).where(LabMusicRun.id.in_({*run_ids, *guide_runs}))
        )
        missing = {*run_ids, *guide_runs} - set(found.scalars())
        if missing:
            raise TrialInputError(f"Run {min(missing)} does not exist.")
    if source_ids or guide_files:
        found = await session.execute(
            select(LabMusicSource.id).where(LabMusicSource.id.in_({*source_ids, *guide_files}))
        )
        missing = {*source_ids, *guide_files} - set(found.scalars())
        if missing:
            raise TrialInputError(f"Recording {min(missing)} does not exist.")

    case = await session.get(LabMusicTrialCase, case_id)
    if case is None:
        count = len((await session.execute(select(LabMusicTrialCase.id))).scalars().all())
        if count >= MAX_CASES:
            raise TrialInputError(f"There are already {MAX_CASES} cases.")
        case = LabMusicTrialCase(
            id=case_id,
            trial_group=trial_group,
            sort_order=sort_order,
            title=title,
            guide=guide,
            run_ids=run_ids,
            source_ids=source_ids,
        )
        session.add(case)
    else:
        case.trial_group = trial_group
        case.sort_order = sort_order
        case.title = title
        case.guide = guide
        case.run_ids = run_ids
        case.source_ids = source_ids
        case.updated_at = utcnow()
    await session.commit()
    _logger.info("music trial case saved: %s (%d runs)", case_id, len(run_ids))
    return case


async def set_answer(
    session: AsyncSession, case_id: str, changes: dict[str, Any]
) -> LabMusicTrialCase | None:
    """Sets the answer and/or the note of a case (only the keys in `changes`). None when the
    case does not exist. Commits. Raises TrialInputError.
    """
    case = await session.get(LabMusicTrialCase, case_id)
    if case is None:
        return None
    if "answer" in changes:
        answer = changes["answer"]
        if answer is not None and answer not in ANSWERS:
            raise TrialInputError("The answer is yes, partly or no.")
        case.answer = answer
    if "answer_note" in changes:
        note = changes["answer_note"]
        if note is not None and not isinstance(note, str):
            raise TrialInputError("The note must be text.")
        text = (note or "").strip()
        if len(text) > NOTE_MAX_CHARS:
            raise TrialInputError(f"The note must be at most {NOTE_MAX_CHARS:,} characters.")
        case.answer_note = text or None
    case.updated_at = utcnow()
    await session.commit()
    return case


async def list_cases(session: AsyncSession) -> list[CaseRow]:
    """Every case in screen order, with its runs (in the order the case lists them)."""
    statement = (
        select(LabMusicTrialCase)
        .order_by(LabMusicTrialCase.sort_order, LabMusicTrialCase.id)
        .limit(MAX_CASES)
        .execution_options(populate_existing=True)
    )
    cases = list((await session.execute(statement)).scalars().all())

    run_ids: set[int] = set()
    guide_runs: set[int] = set()
    file_ids: set[int] = set()
    for case in cases:
        run_ids.update(_ids(case.run_ids))
        file_ids.update(_ids(case.source_ids))
        runs, files = _guide_source_ids(case.guide)
        guide_runs.update(runs)
        file_ids.update(files)

    rows = await music_lab.get_runs(session, run_ids)
    source_runs: dict[int, LabMusicRun] = {}
    if guide_runs:
        found = await session.execute(select(LabMusicRun).where(LabMusicRun.id.in_(guide_runs)))
        source_runs = {run.id: run for run in found.scalars()}
    source_files: dict[int, LabMusicSource] = {}
    if file_ids:
        found_files = await session.execute(
            select(LabMusicSource).where(LabMusicSource.id.in_(file_ids))
        )
        source_files = {source.id: source for source in found_files.scalars()}

    return [
        CaseRow(
            case=case,
            runs=[rows[run_id] for run_id in _ids(case.run_ids) if run_id in rows],
            local_outputs=[
                source_files[source_id]
                for source_id in _ids(case.source_ids)
                if source_id in source_files
            ],
            source_runs=source_runs,
            source_files=source_files,
        )
        for case in cases
    ]
