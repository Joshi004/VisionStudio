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

**Sound bite clips (SB-007).** A usable `video` piece has a verdict like any other. For a clip of
a sound bite claim, an `accepted` verdict also carries a `soundbite` object (`SOUNDBITE_FIELDS`):
the start and end words, the cut found in the clip's audio from those words (the browser sends
words, never times: `_with_clip_details`), the lower third's lines, the recording date, the flags
acknowledged and the rights note. Since SB-016 the owner only presses Accept: the app fills all of
this in (`_auto_details`: the proposed cut, the claim's speaker, the role and venue the agent
gave, the date). `check_clip` lists the rules; a clip that is not
accepted has no details, and an accepted one whose details are missing or no longer fit its words
reads as undecided again. At most one clip is shown per claim, and then nothing else; a video of
a claim that is not a sound bite is only context and is never shown. `shown_claims` leaves clips
out: `shown_soundbites` lists them for the cut plan (SB-008).

No file is ever deleted here (EVD-006: stored files are shared between items and imports).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceItem, EvidenceReview, Project
from app.jobs import store
from app.services import (
    evidence_claims,
    evidence_import,
    evidence_rounds,
    soundbite_analysis,
    soundbite_clips,
)
from app.services.soundbite_analysis import HeardWord

ACCEPTED: Final = "accepted"
REJECTED: Final = "rejected"
VERDICTS: Final = (ACCEPTED, REJECTED)

# --- Sound bite clips (SB-007) -------------------------------------------------------------

# The lower third's lines, and the rights note.
SPEAKER_MAX_CHARS: Final = evidence_claims.SPEAKER_MAX_CHARS
LINE_MAX_CHARS: Final = 80
RIGHTS_NOTE_MAX_CHARS: Final = 300
# Flags that are never listed as to acknowledge: the length is checked on its own, the admission
# words are worked out again for the cut, and the date flags are replaced by the recording date
# the app fills in (which must be a real date not later than the upload).
DATE_FLAG_CODES: Final = ("date_missing", "date_after_upload")
UNACKNOWLEDGED_FLAG_CODES: Final = (*soundbite_analysis.TRIM_FLAG_CODES, *DATE_FLAG_CODES)
_DATE_PATTERN: Final = re.compile(r"\d{4}-\d{2}-\d{2}")

NO_IMPORT_MESSAGE: Final = "Import the research results first, then review them here."
IMPORT_RUNNING_MESSAGE: Final = "The results are being imported. Review them when that is done."
UNKNOWN_CLAIM_MESSAGE: Final = "There is no such claim in this round."


class EvidenceReviewError(ValueError):
    """A review change that cannot be made. The message is meant to be shown to the user."""


class ClaimNotInRoundError(EvidenceReviewError):
    """The claim is not one of the round's claims."""


class ImportRunningError(EvidenceReviewError):
    """An import is going on, so the pieces to decide on are about to change."""


# --- Decisions (pure) ----------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """The owner's decision on one claim."""

    # item_key -> `accepted` or `rejected`, only for pieces that have a verdict.
    verdicts: dict[str, str] = field(default_factory=dict)
    # The item keys shown on video, in the owner's order. Each one is accepted.
    shown: list[str] = field(default_factory=list)
    no_proof_on_screen: bool = False
    # item_key -> the owner's sound bite details of an accepted clip (SB-007), as stored in
    # `evidence_review.content` (see `SOUNDBITE_FIELDS`).
    soundbites: dict[str, dict[str, Any]] = field(default_factory=dict)
    # item_key -> (first_word, last_word): the cut the owner chose for an accepted clip, as words
    # of the clip (SB-017). Only for a decision being saved: `_with_clip_details` turns it into
    # `soundbites`, and it is never stored.
    cuts: dict[str, tuple[int, int]] = field(default_factory=dict)


