"""The footage marks of a continuous explainer: the words of the story that real footage is shown
over (FTG-002, `Footage_broll_implementation_phases.md` FT-4).

Every version is a new `footage_mark_list` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is `{next_id, marks}`, and a
mark is `{id, origin, start, end, text, note, kind_hint, reason, kept}` (§4.4 of the phases
document).

- `origin` `owner`: marked by the owner. `reason` is empty and `kept` is true.
- `origin` `glm`: proposed by the model. `kept` is null until the owner keeps (true) or drops
  (false) it. A dropped proposal stays in the list so that it is not proposed again.

Two ways make a version:

- `start_suggest` queues a job: one model call proposes more marks, and code finds each in the
  story (`services/footage_marks_writer`). A new proposal list replaces only the proposals the
  owner has not decided on.
- The owner's actions (`add_mark`, `update_mark`, `remove_mark`) each store a `manual` version.

**The marks follow the story on read.** Whenever the marks are read, each is checked against the
story as it is now: it stays where it is when its words are still there, moves to the nearest
place where its words are, or is flagged `words_changed` when they are gone (or no longer whole
words, or now overlap another footage mark). `words_changed` is worked out on every read and
never stored.

Footage marks never overlap each other. They may cover the same words as a claim, a graphic
suggestion or a sound bite: the lists are independent (FT-4).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FootageMarkList, Job, Project
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import evidence_claims, explainer, projects
from app.services.script_ranges import nearest_occurrence, snap_to_words

JOB_TYPE: Final = "suggest_footage_marks"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

ORIGIN_OWNER: Final = "owner"
ORIGIN_GLM: Final = "glm"

KIND_ANY: Final = "any"
KINDS: Final = (KIND_ANY, "video", "photo", "page")
# The longest note an owner may add to a mark (§4.4).
NOTE_MAX_CHARS: Final = 300
# The most marks the owner may make in one project.
MAX_OWNER_MARKS: Final = 100

_MARK_FIELDS: Final = (
    "id",
    "origin",
    "start",
    "end",
    "text",
    "note",
    "kind_hint",
    "reason",
    "kept",
)

OFF_MESSAGE: Final = (
    "Footage is only for an explainer with a continuous voice and footage switched on, and "
    "this project does not have it."
)
NO_STORY_MESSAGE: Final = "Save the story before marking footage."
BUSY_MESSAGE: Final = "GLM is proposing footage. Wait for it to finish first."
NOT_FOUND_MESSAGE: Final = "There is no such footage mark."
STORY_CHANGED_MESSAGE: Final = "The story changed while the footage was being proposed. Ask again."
MARKS_CHANGED_MESSAGE: Final = (
    "The footage marks changed while they were being proposed. Ask again."
)


class FootageMarksError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class MarkNotFoundError(FootageMarksError):
    """The mark does not exist."""


class BusyError(FootageMarksError):
    """The marks cannot be changed while the model is proposing."""


# --- What applies --------------------------------------------------------------------------


def wanted(project: Project) -> bool:
    """Whether the project has footage marks at all: a continuous explainer with `footage` on.
    Turning `footage` off later keeps the rows and ignores them.
    """
    return (
        explainer.is_explainer(project)
        and project.voice_track == projects.VOICE_CONTINUOUS
        and project.footage
    )


def blocked_reason(project: Project) -> str | None:
    """Why no footage can be marked or proposed now (or at all for this project), or None."""
    if not wanted(project):
        return OFF_MESSAGE
    if project.script_text is None:
        return NO_STORY_MESSAGE
    return None


def script_sha256(script: str) -> str:
    return hashlib.sha256(script.encode("utf-8")).hexdigest()


# --- Reading marks (pure) ------------------------------------------------------------------


def is_active(mark: dict[str, Any]) -> bool:
    """Whether the mark counts: the owner's marks, and the proposals not dropped."""
    return mark["kept"] is not False


def is_undecided(mark: dict[str, Any]) -> bool:
    """A proposal of the model that the owner has neither kept nor dropped."""
    return mark["origin"] == ORIGIN_GLM and mark["kept"] is None


def _overlaps(start: int, end: int, taken: Sequence[tuple[int, int]]) -> bool:
    return any(start < other_end and end > other_start for other_start, other_end in taken)


