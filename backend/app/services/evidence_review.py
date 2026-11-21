"""The owner's review of an imported research round (EVD-007,
`Evidence_layer_implementation_phases.md` EV-8).

The owner decides, for every claim of the newest round:

- an `accepted` or `rejected` verdict for each **usable** piece of evidence of the newest import;
- which accepted pieces are **shown** on video, in what order;
- or `no_proof_on_screen`: the claim stays in the script with no evidence shot.

Every change is stored as a new `evidence_review` version (nothing is changed in place), written
for the newest import (`inputs.import_id`). A decision names a piece by its `item_key`, so an
import of the same round that did not change a piece keeps the decision for it.

**A claim is decided** when it has no usable piece and `no_proof_on_screen` is set, or when every
usable piece has a verdict and either some piece is shown or `no_proof_on_screen` is set. "Review
done" is refused until every claim of the round is decided, and stores a version with `done` true:
that is what `evidence_rounds.round_status` reads as `reviewed`, so the `evidence` step needs
nothing else. Any later change stores a version with `done` false, so the round reads `imported`
again until the owner presses "Review done" again.

**Decisions are read through `effective_decision`**: a verdict for a piece that is not a usable
piece of the claim in the newest import is dropped, and so is a place in `shown` of a piece that
is no longer accepted. A claim whose piece changed in a re-import is then undecided again.

No file is ever deleted here (EVD-006: stored files are shared between items and imports).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceItem, EvidenceReview, Job, Project
from app.jobs import store
from app.services import evidence_import, evidence_rounds, soundbite_clips

ACCEPTED: Final = "accepted"
REJECTED: Final = "rejected"
VERDICTS: Final = (ACCEPTED, REJECTED)

NO_IMPORT_MESSAGE: Final = "Import the research results first, then review them here."
IMPORT_RUNNING_MESSAGE: Final = "The results are being imported. Review them when that is done."
UNKNOWN_CLAIM_MESSAGE: Final = "There is no such claim in this round."


class EvidenceReviewError(ValueError):
    """A review change that cannot be made. The message is meant to be shown to the user."""


class ClaimNotInRoundError(EvidenceReviewError):
    """The claim is not one of the round's claims."""


class ImportRunningError(EvidenceReviewError):
    """An import is going on, so the pieces to decide on are about to change."""


class TranscriptionRunningError(EvidenceReviewError):
    """The clip's transcription is already queued or running."""


# --- Decisions (pure) ----------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """The owner's decision on one claim."""

    # item_key -> `accepted` or `rejected`, only for pieces that have a verdict.
    verdicts: dict[str, str] = field(default_factory=dict)
    # The item keys shown on video, in the owner's order. Each one is accepted.
    shown: list[str] = field(default_factory=list)
    no_proof_on_screen: bool = False


def effective_decision(entry: object, usable_keys: list[str]) -> Decision:
    """A stored claim entry of `evidence_review.content`, kept to what still holds: verdicts of
    pieces in `usable_keys` only, and `shown` limited to accepted pieces, once each. Anything that
    is not a well-formed entry reads as no decision. Pure.
    """
    if not isinstance(entry, dict):
        return Decision()
    allowed = set(usable_keys)
    verdicts: dict[str, str] = {}
    raw_items = entry.get("items")
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        key, verdict = raw.get("item_key"), raw.get("verdict")
        if isinstance(key, str) and key in allowed and verdict in VERDICTS:
            verdicts[key] = verdict
    shown: list[str] = []
    raw_shown = entry.get("shown")
    for key in raw_shown if isinstance(raw_shown, list) else []:
        if isinstance(key, str) and verdicts.get(key) == ACCEPTED and key not in shown:
            shown.append(key)
    return Decision(
        verdicts=verdicts, shown=shown, no_proof_on_screen=entry.get("no_proof_on_screen") is True
    )


def is_decided(decision: Decision, usable_keys: list[str]) -> bool:
    """Whether the claim is decided (see the module's text). Pure."""
    if not usable_keys:
        return decision.no_proof_on_screen
    if any(key not in decision.verdicts for key in usable_keys):
        return False
    return bool(decision.shown) or decision.no_proof_on_screen