# The fields of a clip's `soundbite` object, in the order they are stored.
SOUNDBITE_FIELDS: Final = (
    "first_word",
    "last_word",
    "in_s",
    "out_s",
    "in_clean",
    "out_clean",
    "speaker",
    "role",
    "venue",
    "recorded",
    "acknowledged_flags",
    "rights_note",
    "music_drop",
)
_INT_FIELDS: Final = ("first_word", "last_word")
_NUMBER_FIELDS: Final = ("in_s", "out_s")
_BOOL_FIELDS: Final = ("in_clean", "out_clean", "music_drop")
_TEXT_FIELDS: Final = ("speaker", "role", "venue", "recorded", "rights_note")


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def read_soundbite(raw: object) -> dict[str, Any] | None:
    """A stored `soundbite` object of an accepted clip, with the fields in storage order, or None
    when it is not well formed (a missing field or a field of the wrong kind). Pure."""
    if not isinstance(raw, dict):
        return None
    result: dict[str, Any] = {}
    for name in SOUNDBITE_FIELDS:
        value = raw.get(name)
        if name in _INT_FIELDS:
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif name in _NUMBER_FIELDS:
            valid = _is_number(value)
        elif name in _BOOL_FIELDS:
            valid = isinstance(value, bool)
        elif name in _TEXT_FIELDS:
            valid = isinstance(value, str)
        else:
            valid = isinstance(value, list) and all(isinstance(code, str) for code in value)
        if not valid:
            return None
        result[name] = list(value) if name == "acknowledged_flags" else value
    return result


@dataclass(frozen=True)
class ClipFacts:
    """What the rules for a `video` piece need to know, read from the item and the brief once.
    `soundbite` is whether the claim is a sound bite; a video of any other claim is only context
    and is never shown."""

    soundbite: bool
    words: tuple[HeardWord, ...]
    fidelity: str | None
    licence: str | None
    upload_date: str | None
    # The flags the import stored (`code`), in order.
    flag_codes: tuple[str, ...]
    # The claim's entry of the round's brief (`sentence`, `context`), for the admission words.
    brief_entry: dict[str, Any]

    def required_flags(self, trim: dict[str, Any]) -> list[str]:
        """The flag codes the owner must acknowledge for this cut: the stored ones that are not
        in `UNACKNOWLEDGED_FLAG_CODES`, and `admission_words` when the cut holds such a phrase.
        Pure."""
        codes = [code for code in self.flag_codes if code not in UNACKNOWLEDGED_FLAG_CODES]
        for flag in soundbite_analysis.trim_flags(list(self.words), trim, self.brief_entry):
            if flag["code"] == "admission_words" and flag["code"] not in codes:
                codes.append(flag["code"])
        return codes


def effective_decision(
    entry: object, usable_keys: list[str], clips: dict[str, ClipFacts] | None = None
) -> Decision:
    """A stored claim entry of `evidence_review.content`, kept to what still holds: verdicts of
    pieces in `usable_keys` only, and `shown` limited to accepted pieces, once each. An accepted
    clip of a sound bite claim keeps its verdict only with a well formed `soundbite` object whose
    words are words of the clip; otherwise the clip is undecided again. Anything that is not a
    well-formed entry reads as no decision. Pure.
    """
    if not isinstance(entry, dict):
        return Decision()
    clips = clips or {}
    allowed = set(usable_keys)
    verdicts: dict[str, str] = {}
    soundbites: dict[str, dict[str, Any]] = {}
    raw_items = entry.get("items")
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        key, verdict = raw.get("item_key"), raw.get("verdict")
        if not (isinstance(key, str) and key in allowed and verdict in VERDICTS):
            continue
        facts = clips.get(key)
        if verdict == ACCEPTED and facts is not None and facts.soundbite:
            details = read_soundbite(raw.get("soundbite"))
            if details is None or details["last_word"] >= len(facts.words):
                continue
            if details["first_word"] < 0 or details["first_word"] > details["last_word"]:
                continue
            soundbites[key] = details
        verdicts[key] = verdict
    shown: list[str] = []
    raw_shown = entry.get("shown")
    for key in raw_shown if isinstance(raw_shown, list) else []:
        if isinstance(key, str) and verdicts.get(key) == ACCEPTED and key not in shown:
            shown.append(key)
    return Decision(
        verdicts=verdicts,
        shown=shown,
        no_proof_on_screen=entry.get("no_proof_on_screen") is True,
        soundbites=soundbites,
    )


def is_decided(decision: Decision, usable_keys: list[str]) -> bool:
    """Whether the claim is decided (see the module's text). Pure."""
    if not usable_keys:
        return decision.no_proof_on_screen
    if any(key not in decision.verdicts for key in usable_keys):
        return False
    return bool(decision.shown) or decision.no_proof_on_screen