def reanchor_marks(script: str | None, marks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The marks as they stand in `script`, in story order, each with `words_changed`.

    A mark whose words are still at its place stays. Otherwise it moves to the occurrence of its
    words nearest the old place. It is flagged `words_changed` (and keeps its old place) when the
    words are gone, are no longer whole words there, or now overlap a mark that counts. The
    owner's marks are placed first, so a proposal gives way to them.
    """
    found: list[dict[str, Any]] = []
    taken: list[tuple[int, int]] = []
    order = sorted(marks, key=lambda mark: (mark["origin"] != ORIGIN_OWNER, mark["start"]))
    for stored in order:
        placed = {key: stored[key] for key in _MARK_FIELDS}
        start, end, text = placed["start"], placed["end"], placed["text"]
        ok = False
        if script:
            if script[start:end] != text:
                moved = nearest_occurrence(script, text, start)
                if moved is not None:
                    start, end = moved, moved + len(text)
            ok = script[start:end] == text and snap_to_words(script, start, end) == (start, end)
        if ok:
            placed["start"], placed["end"] = start, end
            if is_active(placed):
                if _overlaps(start, end, taken):
                    ok = False
                else:
                    taken.append((start, end))
        placed["words_changed"] = not ok
        found.append(placed)
    return sorted(found, key=lambda mark: mark["start"])


def counting(marks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The marks that count and sit in the story (not dropped, words not changed)."""
    return [mark for mark in marks if is_active(mark) and not mark.get("words_changed")]


def _clean_note(note: str) -> str:
    """The owner's note as one line of plain text."""
    cleaned = " ".join(note.split())
    if len(cleaned) > NOTE_MAX_CHARS:
        raise FootageMarksError(f"A note can be at most {NOTE_MAX_CHARS} characters.")
    return cleaned


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise FootageMarksError(f"The kind must be one of: {', '.join(KINDS)}.")
    return kind


# --- Versions ------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> FootageMarkList | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(FootageMarkList)
        .where(FootageMarkList.project_id == project_id)
        .order_by(FootageMarkList.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def has_ai_version(session: AsyncSession, project_id: int) -> bool:
    """Whether the model has been asked, and answered, for this project."""
    statement = (
        select(FootageMarkList.id)
        .where(FootageMarkList.project_id == project_id, FootageMarkList.source == SOURCE_AI)
        .limit(1)
    )
    return (await session.execute(statement)).first() is not None


def _stored_marks(row: FootageMarkList | None) -> list[dict[str, Any]]:
    """The marks of a version as stored, or none."""
    if row is None or not isinstance(row.content, dict):
        return []
    marks = row.content.get("marks")
    return [dict(mark) for mark in marks] if isinstance(marks, list) else []


def _next_id(row: FootageMarkList | None) -> int:
    if row is None or not isinstance(row.content, dict):
        return 1
    value = row.content.get("next_id")
    return value if isinstance(value, int) and value >= 1 else 1


def _content(marks: Sequence[dict[str, Any]], next_id: int) -> dict[str, Any]:
    """What is stored: the marks in story order, without anything worked out on read."""
    stored = [{key: mark[key] for key in _MARK_FIELDS} for mark in marks]
    return {"next_id": next_id, "marks": sorted(stored, key=lambda mark: mark["start"])}


def _inputs(script: str, based_on: FootageMarkList | None) -> dict[str, Any]:
    return {
        "script_sha256": script_sha256(script),
        "based_on_version": based_on.version if based_on is not None else None,
    }


async def _add_version(
    session: AsyncSession,
    project: Project,
    *,
    source: str,
    job_id: int | None,
    based_on: FootageMarkList | None,
    marks: Sequence[dict[str, Any]],
    next_id: int,
) -> FootageMarkList:
    assert project.script_text is not None
    statement = select(func.max(FootageMarkList.version)).where(
        FootageMarkList.project_id == project.id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = FootageMarkList(
        project_id=project.id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        inputs=_inputs(project.script_text, based_on),
        content=_content(marks, next_id),
    )
    session.add(row)
    await session.flush()
    return row


# --- The owner's actions -------------------------------------------------------------------


@dataclass(frozen=True)
class _Editing:
    row: FootageMarkList | None
    marks: list[dict[str, Any]]
    next_id: int


async def _load_for_edit(session: AsyncSession, project: Project) -> _Editing:
    """The newest version with its marks as they stand in the story now. Raises when marks
    cannot be changed: not applicable, no story, or the model is proposing.
    """
    reason = blocked_reason(project)
    if reason is not None:
        raise FootageMarksError(reason)
    active = await store.latest_job(session, project.id, JOB_TYPE)
    if active is not None and active.status in store.ACTIVE_STATUSES:
        raise BusyError(BUSY_MESSAGE)
    row = await latest(session, project.id)
    return _Editing(
        row=row,
        marks=reanchor_marks(project.script_text, _stored_marks(row)),
        next_id=_next_id(row),
    )


async def _commit_manual(
    session: AsyncSession, project: Project, editing: _Editing, marks: list[dict[str, Any]]
) -> None:
    await _add_version(
        session,
        project,
        source=SOURCE_MANUAL,
        job_id=None,
        based_on=editing.row,
        marks=marks,
        next_id=editing.next_id,
    )
    await session.commit()


async def add_mark(
    session: AsyncSession,
    project: Project,
    *,
    start: int,
    end: int,
    text: str,
    note: str = "",
    kind_hint: str | None = None,
) -> None:
    """Stores a new version with the words `start` to `end` marked as footage (`source` is
    `manual`), and commits. The range is moved out to whole words and must hold `text`, which
    catches a story that changed under the owner's feet. A proposal of the model that covers the
    same words is dropped: the owner's mark wins. Raises FootageMarksError.
    """
    editing = await _load_for_edit(session, project)
    script = project.script_text
    assert script is not None
    if not 0 <= start < end <= len(script):
        raise FootageMarksError("The marked words are outside the story.")
    if script[start:end] != text:
        raise FootageMarksError(
            "The marked words do not match the story. The story may have changed: reload it "
            "and mark the words again."
        )
    start, end = snap_to_words(script, start, end)
    if start == end:
        raise FootageMarksError("Select some words to mark.")
    owner_marks = [mark for mark in editing.marks if mark["origin"] == ORIGIN_OWNER]
    if len(owner_marks) >= MAX_OWNER_MARKS:
        raise FootageMarksError(f"There can be at most {MAX_OWNER_MARKS} footage marks.")
    if _overlaps(start, end, [(m["start"], m["end"]) for m in counting(owner_marks)]):
        raise FootageMarksError("Those words overlap footage you already marked.")
    kind = _check_kind(kind_hint) if kind_hint is not None else KIND_ANY
    cleaned_note = _clean_note(note)
    marks = []
    for mark in editing.marks:
        overlapping = (
            mark["origin"] == ORIGIN_GLM
            and is_active(mark)
            and not mark["words_changed"]
            and start < mark["end"]
            and end > mark["start"]
        )
        marks.append({**mark, "kept": False} if overlapping else mark)
    marks.append(
        {
            "id": f"f{editing.next_id}",
            "origin": ORIGIN_OWNER,
            "start": start,
            "end": end,
            "text": script[start:end],
            "note": cleaned_note,
            "kind_hint": kind,
            "reason": "",
            "kept": True,
        }
    )
    await _commit_manual(
        session, project, _Editing(editing.row, editing.marks, editing.next_id + 1), marks
    )


async def update_mark(
    session: AsyncSession,
    project: Project,
    mark_id: str,
    *,
    note: str | None = None,
    kind_hint: str | None = None,
    kept: bool | None = None,
) -> None:
    """Changes a mark's note and kind, or (for a proposal of the model) whether it is kept, as a
    new `manual` version, and commits. A value left as None is not changed, and nothing is
    stored when nothing changes. Raises FootageMarksError (MarkNotFoundError for an unknown
    mark).
    """
    editing = await _load_for_edit(session, project)
    mark = next((m for m in editing.marks if m["id"] == mark_id), None)
    if mark is None:
        raise MarkNotFoundError(NOT_FOUND_MESSAGE)
    changed = dict(mark)
    if note is not None:
        changed["note"] = _clean_note(note)
    if kind_hint is not None:
        changed["kind_hint"] = _check_kind(kind_hint)
    if kept is not None and kept != mark["kept"]:
        if mark["origin"] == ORIGIN_OWNER:
            raise FootageMarksError("Your own marks are always kept. Remove the mark instead.")
        if kept:
            if mark["words_changed"]:
                raise FootageMarksError(
                    "The words of this mark are no longer in the story, so it cannot be kept."
                )
            others = [(m["start"], m["end"]) for m in counting(editing.marks) if m is not mark]
            if _overlaps(mark["start"], mark["end"], others):
                raise FootageMarksError("Those words overlap other footage.")
        changed["kept"] = kept
    if all(changed[key] == mark[key] for key in _MARK_FIELDS):
        return
    marks = [changed if m["id"] == mark_id else m for m in editing.marks]
    await _commit_manual(session, project, editing, marks)


async def remove_mark(session: AsyncSession, project: Project, mark_id: str) -> None:
    """Removes one of the owner's marks, as a new `manual` version, and commits. A proposal of
    the model is dropped (`update_mark`, `kept` false), never removed, so that it is not
    proposed again. Raises FootageMarksError.
    """
    editing = await _load_for_edit(session, project)
    mark = next((m for m in editing.marks if m["id"] == mark_id), None)
    if mark is None:
        raise MarkNotFoundError(NOT_FOUND_MESSAGE)
    if mark["origin"] != ORIGIN_OWNER:
        raise FootageMarksError("Drop a proposal of GLM instead of removing it.")
    await _commit_manual(
        session, project, editing, [m for m in editing.marks if m["id"] != mark_id]
    )


# --- The model's proposals -----------------------------------------------------------------


async def _context(session: AsyncSession, project: Project) -> dict[str, Any]:
    """What GLM reads beside the story, so it keeps footage off words that already have proof or
    a picture: the claims that count, the sound bite quotes (`{start, end, text}`) and the texts
    of the graphic suggestions. Plain data, copied now.
    """
    claims: list[str] = []
    soundbites: list[dict[str, Any]] = []
    if evidence_claims.wanted(project):
        state = await evidence_claims.state(session, project)
        for claim in evidence_claims.counting(state.claims):
            claims.append(claim["text"])
            if evidence_claims.is_soundbite(claim):
                soundbites.append(
                    {"start": claim["start"], "end": claim["end"], "text": claim["text"]}
                )
    graphics: list[str] = []
    if project.graphics and isinstance(project.graphic_suggestions, list):
        graphics = [str(entry["text"]) for entry in project.graphic_suggestions]
    return {"claims": claims, "soundbites": soundbites, "graphics": graphics}


async def start_suggest(session: AsyncSession, project: Project) -> Job:
    """Queues the job that asks the model for more footage marks, from a copy of what it needs
    taken now: the story, its hash, the marks as they stand, the version they are, and the
    context. If one is already waiting or running, that job is returned. Raises
    FootageMarksError.
    """
    reason = blocked_reason(project)
    if reason is not None:
        raise FootageMarksError(reason)
    assert project.script_text is not None
    row = await latest(session, project.id)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input={
            "script": project.script_text,
            "script_sha256": script_sha256(project.script_text),
            "marks": reanchor_marks(project.script_text, _stored_marks(row)),
            "based_on_version": row.version if row is not None else None,
            "context": await _context(session, project),
        },
    )
    return job


async def save_ai_version(
    session: AsyncSession,
    project: Project,
    *,
    job_id: int,
    based_on_version: int | None,
    script_hash: str,
    proposals: Sequence[dict[str, Any]],
) -> FootageMarkList:
    """Adds the next version with the model's proposals (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself.

    `proposals` are `{start, end, text, note, kind_hint, reason}`, already found in the story as
    it was when the job was queued. The marks the owner has decided on stay; the proposals the
    owner has not decided on are replaced (one with the same words and place keeps its id).
    Raises FootageMarksError when the story or the marks are no longer what the job started
    from.
    """
    script = project.script_text
    if script is None or script_sha256(script) != script_hash:
        raise FootageMarksError(STORY_CHANGED_MESSAGE)
    row = await latest(session, project.id)
    if (row.version if row is not None else None) != based_on_version:
        raise FootageMarksError(MARKS_CHANGED_MESSAGE)
    marks = reanchor_marks(script, _stored_marks(row))
    old_ids = {
        (mark["start"], mark["end"], mark["text"]): mark["id"]
        for mark in marks
        if is_undecided(mark)
    }
    next_id = _next_id(row)
    stay = [mark for mark in marks if not is_undecided(mark)]
    for proposal in proposals:
        key = (proposal["start"], proposal["end"], proposal["text"])
        mark_id = old_ids.get(key)
        if mark_id is None:
            mark_id = f"f{next_id}"
            next_id += 1
        stay.append(
            {
                "id": mark_id,
                "origin": ORIGIN_GLM,
                "start": proposal["start"],
                "end": proposal["end"],
                "text": proposal["text"],
                "note": proposal["note"],
                "kind_hint": proposal["kind_hint"],
                "reason": proposal["reason"],
                "kept": None,
            }
        )
    return await _add_version(
        session,
        project,
        source=SOURCE_AI,
        job_id=job_id,
        based_on=row,
        marks=stay,
        next_id=next_id,
    )


# --- Reading the state ---------------------------------------------------------------------


@dataclass(frozen=True)
class MarksState:
    """What the story panel shows."""

    # The newest version, or None when there is none (or the project has no footage).
    latest: FootageMarkList | None
    # The marks as they stand in the story now, each with `words_changed`.
    marks: list[dict[str, Any]]
    # The newest `suggest_footage_marks` job, whatever its status.
    job: Job | None
    # Why no footage can be marked or proposed now (or at all for this project), or None.
    blocked_reason: str | None
    # Whether the project has footage marks at all.
    wanted: bool
    # Whether the model has been asked, and answered, for this project.
    has_ai_version: bool


@memoized_state
async def state(session: AsyncSession, project: Project) -> MarksState:
    """The project's footage marks with where they stand. Worked out on every read. A project
    without footage reads nothing from the tables.
    """
    if not wanted(project):
        return MarksState(
            latest=None,
            marks=[],
            job=None,
            blocked_reason=OFF_MESSAGE,
            wanted=False,
            has_ai_version=False,
        )
    row = await latest(session, project.id)
    return MarksState(
        latest=row,
        marks=reanchor_marks(project.script_text, _stored_marks(row)),
        job=await store.latest_job(session, project.id, JOB_TYPE),
        blocked_reason=blocked_reason(project),
        wanted=True,
        has_ai_version=await has_ai_version(session, project.id),
    )
