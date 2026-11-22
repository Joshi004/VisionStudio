"""The evidence claims of a continuous explainer: the words of the story that need proof (EVD-002,
`Evidence_layer_implementation_phases.md` EV-3).

Every version is a new `evidence_claim_list` row and a stored row is never changed (the artifact
provenance convention, DATABASE_STRUCTURE.md Section 2.1). `content` is `{next_id, claims}`, and
a claim is `{id, origin, start, end, text, hint, kind_hint, want, speaker, reason, kept}`
(Section 5). `want` is `evidence` or `soundbite` (the owner's choice, SB-001) and `speaker` names
who says a sound bite; a claim stored before they existed reads as `evidence` with no speaker.
The script rules of a sound bite (`services/soundbite_rules`, SB-005) are worked out on every
read by `with_soundbite_rules` and are never stored.

- `origin` `owner`: marked by the owner. `reason` is empty and `kept` is true.
- `origin` `glm`: proposed by the model. `kept` is null until the owner keeps (true) or drops
  (false) it. A dropped proposal stays in the list so that it is not proposed again.

Two ways make a version:

- `start_suggest` queues a job: one model call proposes more claims, and code finds each in the
  story (`services/evidence_claims_writer`). A new proposal list replaces only the proposals the
  owner has not decided on.
- The owner's actions (`add_mark`, `update_claim`, `remove_mark`) each store a `manual` version.

**The marks follow the story on read.** The story is edited through the project's PATCH, which is
not touched here. Whenever the claims are read, each is checked against the story as it is now:
it stays where it is when its words are still there, moves to the nearest place where its words
are, or is flagged `words_changed` when they are gone (or no longer whole words, or now overlap
another claim). `words_changed` is worked out on every read and never stored. The next version
the owner makes stores the positions as they were found.

Marks may cover the same words as a graphic suggestion: the two lists are independent.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceClaimList, Job, Project
from app.db.state_memo import memoized_state
from app.jobs import store
from app.services import explainer, projects, soundbite_rules
from app.services.number_words import numbers_in
from app.services.script_ranges import nearest_occurrence, snap_to_words

JOB_TYPE: Final = "suggest_evidence_claims"
SOURCE_AI: Final = "ai"
SOURCE_MANUAL: Final = "manual"

ORIGIN_OWNER: Final = "owner"
ORIGIN_GLM: Final = "glm"

KINDS: Final = ("number", "quote", "statement", "event", "other")
# What the owner wants for a claim: ordinary evidence, or a clip of the person saying the quote
# (`Sound_bite_implementation_phases.md`, SB-3).
WANT_EVIDENCE: Final = "evidence"
WANT_SOUNDBITE: Final = "soundbite"
WANTS: Final = (WANT_EVIDENCE, WANT_SOUNDBITE)
# Who last chose `want` for a claim: the owner (the controls on the claim card) or the model (when
# it proposed claims, SB-015). The model never changes a claim whose `want` the owner chose. A
# claim nobody chose for has None.
WANT_BY_OWNER: Final = "owner"
WANT_BY_GLM: Final = "glm"
# The longest name an owner may give for who says a sound bite.
SPEAKER_MAX_CHARS: Final = 100
# The longest note an owner may add to a claim.
HINT_MAX_CHARS: Final = 300
# The most claims the owner may mark in one project.
MAX_OWNER_MARKS: Final = 100

_CLAIM_FIELDS: Final = (
    "id",
    "origin",
    "start",
    "end",
    "text",
    "hint",
    "kind_hint",
    "want",
    "speaker",
    "want_by",
    "reason",
    "kept",
)
# What a claim stored before sound bites (or before the model chose them) reads as.
_CLAIM_DEFAULTS: Final = {"want": WANT_EVIDENCE, "speaker": None, "want_by": None}

OFF_MESSAGE: Final = (
    "Evidence is only for an explainer with a continuous voice and evidence switched on, and "
    "this project does not have it."
)
NO_STORY_MESSAGE: Final = "Save the story before marking claims."
BUSY_MESSAGE: Final = "GLM is proposing claims. Wait for it to finish first."
NOT_FOUND_MESSAGE: Final = "There is no such claim."
STORY_CHANGED_MESSAGE: Final = "The story changed while the claims were being proposed. Ask again."
CLAIMS_CHANGED_MESSAGE: Final = "The claims changed while they were being proposed. Ask again."


class EvidenceClaimsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


class ClaimNotFoundError(EvidenceClaimsError):
    """The claim does not exist."""


class BusyError(EvidenceClaimsError):
    """The claims cannot be changed while the model is proposing."""


# --- What applies --------------------------------------------------------------------------


def wanted(project: Project) -> bool:
    """Whether the project has evidence claims at all: a continuous explainer with `evidence`
    on. Turning `evidence` off later keeps the rows and ignores them.
    """
    return (
        explainer.is_explainer(project)
        and project.voice_track == projects.VOICE_CONTINUOUS
        and project.evidence
    )


def blocked_reason(project: Project) -> str | None:
    """Why no claim can be marked or proposed now (or at all for this project), or None."""
    if not wanted(project):
        return OFF_MESSAGE
    if project.script_text is None:
        return NO_STORY_MESSAGE
    return None


def script_sha256(script: str) -> str:
    return hashlib.sha256(script.encode("utf-8")).hexdigest()


# --- Reading claims (pure) -----------------------------------------------------------------


def is_active(claim: dict[str, Any]) -> bool:
    """Whether the claim counts: the owner's marks, and the proposals not dropped."""
    return claim["kept"] is not False