def _line_problem(value: object, limit: int) -> bool:
    """Whether a lower third line is blank, too long or holds a character that cannot be shown."""
    return (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or not all(char.isprintable() for char in value)
    )


def _real_date(value: object) -> date | None:
    """A `YYYY-MM-DD` text as a date, or None."""
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def check_clip(key: str, facts: ClipFacts, details: dict[str, Any] | None, today: date) -> None:
    """Raises EvidenceReviewError when an accepted clip of a sound bite claim lacks something
    (the rules of SB-007 as SB-016 relaxed them), with one sentence. `details` is the `soundbite`
    object with its cut filled in. What the app needs: the clip has words (from the source's
    captions), a cut of 3 to 15 s and a speaker. Whether the words are the quote's is the owner's
    decision: the review warns when they differ (`facts.fidelity`), and the owner may accept
    anyway. The owner no longer confirms the role, the venue, the date, the flags or a rights
    note. Pure.
    """
    if not facts.words:
        raise EvidenceReviewError(
            "The captions gave no words for this clip, so it cannot be accepted."
        )
    if details is None:
        raise EvidenceReviewError("The app found no cut for this clip, so it cannot be accepted.")
    first, last = details.get("first_word"), details.get("last_word")
    if (
        not isinstance(first, int)
        or not isinstance(last, int)
        or isinstance(first, bool)
        or isinstance(last, bool)
        or not 0 <= first <= last < len(facts.words)
    ):
        raise EvidenceReviewError("The start and end words are not words of this clip.")
    start, end = details.get("in_s"), details.get("out_s")
    if not _is_number(start) or not _is_number(end) or end < start:
        raise EvidenceReviewError("The cut of this clip is not known.")
    length = end - start
    low, high = soundbite_analysis.MIN_CLIP_S, soundbite_analysis.MAX_CLIP_S
    if length < low or length > high:
        raise EvidenceReviewError(
            f"The cut is {length:.1f} s long; a sound bite is {low:.0f} to {high:.0f} s."
        )
    if _line_problem(details.get("speaker"), SPEAKER_MAX_CHARS):
        raise EvidenceReviewError("The claim has no speaker name for the lower third.")
    # The role and the venue may be empty (the lower third leaves them out); when there, each is
    # one line that can be shown.
    for name in ("role", "venue"):
        line = details.get(name)
        if line != "" and _line_problem(line, LINE_MAX_CHARS):
            raise EvidenceReviewError(f"The {name} of the lower third cannot be shown.")
    # The recording date may be empty; when there, it is a real date that is not in the future
    # and not after the upload.
    if details.get("recorded") != "":
        recorded = _real_date(details.get("recorded"))
        if recorded is None:
            raise EvidenceReviewError("The recording date is not a date (year, month and day).")
        if recorded > today:
            raise EvidenceReviewError("The recording date cannot be in the future.")
        uploaded = _real_date(facts.upload_date)
        if uploaded is not None and recorded > uploaded:
            raise EvidenceReviewError("The recording date cannot be later than the upload date.")