def check_decision(decision: Decision, usable_keys: list[str]) -> None:
    """Raises EvidenceReviewError when a decision the owner sends is not allowed: a verdict for a
    piece that is not usable in the newest import, two verdicts for one piece, a shown piece that
    is not accepted (or shown twice), or pieces shown together with `no_proof_on_screen`. Pure.
    """
    allowed = set(usable_keys)
    for key, verdict in decision.verdicts.items():
        if key not in allowed:
            raise EvidenceReviewError(
                "A piece of evidence in the decision is not a usable piece of this claim."
            )
        if verdict not in VERDICTS:
            raise EvidenceReviewError("A verdict must be accepted or rejected.")
    if len(set(decision.shown)) != len(decision.shown):
        raise EvidenceReviewError("A piece of evidence cannot be shown twice.")
    for key in decision.shown:
        if decision.verdicts.get(key) != ACCEPTED:
            raise EvidenceReviewError("Only an accepted piece of evidence can be shown.")
    if decision.shown and decision.no_proof_on_screen:
        raise EvidenceReviewError("A claim cannot both show evidence and have no proof on screen.")


def decision_entry(claim_id: str, decision: Decision, usable_keys: list[str]) -> dict[str, Any]:
    """One claim of `evidence_review.content`. The items are in the import's order. Pure."""
    return {
        "claim_id": claim_id,
        "items": [
            {"item_key": key, "verdict": decision.verdicts[key]}
            for key in usable_keys
            if key in decision.verdicts
        ],
        "shown": list(decision.shown),
        "no_proof_on_screen": decision.no_proof_on_screen,
    }


def undecided_ids(
    claim_ids: list[str], decisions: dict[str, Decision], keys: dict[str, list[str]]
) -> list[str]:
    """The claims that are not decided yet, in the round's order. Pure."""
    return [
        claim_id for claim_id in claim_ids if not is_decided(decisions[claim_id], keys[claim_id])
    ]


# --- What the review shows ---------------------------------------------------------------------


@dataclass
class ReviewClaim:
    """One claim of the round, with its import result, its pieces and the owner's decision."""

    # The claim as the round's brief states it (`id`, `origin`, `text`, `sentence`, `hint`, ...).
    entry: dict[str, Any]
    # The claim's entry of the import's `results` (`status`, `summary`, `attempts`, ...).
    result: dict[str, Any]
    # Every piece of the claim in the newest import, usable or not, in the import's order.
    items: list[EvidenceItem]
    decision: Decision
    decided: bool


@dataclass
class ReviewView:
    """Everything the review screen shows. `claims` is empty when there is nothing to review."""

    round_id: str | None
    import_id: int | None
    import_version: int | None
    # The newest review version of the round, or None when the owner has decided nothing yet.
    version: int | None
    # The newest review version is "Review done" and was made for the newest import.
    done: bool
    # Why decisions cannot be changed now, or None.
    blocked_reason: str | None
    claims: list[ReviewClaim]

    @property
    def editable(self) -> bool:
        return self.blocked_reason is None

    @property
    def undecided(self) -> list[str]:
        return [claim.entry["id"] for claim in self.claims if not claim.decided]