def is_undecided(claim: dict[str, Any]) -> bool:
    """A proposal of the model that the owner has neither kept nor dropped."""
    return claim["origin"] == ORIGIN_GLM and claim["kept"] is None


def _overlaps(start: int, end: int, taken: Sequence[tuple[int, int]]) -> bool:
    return any(start < other_end and end > other_start for other_start, other_end in taken)


def reanchor_claims(script: str | None, claims: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The claims as they stand in `script`, in story order, each with `words_changed`.

    A claim whose words are still at its place stays. Otherwise it moves to the occurrence of its
    words nearest the old place. It is flagged `words_changed` (and keeps its old place) when the
    words are gone, are no longer whole words there, or now overlap a claim that counts. The
    owner's marks are placed first, so a proposal gives way to them.
    """
    found: list[dict[str, Any]] = []
    taken: list[tuple[int, int]] = []
    order = sorted(claims, key=lambda claim: (claim["origin"] != ORIGIN_OWNER, claim["start"]))
    for stored in order:
        claim = {**_CLAIM_DEFAULTS, **stored}
        placed = {key: claim[key] for key in _CLAIM_FIELDS}
        start, end, text = claim["start"], claim["end"], claim["text"]
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
    return sorted(found, key=lambda claim: claim["start"])


def with_soundbite_rules(
    script: str | None, claims: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The claims with the script rules of a sound bite (SB-005), worked out now and never
    stored: `soundbite_block` (why the words cannot be a sound bite, or None) for every claim
    whose words are in the story, and `soundbite_warnings` and `soundbite_hints` for the claims
    that are sound bites. `claims` are as `reanchor_claims` gives them.
    """
    ruled: list[dict[str, Any]] = []
    for claim in claims:
        block: str | None = None
        warnings: list[dict[str, Any]] = []
        hints: list[str] = []
        if script is not None and not claim["words_changed"]:
            result = soundbite_rules.check(script, claim)
            block = result.block
            if is_soundbite(claim):
                warnings, hints = result.warnings, result.hints
        ruled.append(
            {
                **claim,
                "soundbite_block": block,
                "soundbite_warnings": warnings,
                "soundbite_hints": hints,
            }
        )
    return ruled


def counting(claims: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The claims that count and sit in the story (not dropped, words not changed)."""
    return [claim for claim in claims if is_active(claim) and not claim.get("words_changed")]


def default_kind(text: str) -> str:
    """The kind an owner's mark gets when none is chosen."""
    return "number" if numbers_in(text) else "statement"


def _clean_hint(hint: str) -> str:
    """The owner's note as one line of plain text."""
    cleaned = " ".join(hint.split())
    if len(cleaned) > HINT_MAX_CHARS:
        raise EvidenceClaimsError(f"A note can be at most {HINT_MAX_CHARS} characters.")
    return cleaned


def is_soundbite(claim: dict[str, Any]) -> bool:
    """Whether the owner chose a sound bite for the claim."""
    return claim.get("want", WANT_EVIDENCE) == WANT_SOUNDBITE


def _clean_speaker(speaker: str) -> str | None:
    """The speaker's name as one line of plain text, or None when it is empty."""
    cleaned = " ".join(speaker.split())
    if len(cleaned) > SPEAKER_MAX_CHARS:
        raise EvidenceClaimsError(
            f"A speaker's name can be at most {SPEAKER_MAX_CHARS} characters."
        )
    return cleaned or None


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise EvidenceClaimsError(f"The kind must be one of: {', '.join(KINDS)}.")
    return kind


# --- Versions ------------------------------------------------------------------------------


async def latest(session: AsyncSession, project_id: int) -> EvidenceClaimList | None:
    """The project's newest version, or None when it has none."""
    statement = (
        select(EvidenceClaimList)
        .where(EvidenceClaimList.project_id == project_id)
        .order_by(EvidenceClaimList.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def has_ai_version(session: AsyncSession, project_id: int) -> bool:
    """Whether the model has been asked, and answered, for this project."""
    statement = (
        select(EvidenceClaimList.id)
        .where(EvidenceClaimList.project_id == project_id, EvidenceClaimList.source == SOURCE_AI)
        .limit(1)
    )
    return (await session.execute(statement)).first() is not None


def _stored_claims(row: EvidenceClaimList | None) -> list[dict[str, Any]]:
    """The claims of a version as stored, or none."""
    if row is None or not isinstance(row.content, dict):
        return []
    claims = row.content.get("claims")
    return [dict(claim) for claim in claims] if isinstance(claims, list) else []


def _next_id(row: EvidenceClaimList | None) -> int:
    if row is None or not isinstance(row.content, dict):
        return 1
    value = row.content.get("next_id")
    return value if isinstance(value, int) and value >= 1 else 1


def _content(claims: Sequence[dict[str, Any]], next_id: int) -> dict[str, Any]:
    """What is stored: the claims in story order, without anything worked out on read."""
    stored = [{key: claim[key] for key in _CLAIM_FIELDS} for claim in claims]
    return {"next_id": next_id, "claims": sorted(stored, key=lambda claim: claim["start"])}


def _inputs(script: str, based_on: EvidenceClaimList | None) -> dict[str, Any]:
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
    based_on: EvidenceClaimList | None,
    claims: Sequence[dict[str, Any]],
    next_id: int,
) -> EvidenceClaimList:
    assert project.script_text is not None
    statement = select(func.max(EvidenceClaimList.version)).where(
        EvidenceClaimList.project_id == project.id
    )
    highest = (await session.execute(statement)).scalar_one_or_none()
    row = EvidenceClaimList(
        project_id=project.id,
        version=(highest or 0) + 1,
        source=source,
        job_id=job_id,
        inputs=_inputs(project.script_text, based_on),
        content=_content(claims, next_id),
    )
    session.add(row)
    await session.flush()
    return row


# --- The owner's actions -------------------------------------------------------------------


@dataclass(frozen=True)
class _Editing:
    row: EvidenceClaimList | None
    claims: list[dict[str, Any]]
    next_id: int


async def _load_for_edit(session: AsyncSession, project: Project) -> _Editing:
    """The newest version with its claims as they stand in the story now. Raises when claims
    cannot be changed: not applicable, no story, or the model is proposing.
    """
    reason = blocked_reason(project)
    if reason is not None:
        raise EvidenceClaimsError(reason)
    active = await store.latest_job(session, project.id, JOB_TYPE)
    if active is not None and active.status in store.ACTIVE_STATUSES:
        raise BusyError(BUSY_MESSAGE)
    row = await latest(session, project.id)
    return _Editing(
        row=row,
        claims=reanchor_claims(project.script_text, _stored_claims(row)),
        next_id=_next_id(row),
    )


async def _commit_manual(
    session: AsyncSession, project: Project, editing: _Editing, claims: list[dict[str, Any]]
) -> None:
    await _add_version(
        session,
        project,
        source=SOURCE_MANUAL,
        job_id=None,
        based_on=editing.row,
        claims=claims,
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
    hint: str = "",
    kind_hint: str | None = None,
) -> None:
    """Stores a new version with the words `start` to `end` marked as a claim (`source` is
    `manual`), and commits. The range is moved out to whole words and must hold `text`, which
    catches a story that changed under the owner's feet. A proposal of the model that covers the
    same words is dropped: the owner's mark wins. Raises EvidenceClaimsError.
    """
    editing = await _load_for_edit(session, project)
    script = project.script_text
    assert script is not None
    if not 0 <= start < end <= len(script):
        raise EvidenceClaimsError("The marked words are outside the story.")
    if script[start:end] != text:
        raise EvidenceClaimsError(
            "The marked words do not match the story. The story may have changed: reload it "
            "and mark the words again."
        )
    start, end = snap_to_words(script, start, end)
    if start == end:
        raise EvidenceClaimsError("Select some words to mark.")
    owner_marks = [claim for claim in editing.claims if claim["origin"] == ORIGIN_OWNER]
    if len(owner_marks) >= MAX_OWNER_MARKS:
        raise EvidenceClaimsError(f"There can be at most {MAX_OWNER_MARKS} marked claims.")
    if _overlaps(start, end, [(c["start"], c["end"]) for c in counting(owner_marks)]):
        raise EvidenceClaimsError("Those words overlap a claim you already marked.")
    kind = _check_kind(kind_hint) if kind_hint is not None else default_kind(script[start:end])
    claims = []
    for claim in editing.claims:
        overlapping = (
            claim["origin"] == ORIGIN_GLM
            and is_active(claim)
            and not claim["words_changed"]
            and start < claim["end"]
            and end > claim["start"]
        )
        claims.append({**claim, "kept": False} if overlapping else claim)
    claims.append(
        {
            "id": f"c{editing.next_id}",
            "origin": ORIGIN_OWNER,
            "start": start,
            "end": end,
            "text": script[start:end],
            "hint": _clean_hint(hint),
            "kind_hint": kind,
            "want": WANT_EVIDENCE,
            "speaker": None,
            "want_by": None,
            "reason": "",
            "kept": True,
        }
    )
    await _commit_manual(
        session,
        project,
        _Editing(editing.row, editing.claims, editing.next_id + 1),
        claims,
    )


def _apply_want(
    claim: dict[str, Any], changed: dict[str, Any], want: str | None, speaker: str | None
) -> None:
    """Sets `want` and `speaker` on `changed` by the rules of a sound bite. Raises
    EvidenceClaimsError.
    """
    if want is not None and want not in WANTS:
        raise EvidenceClaimsError(f"What is wanted must be one of: {', '.join(WANTS)}.")
    new_want = want if want is not None else claim["want"]
    new_speaker = _clean_speaker(speaker) if speaker is not None else claim["speaker"]
    if new_want == WANT_EVIDENCE:
        if speaker is not None and new_speaker is not None:
            raise EvidenceClaimsError("Only a sound bite has a speaker. Choose sound bite first.")
        changed["want"], changed["speaker"] = WANT_EVIDENCE, None
        if claim["want"] != WANT_EVIDENCE:
            changed["want_by"] = WANT_BY_OWNER
        return
    if changed["kept"] is False or claim["words_changed"]:
        raise EvidenceClaimsError(
            "A sound bite needs a claim that is kept and whose words are still in the story."
        )
    problem = soundbite_rules.quote_problem(claim["text"])
    if problem is not None:
        raise EvidenceClaimsError(problem)
    if new_speaker is None:
        raise EvidenceClaimsError("Say who speaks the quote before choosing a sound bite.")
    changed["want"], changed["speaker"] = WANT_SOUNDBITE, new_speaker
    if claim["want"] != WANT_SOUNDBITE or claim["speaker"] != new_speaker:
        changed["want_by"] = WANT_BY_OWNER


async def update_claim(
    session: AsyncSession,
    project: Project,
    claim_id: str,
    *,
    hint: str | None = None,
    kind_hint: str | None = None,
    kept: bool | None = None,
    want: str | None = None,
    speaker: str | None = None,
) -> None:
    """Changes a claim's note, kind, `want` and `speaker` (SB-001), or (for a proposal of the
    model) whether it is kept, as a new `manual` version, and commits. A sound bite needs a
    speaker, a claim that counts and words that are whole sentences in quotation marks
    (`soundbite_rules.quote_problem`). Choosing `evidence` clears the speaker, and a speaker
    for a claim that is not a sound bite is refused. A value left as None is not changed, and
    nothing is stored when nothing changes. Raises EvidenceClaimsError (ClaimNotFoundError for an
    unknown claim).
    """
    editing = await _load_for_edit(session, project)
    claim = next((c for c in editing.claims if c["id"] == claim_id), None)
    if claim is None:
        raise ClaimNotFoundError(NOT_FOUND_MESSAGE)
    changed = dict(claim)
    if hint is not None:
        changed["hint"] = _clean_hint(hint)
    if kind_hint is not None:
        changed["kind_hint"] = _check_kind(kind_hint)
    if kept is not None and kept != claim["kept"]:
        if claim["origin"] == ORIGIN_OWNER:
            raise EvidenceClaimsError("Your own marks are always kept. Remove the mark instead.")
        if kept:
            if claim["words_changed"]:
                raise EvidenceClaimsError(
                    "The words of this claim are no longer in the story, so it cannot be kept."
                )
            others = [(c["start"], c["end"]) for c in counting(editing.claims) if c is not claim]
            if _overlaps(claim["start"], claim["end"], others):
                raise EvidenceClaimsError("Those words overlap another claim.")
        changed["kept"] = kept
    if want is not None or speaker is not None:
        _apply_want(claim, changed, want, speaker)
    if all(changed[key] == claim[key] for key in _CLAIM_FIELDS):
        return
    claims = [changed if c["id"] == claim_id else c for c in editing.claims]
    await _commit_manual(session, project, editing, claims)


async def remove_mark(session: AsyncSession, project: Project, claim_id: str) -> None:
    """Removes one of the owner's marks, as a new `manual` version, and commits. A proposal of
    the model is dropped (`update_claim`, `kept` false), never removed, so that it is not
    proposed again. Raises EvidenceClaimsError.
    """
    editing = await _load_for_edit(session, project)
    claim = next((c for c in editing.claims if c["id"] == claim_id), None)
    if claim is None:
        raise ClaimNotFoundError(NOT_FOUND_MESSAGE)
    if claim["origin"] != ORIGIN_OWNER:
        raise EvidenceClaimsError("Drop a proposal of GLM instead of removing it.")
    await _commit_manual(
        session, project, editing, [c for c in editing.claims if c["id"] != claim_id]
    )


# --- The model's proposals -----------------------------------------------------------------


async def start_suggest(session: AsyncSession, project: Project) -> Job:
    """Queues the job that asks the model for more claims, from a copy of what it needs taken
    now: the story, its hash, the claims as they stand and the version they are. If one is
    already waiting or running, that job is returned. Raises EvidenceClaimsError.
    """
    reason = blocked_reason(project)
    if reason is not None:
        raise EvidenceClaimsError(reason)
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
            "claims": reanchor_claims(project.script_text, _stored_claims(row)),
            "based_on_version": row.version if row is not None else None,
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
    soundbites: Sequence[dict[str, str]] = (),
) -> tuple[EvidenceClaimList, list[dict[str, str]]]:
    """Adds the next version with the model's proposals (`source` is `ai`). Flushes but does not
    commit: the job commits it together with finishing itself. Answers the version and the sound
    bite choices of the model that were not applied, as `[{claim, why}]`.

    `proposals` are `{start, end, text, kind_hint, reason}` (and `soundbite`, `speaker` when the
    model chose a sound bite), already found in the story as it was when the job was queued.
    `soundbites` are the model's choices among the claims already marked, `{id, speaker}`. The
    claims the owner has decided on stay; the proposals the owner has not decided on are replaced
    (one with the same words and place keeps its id). Raises EvidenceClaimsError when the story
    or the claims are no longer what the job started from.

    **The model's sound bite choices** (SB-015) are applied only when the code rules allow:
    a speaker is named and the words pass `soundbite_rules.quote_problem`; for a claim already
    marked, also that it counts, is still in the story, is ordinary evidence now and that the
    owner never chose its `want`. A choice that is applied is stored with `want_by` `glm`.
    """
    script = project.script_text
    if script is None or script_sha256(script) != script_hash:
        raise EvidenceClaimsError(STORY_CHANGED_MESSAGE)
    row = await latest(session, project.id)
    if (row.version if row is not None else None) != based_on_version:
        raise EvidenceClaimsError(CLAIMS_CHANGED_MESSAGE)
    claims = reanchor_claims(script, _stored_claims(row))
    old_ids = {
        (claim["start"], claim["end"], claim["text"]): claim["id"]
        for claim in claims
        if is_undecided(claim)
    }
    next_id = _next_id(row)
    stay = [claim for claim in claims if not is_undecided(claim)]
    not_applied: list[dict[str, str]] = []
    marked_by_id = {claim["id"]: claim for claim in stay}
    for choice in soundbites:
        claim = marked_by_id.get(choice["id"])
        label = claim["text"][:80] if claim is not None else choice["id"]
        why = _marked_refusal(claim, choice["speaker"])
        if why is not None:
            not_applied.append({"claim": label, "why": why})
            continue
        assert claim is not None
        claim["want"], claim["speaker"], claim["want_by"] = (
            WANT_SOUNDBITE,
            choice["speaker"],
            WANT_BY_GLM,
        )
    for proposal in proposals:
        key = (proposal["start"], proposal["end"], proposal["text"])
        claim_id = old_ids.get(key)
        if claim_id is None:
            claim_id = f"c{next_id}"
            next_id += 1
        want, speaker, want_by = WANT_EVIDENCE, None, None
        if proposal.get("soundbite"):
            why = _soundbite_refusal(proposal["text"], proposal.get("speaker"))
            if why is None:
                want, speaker, want_by = WANT_SOUNDBITE, proposal["speaker"], WANT_BY_GLM
            else:
                not_applied.append({"claim": proposal["text"][:80], "why": why})
        stay.append(
            {
                "id": claim_id,
                "origin": ORIGIN_GLM,
                "start": proposal["start"],
                "end": proposal["end"],
                "text": proposal["text"],
                "hint": "",
                "kind_hint": proposal["kind_hint"],
                "want": want,
                "speaker": speaker,
                "want_by": want_by,
                "reason": proposal["reason"],
                "kept": None,
            }
        )
    version = await _add_version(
        session,
        project,
        source=SOURCE_AI,
        job_id=job_id,
        based_on=row,
        claims=stay,
        next_id=next_id,
    )
    return version, not_applied


def _soundbite_refusal(text: str, speaker: str | None) -> str | None:
    """Why the model may not make words a sound bite, or None when it may: the words must be
    whole sentences in quotation marks and a speaker must be named.
    """
    if not speaker:
        return "no speaker was named"
    return soundbite_rules.quote_problem(text)


def _marked_refusal(claim: dict[str, Any] | None, speaker: str) -> str | None:
    """Why the model may not make an already marked claim a sound bite, or None."""
    if claim is None:
        return "no such marked claim"
    if not is_active(claim) or claim["words_changed"]:
        return "the claim is dropped or its words are no longer in the story"
    if claim["want_by"] == WANT_BY_OWNER:
        return "the owner chose what this claim wants"
    if is_soundbite(claim):
        return "it is a sound bite already"
    return _soundbite_refusal(claim["text"], speaker)


# --- Reading the state ---------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimsState:
    """What the story panel shows."""

    # The newest version, or None when there is none (or the project has no evidence).
    latest: EvidenceClaimList | None
    # The claims as they stand in the story now, each with `words_changed`.
    claims: list[dict[str, Any]]
    # The newest `suggest_evidence_claims` job, whatever its status.
    job: Job | None
    # Why no claim can be marked or proposed now (or at all for this project), or None.
    blocked_reason: str | None
    # Whether the project has evidence claims at all.
    wanted: bool
    # Whether the model has been asked, and answered, for this project.
    has_ai_version: bool


@memoized_state
async def state(session: AsyncSession, project: Project) -> ClaimsState:
    """The project's claims with where they stand. Worked out on every read. A project without
    evidence reads nothing from the tables (EVD-001).
    """
    if not wanted(project):
        return ClaimsState(
            latest=None,
            claims=[],
            job=None,
            blocked_reason=OFF_MESSAGE,
            wanted=False,
            has_ai_version=False,
        )
    row = await latest(session, project.id)
    return ClaimsState(
        latest=row,
        claims=with_soundbite_rules(
            project.script_text, reanchor_claims(project.script_text, _stored_claims(row))
        ),
        job=await store.latest_job(session, project.id, JOB_TYPE),
        blocked_reason=blocked_reason(project),
        wanted=True,
        has_ai_version=await has_ai_version(session, project.id),
    )