def check_decision(
    decision: Decision,
    usable_keys: list[str],
    clips: dict[str, ClipFacts] | None = None,
    today: date | None = None,
) -> None:
    """Raises EvidenceReviewError when a decision the owner sends is not allowed: a verdict for a
    piece that is not usable in the newest import, two verdicts for one piece, a shown piece that
    is not accepted (or shown twice), or pieces shown together with `no_proof_on_screen`. For
    clips (`clips`, by item key, for every usable `video` piece; SB-007): an accepted clip of a
    sound bite claim must pass `check_clip`; sound bite details belong only to such a clip; a
    video that is only context is never shown; at most one clip is shown, and then nothing
    else. A cut (SB-017) belongs only to an accepted clip of a sound bite claim and must name
    words of the clip. Pure.
    """
    clips = clips or {}
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

    for key in decision.soundbites:
        facts = clips.get(key)
        if facts is None or not facts.soundbite:
            raise EvidenceReviewError(
                "Sound bite details belong only to a clip of a sound bite claim."
            )
        if decision.verdicts.get(key) != ACCEPTED:
            raise EvidenceReviewError("Sound bite details belong only to an accepted clip.")
    for key, (first, last) in decision.cuts.items():
        facts = clips.get(key)
        if facts is None or not facts.soundbite:
            raise EvidenceReviewError("A cut belongs only to a clip of a sound bite claim.")
        if decision.verdicts.get(key) != ACCEPTED:
            raise EvidenceReviewError("A cut belongs only to an accepted clip.")
        if not 0 <= first <= last < len(facts.words):
            raise EvidenceReviewError("The start and end words are not words of this clip.")
    for key, verdict in decision.verdicts.items():
        facts = clips.get(key)
        if facts is not None and facts.soundbite and verdict == ACCEPTED:
            check_clip(key, facts, decision.soundbites.get(key), today or date.today())
    shown_clips = [key for key in decision.shown if key in clips and clips[key].soundbite]
    if any(key in clips and not clips[key].soundbite for key in decision.shown):
        raise EvidenceReviewError("A video that is only context cannot be shown on video.")
    if len(shown_clips) > 1:
        raise EvidenceReviewError("Only one sound bite clip can be shown for a claim.")
    if shown_clips and len(decision.shown) > 1:
        raise EvidenceReviewError("A claim that shows a sound bite clip shows nothing else.")