async def latest_review(session: AsyncSession, round_row_id: int) -> EvidenceReview | None:
    """The round's newest review version, or None."""
    statement = (
        select(EvidenceReview)
        .where(EvidenceReview.round_id == round_row_id)
        .order_by(EvidenceReview.version.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


def _review_claims_by_id(review: EvidenceReview | None) -> dict[str, Any]:
    content = review.content if review is not None else None
    claims = content.get("claims") if isinstance(content, dict) else None
    by_id: dict[str, Any] = {}
    for entry in claims if isinstance(claims, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("claim_id"), str):
            by_id[entry["claim_id"]] = entry
    return by_id


def _brief_claims(brief: Any) -> list[dict[str, Any]]:
    claims = brief.get("claims") if isinstance(brief, dict) else None
    return [
        claim
        for claim in (claims if isinstance(claims, list) else [])
        if isinstance(claim, dict) and isinstance(claim.get("id"), str)
    ]


async def _write_refusal(
    session: AsyncSession, project: Project, current: evidence_rounds.EvidenceState
) -> EvidenceReviewError | None:
    """Why the owner's decisions cannot be changed now, or None: the claims changed since the
    round's brief (a new round is needed), or an import is going on (a conflict). The caller has
    already checked that evidence applies and that the round exists.
    """
    if current.round is not None and not current.current:
        return EvidenceReviewError(
            f"The claims changed since round r{current.round.round_no}. Write a new round."
        )
    import_job = await store.latest_job(session, project.id, evidence_import.JOB_TYPE)
    if import_job is not None and import_job.status in store.ACTIVE_STATUSES:
        return ImportRunningError(IMPORT_RUNNING_MESSAGE)
    return None


@dataclass
class _Loaded:
    """What a change is made from: the state, the newest import and the newest review."""

    current: evidence_rounds.EvidenceState
    view: ReviewView
    import_id: int
    claim_ids: list[str]
    keys: dict[str, list[str]]
    decisions: dict[str, Decision]
    latest: EvidenceReview | None
    # Why nothing can be changed now, or None.
    refusal: EvidenceReviewError | None


async def _load(session: AsyncSession, project: Project) -> _Loaded | EvidenceReviewError:
    """The review as it stands, or why there is nothing to review."""
    current = await evidence_rounds.state(session, project)
    row = current.round
    if not current.wanted or row is None:
        return EvidenceReviewError(
            evidence_import.import_refusal(current) or evidence_import.NO_ROUND_MESSAGE
        )
    record = await evidence_import.latest_import(session, row.id)
    if record is None:
        return EvidenceReviewError(NO_IMPORT_MESSAGE)
    items = await evidence_import.items_of(session, record.id)
    by_claim: dict[str, list[EvidenceItem]] = {}
    for item in items:
        by_claim.setdefault(item.claim_id, []).append(item)
    entries = _brief_claims(row.brief)
    claim_ids = [entry["id"] for entry in entries]
    # A video clip (SB-006) is shown but gets no verdict until the sound bite review exists
    # (SB-007): it is left out of the pieces a decision may name.
    keys = {
        claim_id: [
            item.item_key
            for item in by_claim.get(claim_id, [])
            if item.usable and item.kind != "video"
        ]
        for claim_id in claim_ids
    }
    latest = await latest_review(session, row.id)
    stored = _review_claims_by_id(latest)
    decisions = {
        claim_id: effective_decision(stored.get(claim_id), keys[claim_id]) for claim_id in claim_ids
    }
    results = record.results if isinstance(record.results, dict) else {}
    claims = [
        ReviewClaim(
            entry=entry,
            result=results.get(entry["id"]) if isinstance(results.get(entry["id"]), dict) else {},
            items=by_claim.get(entry["id"], []),
            decision=decisions[entry["id"]],
            decided=is_decided(decisions[entry["id"]], keys[entry["id"]]),
        )
        for entry in entries
    ]
    refusal = await _write_refusal(session, project, current)
    inputs = latest.inputs if latest is not None else None
    view = ReviewView(
        round_id=f"r{row.round_no}",
        import_id=record.id,
        import_version=record.version,
        version=latest.version if latest is not None else None,
        done=(
            latest is not None
            and latest.done
            and isinstance(inputs, dict)
            and inputs.get("import_id") == record.id
        ),
        blocked_reason=str(refusal) if refusal is not None else None,
        claims=claims,
    )
    return _Loaded(
        current=current,
        view=view,
        import_id=record.id,
        claim_ids=claim_ids,
        keys=keys,
        decisions=decisions,
        latest=latest,
        refusal=refusal,
    )


async def view(session: AsyncSession, project: Project) -> ReviewView:
    """What the review screen shows. With nothing to review (evidence off, no round, no import)
    `claims` is empty and `blocked_reason` says why.
    """
    loaded = await _load(session, project)
    if isinstance(loaded, EvidenceReviewError):
        return ReviewView(
            round_id=None,
            import_id=None,
            import_version=None,
            version=None,
            done=False,
            blocked_reason=str(loaded),
            claims=[],
        )
    return loaded.view


@dataclass(frozen=True)
class ShownPiece:
    """One piece of evidence the owner chose to show, as the cut planner reads it."""

    item_key: str
    item_id: int


@dataclass(frozen=True)
class ShownClaim:
    """A claim that has evidence to show (EVD-009). `start` and `end` are code-point positions in
    `script_text` (end not included), as for the graphic suggestions; `pieces` are in the owner's
    order and are never empty.
    """

    id: str
    start: int
    end: int
    text: str
    pieces: tuple[ShownPiece, ...]


async def shown_claims(session: AsyncSession, project: Project) -> list[ShownClaim]:
    """The claims whose evidence is shown on video, in story order (EVD-009). Empty unless the
    newest round has exactly the claims that count now, so a claim whose words moved or changed
    never gets a shot. The positions are those `evidence_claims.state()` gives (never the brief's,
    which has none); a claim that is not placed in the story is left out.
    """
    current = await evidence_rounds.state(session, project)
    if not current.wanted or current.round is None or not current.current:
        return []
    review = await view(session, project)
    placed = {claim["id"]: claim for claim in current.claims}
    found: list[ShownClaim] = []
    for claim in review.claims:
        position = placed.get(claim.entry["id"])
        if position is None or not claim.decision.shown:
            continue
        by_key = {item.item_key: item for item in claim.items if item.usable}
        pieces = tuple(
            ShownPiece(item_key=key, item_id=by_key[key].id)
            for key in claim.decision.shown
            if key in by_key
        )
        if pieces:
            found.append(
                ShownClaim(
                    id=claim.entry["id"],
                    start=position["start"],
                    end=position["end"],
                    text=position["text"],
                    pieces=pieces,
                )
            )
    return sorted(found, key=lambda claim: claim.start)


# --- The owner's actions -------------------------------------------------------------------


def _content(loaded: _Loaded, decisions: dict[str, Decision]) -> dict[str, Any]:
    return {
        "claims": [
            decision_entry(claim_id, decisions[claim_id], loaded.keys[claim_id])
            for claim_id in loaded.claim_ids
        ]
    }


async def _add_version(
    session: AsyncSession,
    project: Project,
    round_row_id: int,
    import_id: int,
    content: dict[str, Any],
    *,
    done: bool,
) -> None:
    highest = (
        await session.execute(
            select(func.max(EvidenceReview.version)).where(EvidenceReview.project_id == project.id)
        )
    ).scalar_one_or_none()
    session.add(
        EvidenceReview(
            project_id=project.id,
            round_id=round_row_id,
            version=(highest or 0) + 1,
            inputs={"import_id": import_id},
            content=content,
            done=done,
        )
    )
    await session.commit()


def _unchanged(loaded: _Loaded, content: dict[str, Any], *, done: bool) -> bool:
    """The newest version already says exactly this, for the newest import. With no version yet,
    only the default (no decision at all) is unchanged.
    """
    latest = loaded.latest
    if latest is None:
        return not done and content == _content(loaded, {c: Decision() for c in loaded.claim_ids})
    inputs = latest.inputs
    return (
        isinstance(inputs, dict)
        and inputs.get("import_id") == loaded.import_id
        and latest.done == done
        and latest.content == content
    )


async def _loaded_for_edit(session: AsyncSession, project: Project) -> _Loaded:
    loaded = await _load(session, project)
    if isinstance(loaded, EvidenceReviewError):
        raise loaded
    if loaded.refusal is not None:
        raise loaded.refusal
    return loaded


async def save_claim_decision(
    session: AsyncSession, project: Project, claim_id: str, decision: Decision
) -> ReviewView:
    """Replaces the decision on one claim, as a new version with `done` false (nothing is stored
    when it changes nothing), and commits. Raises ClaimNotInRoundError, ImportRunningError or
    EvidenceReviewError.
    """
    loaded = await _loaded_for_edit(session, project)
    if claim_id not in loaded.keys:
        raise ClaimNotInRoundError(UNKNOWN_CLAIM_MESSAGE)
    check_decision(decision, loaded.keys[claim_id])
    row = loaded.current.round
    assert row is not None
    decisions = {**loaded.decisions, claim_id: decision}
    content = _content(loaded, decisions)
    if not _unchanged(loaded, content, done=False):
        await _add_version(session, project, row.id, loaded.import_id, content, done=False)
    return await view(session, project)


async def finish_review(session: AsyncSession, project: Project) -> ReviewView:
    """Ends the review ("Review done"): a new version with `done` true, when every claim is
    decided. Raises EvidenceReviewError naming the claims that are not. Commits.
    """
    loaded = await _loaded_for_edit(session, project)
    open_claims = undecided_ids(loaded.claim_ids, loaded.decisions, loaded.keys)
    if open_claims:
        many = len(open_claims) > 1
        raise EvidenceReviewError(
            f"Decide {'these claims' if many else 'this claim'} first: {', '.join(open_claims)}."
        )
    row = loaded.current.round
    assert row is not None
    content = _content(loaded, loaded.decisions)
    if not _unchanged(loaded, content, done=True):
        await _add_version(session, project, row.id, loaded.import_id, content, done=True)
    return await view(session, project)


async def retry_transcription(session: AsyncSession, project: Project, item_key: str) -> Job:
    """Queues the transcription of a sound bite clip again ("Transcribe again"). Only for a usable
    clip of the newest import that has no heard words and no active job. Commits. Raises
    TranscriptionRunningError (a job is active) or EvidenceReviewError.
    """
    loaded = await _load(session, project)
    if isinstance(loaded, EvidenceReviewError):
        raise loaded
    if loaded.refusal is not None:
        raise loaded.refusal
    item = next(
        (
            entry
            for claim in loaded.view.claims
            for entry in claim.items
            if entry.item_key == item_key
        ),
        None,
    )
    if item is None or not item.usable or item.kind != "video":
        raise EvidenceReviewError("This is not a usable clip of the newest import.")
    if item.transcribe_job_id is None:
        raise EvidenceReviewError("This clip is not for a sound bite, so it is not transcribed.")
    if item.heard_words is not None:
        raise EvidenceReviewError("This clip is transcribed already.")
    job = (await soundbite_clips.jobs_of(session, [item])).get(item.id)
    if job is not None and job.status in store.ACTIVE_STATUSES:
        raise TranscriptionRunningError("The clip is being transcribed. Wait for it to finish.")
    return await soundbite_clips.queue(session, item, commit=True)