def decision_entry(claim_id: str, decision: Decision, usable_keys: list[str]) -> dict[str, Any]:
    """One claim of `evidence_review.content`. The items are in the import's order; an accepted
    clip also carries its `soundbite` object. Pure."""
    items: list[dict[str, Any]] = []
    for key in usable_keys:
        if key not in decision.verdicts:
            continue
        item: dict[str, Any] = {"item_key": key, "verdict": decision.verdicts[key]}
        details = decision.soundbites.get(key)
        if details is not None and decision.verdicts[key] == ACCEPTED:
            item["soundbite"] = {name: details[name] for name in SOUNDBITE_FIELDS}
        items.append(item)
    return {
        "claim_id": claim_id,
        "items": items,
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
    # For each claim, the rules' facts and the item of every usable `video` piece, by item key.
    clips: dict[str, dict[str, ClipFacts]]
    clip_items: dict[str, EvidenceItem]


def _clip_facts(item: EvidenceItem, entry: dict[str, Any]) -> ClipFacts:
    """The facts the rules need about one usable `video` piece of the claim `entry`."""
    capture = item.capture if isinstance(item.capture, dict) else {}
    licence, upload = capture.get("licence"), capture.get("upload_date")
    stored = item.flags if isinstance(item.flags, list) else []
    return ClipFacts(
        soundbite=evidence_claims.is_soundbite(entry),
        words=tuple(soundbite_clips.words_of(item.heard_words)),
        fidelity=item.fidelity,
        licence=licence if isinstance(licence, str) else None,
        upload_date=upload if isinstance(upload, str) else None,
        flag_codes=tuple(
            flag["code"]
            for flag in stored
            if isinstance(flag, dict) and isinstance(flag.get("code"), str)
        ),
        brief_entry=entry,
    )


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
    keys = {
        claim_id: [item.item_key for item in by_claim.get(claim_id, []) if item.usable]
        for claim_id in claim_ids
    }
    clips: dict[str, dict[str, ClipFacts]] = {}
    clip_items: dict[str, EvidenceItem] = {}
    for entry in entries:
        found: dict[str, ClipFacts] = {}
        for item in by_claim.get(entry["id"], []):
            if item.usable and item.kind == "video":
                found[item.item_key] = _clip_facts(item, entry)
                clip_items[item.item_key] = item
        clips[entry["id"]] = found
    latest = await latest_review(session, row.id)
    stored = _review_claims_by_id(latest)
    decisions = {
        claim_id: effective_decision(stored.get(claim_id), keys[claim_id], clips[claim_id])
        for claim_id in claim_ids
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
        clips=clips,
        clip_items=clip_items,
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
        # A shown sound bite clip gets no screenshot shot: `shown_soundbites` plans its own.
        by_key = {
            item.item_key: item for item in claim.items if item.usable and item.kind != "video"
        }
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


@dataclass(frozen=True)
class ShownSoundbite:
    """A sound bite clip the owner accepted and chose to show (SB-008). `start` and `end` are
    code-point positions of the quote in `script_text`, as for `ShownClaim`. `item_key` names the
    clip. `seconds` is the length of the owner's cut (`out_s - in_s`), not yet rounded to frames.
    """

    id: str
    start: int
    end: int
    text: str
    item_key: str
    seconds: float


@dataclass(frozen=True)
class SoundbiteClip:
    """A shown sound bite with what its render needs (SB-009): the clip's row in the newest import
    and the owner's details of it (`SOUNDBITE_FIELDS`, with the cut, the lower third's lines and
    `music_drop`). `start` and `end` are the quote's code-point positions in `script_text`."""

    id: str
    start: int
    end: int
    text: str
    item_key: str
    item: EvidenceItem
    details: dict[str, Any]


async def shown_soundbite_clips(session: AsyncSession, project: Project) -> list[SoundbiteClip]:
    """The sound bite clips shown on video, in story order, with their rows and the owner's
    details (SB-008, SB-009). The same gate as `shown_claims`: empty unless the newest round has
    exactly the claims that count now. A claim is listed when it is a sound bite whose one shown
    piece is a usable `video` item with the owner's details.
    """
    current = await evidence_rounds.state(session, project)
    if not current.wanted or current.round is None or not current.current:
        return []
    review = await view(session, project)
    placed = {claim["id"]: claim for claim in current.claims}
    found: list[SoundbiteClip] = []
    for claim in review.claims:
        position = placed.get(claim.entry["id"])
        if position is None or not evidence_claims.is_soundbite(claim.entry):
            continue
        clips = {
            item.item_key: item for item in claim.items if item.usable and item.kind == "video"
        }
        for key in claim.decision.shown:
            details = claim.decision.soundbites.get(key)
            if key not in clips or details is None:
                continue
            found.append(
                SoundbiteClip(
                    id=claim.entry["id"],
                    start=position["start"],
                    end=position["end"],
                    text=position["text"],
                    item_key=key,
                    item=clips[key],
                    details=details,
                )
            )
            break
    return sorted(found, key=lambda bite: bite.start)


async def shown_soundbites(session: AsyncSession, project: Project) -> list[ShownSoundbite]:
    """The sound bite clips shown on video, in story order (SB-008). The same gate as
    `shown_claims`: empty unless the newest round has exactly the claims that count now. A claim
    is listed when it is a sound bite whose one shown piece is a usable `video` item with the
    owner's details. A change of the cut changes only `seconds`.
    """
    return [
        ShownSoundbite(
            id=clip.id,
            start=clip.start,
            end=clip.end,
            text=clip.text,
            item_key=clip.item_key,
            seconds=round(float(clip.details["out_s"]) - float(clip.details["in_s"]), 3),
        )
        for clip in await shown_soundbite_clips(session, project)
    ]


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


_CUT_FIELDS: Final = ("in_s", "out_s", "in_clean", "out_clean")


def _clean_line(value: object, limit: int = LINE_MAX_CHARS) -> str:
    """A text as one line, or the empty text when it is not text or cannot be shown."""
    if not isinstance(value, str):
        return ""
    line = " ".join(value.split())
    return "" if _line_problem(line, limit) else line


_LICENCE_NOTE: Final = {
    "standard": "standard",
    "creative_commons": "Creative Commons",
    "unknown": "unknown",
}
CHANNEL_NOTE_MAX_CHARS: Final = 60


def clip_note(item: EvidenceItem, facts: ClipFacts, cut: dict[str, Any]) -> str:
    """One line on why a clip may be used (SB-017), made from what the app knows and stored as the
    clip's `rights_note`: whose channel it is, how long the excerpt is, that the narrator comments
    on it, the licence and how well the words match. `cut` holds `in_s` and `out_s`. It is a
    record of the app's own facts, not legal advice. Pure.
    """
    capture = item.capture if isinstance(item.capture, dict) else {}
    channel = _clean_line(capture.get("channel"), CHANNEL_NOTE_MAX_CHARS)
    named = f" ({channel})" if channel else ""
    if "channel_not_publisher" in facts.flag_codes:
        source = f"Not the publisher's channel{named}"
    elif item.source_tier == "primary":
        source = f"Official channel{named}"
    elif item.source_tier == "secondary":
        source = f"Outlet's upload{named}"
    else:
        source = f"Other channel{named}"
    length = float(cut["out_s"]) - float(cut["in_s"])
    parts = [
        source,
        f"{length:.1f} s excerpt",
        "used with commentary",
        f"licence: {_LICENCE_NOTE.get(facts.licence or '', 'unknown')}",
        f"words: {facts.fidelity or 'unknown'}",
    ]
    return _clean_line(", ".join(parts) + ".", RIGHTS_NOTE_MAX_CHARS)


def _auto_recorded(item: EvidenceItem, facts: ClipFacts, today: date) -> str:
    """The recording date the app uses for a clip: the date the agent gave (`source.published`)
    when it is a real date that is not in the future and not after the upload, else the upload
    date, else the empty text."""
    uploaded = _real_date(facts.upload_date)
    source = item.source if isinstance(item.source, dict) else {}
    for candidate in (source.get("published"), facts.upload_date):
        found = _real_date(candidate)
        if found is None or found > today or (uploaded is not None and found > uploaded):
            continue
        return found.isoformat()
    return ""


def _auto_details(item: EvidenceItem, facts: ClipFacts, today: date) -> dict[str, Any] | None:
    """The `soundbite` object of an accepted clip when the owner only pressed Accept (SB-016): the
    words and the cut the app proposed for the quote, the claim's speaker, the role and venue the
    agent gave, the recording date (`_auto_recorded`), every flag acknowledged, the app's own note
    on why the clip may be used (`clip_note`) and the music only lowered. None when the clip has
    no usable match or proposed cut, for `check_decision` to refuse with its reason."""
    heard = item.heard_words if isinstance(item.heard_words, dict) else {}
    match = heard.get("match")
    trim = item.proposed_trim
    if not isinstance(match, dict) or not isinstance(trim, dict):
        return None
    first, last = match.get("first"), match.get("last")
    if (
        not isinstance(first, int)
        or not isinstance(last, int)
        or isinstance(first, bool)
        or isinstance(last, bool)
        or not 0 <= first <= last < len(facts.words)
    ):
        return None
    start, end = trim.get("in_s"), trim.get("out_s")
    if not _is_number(start) or not _is_number(end):
        return None
    cut = {
        "in_s": float(start),
        "out_s": float(end),
        "in_clean": trim.get("in_clean") is True,
        "out_clean": trim.get("out_clean") is True,
    }
    capture = item.capture if isinstance(item.capture, dict) else {}
    return {
        "first_word": first,
        "last_word": last,
        **cut,
        "speaker": _clean_line(facts.brief_entry.get("speaker"), SPEAKER_MAX_CHARS),
        "role": _clean_line(capture.get("role")),
        "venue": _clean_line(capture.get("venue")),
        "recorded": _auto_recorded(item, facts, today),
        "acknowledged_flags": facts.required_flags(cut),
        "rights_note": clip_note(item, facts, cut),
        "music_drop": False,
    }


async def _with_clip_details(loaded: _Loaded, claim_id: str, decision: Decision) -> Decision:
    """The decision with the cut of each clip set from the start and end words, and each clip's
    acknowledged flags kept to the ones that are asked for. An accepted clip of a sound bite claim
    that comes without details gets the app's own (`_auto_details`), or the ones stored for it.
    The browser sends words, never times: the cut is found in the clip's own audio (as the
    proposed cut is), or is the stored one when the words did not change. A clip whose details
    cannot be used is left as it is, for `check_decision` to refuse with its reason. Raises
    EvidenceReviewError when the audio cannot be read.
    """
    clips = loaded.clips[claim_id]
    before = loaded.decisions[claim_id].soundbites
    filled: dict[str, dict[str, Any]] = {}
    for key, details in decision.soundbites.items():
        facts = clips.get(key)
        first, last = details.get("first_word"), details.get("last_word")
        if (
            facts is None
            or not facts.soundbite
            or not isinstance(first, int)
            or not isinstance(last, int)
            or isinstance(first, bool)
            or isinstance(last, bool)
            or not 0 <= first <= last < len(facts.words)
        ):
            filled[key] = details
            continue
        stored = before.get(key)
        if stored is not None and stored["first_word"] == first and stored["last_word"] == last:
            cut = {name: stored[name] for name in _CUT_FIELDS}
        else:
            try:
                cut = await soundbite_clips.trim_for(loaded.clip_items[key], first, last)
            except soundbite_clips.SoundbiteClipError as exc:
                raise EvidenceReviewError(str(exc)) from exc
        sent = details.get("acknowledged_flags")
        sent = sent if isinstance(sent, list) else []
        required = facts.required_flags(cut)
        filled[key] = {
            **details,
            **cut,
            "acknowledged_flags": [code for code in required if code in sent],
        }
    today = date.today()
    # A clip that comes with a cut and no details (SB-017): the stored or automatic details, with
    # the cut found in the clip's audio for the chosen words. A cut that does not belong to an
    # accepted clip, or whose words are not the clip's, is left for `check_decision` to refuse.
    for key, (first, last) in decision.cuts.items():
        facts = clips.get(key)
        if (
            facts is None
            or not facts.soundbite
            or decision.verdicts.get(key) != ACCEPTED
            or key in filled
            or not 0 <= first <= last < len(facts.words)
        ):
            continue
        item = loaded.clip_items[key]
        details = before.get(key) or _auto_details(item, facts, today)
        if details is None:
            continue
        if (details["first_word"], details["last_word"]) != (first, last):
            try:
                cut = await soundbite_clips.trim_for(item, first, last)
            except soundbite_clips.SoundbiteClipError as exc:
                raise EvidenceReviewError(str(exc)) from exc
            details = {
                **details,
                "first_word": first,
                "last_word": last,
                **cut,
                "acknowledged_flags": facts.required_flags(cut),
                "rights_note": clip_note(item, facts, cut),
            }
        filled[key] = details
    for key, verdict in decision.verdicts.items():
        facts = clips.get(key)
        if verdict != ACCEPTED or facts is None or not facts.soundbite or key in filled:
            continue
        details = before.get(key) or _auto_details(loaded.clip_items[key], facts, today)
        if details is not None:
            filled[key] = details
    return replace(decision, soundbites=filled)


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
    decision = await _with_clip_details(loaded, claim_id, decision)
    check_decision(decision, loaded.keys[claim_id], loaded.clips[claim_id])
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


@dataclass(frozen=True)
class TrimPreview:
    """A cut the owner is trying, before anything is saved: the points, the length, the flags that
    depend on the cut and the warnings."""

    in_s: float
    out_s: float
    in_clean: bool
    out_clean: bool
    length_s: float
    flags: list[dict[str, str]]
    warnings: list[str]


async def preview_trim(
    session: AsyncSession, project: Project, item_key: str, first: int, last: int
) -> TrimPreview:
    """The cut for a clip of the newest import whose quote runs from heard word `first` to heard
    word `last`, found in the clip's own audio. Read only: nothing is stored. Raises
    EvidenceReviewError when the piece is not a transcribed clip of the newest import or the
    words are not words of the clip.
    """
    loaded = await _load(session, project)
    if isinstance(loaded, EvidenceReviewError):
        raise loaded
    item = loaded.clip_items.get(item_key)
    if item is None:
        raise EvidenceReviewError("This is not a usable clip of the newest import.")
    facts = next(found[item_key] for found in loaded.clips.values() if item_key in found)
    if not facts.words:
        raise EvidenceReviewError(
            "The captions gave no words for this clip, so it cannot be trimmed."
        )
    if not 0 <= first <= last < len(facts.words):
        raise EvidenceReviewError("The start and end words are not words of this clip.")
    try:
        cut = await soundbite_clips.trim_for(item, first, last)
    except soundbite_clips.SoundbiteClipError as exc:
        raise EvidenceReviewError(str(exc)) from exc
    length = cut["out_s"] - cut["in_s"]
    warnings = []
    if soundbite_analysis.WARN_CLIP_S < length <= soundbite_analysis.MAX_CLIP_S:
        warnings.append(
            f"The cut is {length:.1f} s long. A sound bite longer than "
            f"{soundbite_analysis.WARN_CLIP_S:.0f} s starts to feel like a speech."
        )
    return TrimPreview(
        in_s=cut["in_s"],
        out_s=cut["out_s"],
        in_clean=cut["in_clean"],
        out_clean=cut["out_clean"],
        length_s=round(length, 3),
        flags=soundbite_analysis.trim_flags(list(facts.words), cut, facts.brief_entry),
        warnings=warnings,
    )
