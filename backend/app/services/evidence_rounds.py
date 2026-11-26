"""The research rounds of the evidence layer: the brief the app writes for the research agent, and
where a round stands (EVD-003, `Evidence_layer_implementation_phases.md` §4.3, §4.4).

A **round** is one brief written for the claims that were waiting for research when it was written
(`evidence_round`). The app writes `evidence/<project_id>/r<round_no>/brief/claims.json` and
`README.md` in the files folder, and an empty `results/` folder for the agent.

**Evidence is per claim (OVL-006).** A claim is **covered** by the newest *reviewed* round whose
brief holds it unchanged (`claim_keys`), and its evidence is what that round's review shows
(`evidence_review.shown_view`). A claim that counts and has no covering round is **waiting**. A new
round carries only the waiting claims, so adding a claim later researches that claim alone and
leaves every reviewed claim, and the shots, cards and clips built from it, as they were. (Before
OVL-006 every round carried every claim and stood alone.) The newest round is the one the owner
imports and reviews.

**Where a round stands** is worked out on read from the rows that exist (`round_status`):

- `brief_written`: the round exists and has no import (EVD-006).
- `imported`: an `evidence_import` exists.
- `reviewed`: the newest `evidence_review` of the round is `done` and was made for the round's
  newest import (EVD-007).

**The `evidence` pipeline step** waits on the owner, not on a job: `awaiting_text` is what the
owner has to do next, or None. The step is done when the claims that count are empty, or when none
of them is waiting. `current` is whether the newest round holds every waiting claim unchanged (a
new brief would add nothing); `live` is whether it holds at least one claim that counts unchanged
(so it can still be imported and reviewed). A claim that is not as the round brief says (its id,
origin, words, sentence, note, kind, or for a sound bite its `want` and `speaker`) is not held by
it; the sentences around it do not count, so an edit elsewhere in the story forces no new round.

Claims are read through `evidence_claims.state()`, never straight from a row (EVD-002): a claim
whose words changed in the story is unusable.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import anyio.to_thread
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.db.models import (
    EvidenceImport,
    EvidenceReview,
    EvidenceRound,
    Job,
    Project,
)
from app.db.state_memo import memoized_state
from app.db.types import utcnow
from app.jobs import store
from app.services import evidence_claims, story_bible
from app.services.speech_chunks import sentences
from app.services.storage import FILES_MARKER, StorageError

JOB_TYPE: Final = "write_evidence_brief"

BRIEF_SCHEMA: Final = "visio.evidence.brief"
# Version 1 is the brief of a round with no sound bite; version 2 (SB-001) is written when any
# claim is a sound bite, and then every entry also says `want` and `speaker`.
BRIEF_VERSION_PLAIN: Final = 1
BRIEF_VERSION_SOUNDBITE: Final = 2
# What the agent may keep for one claim (§4.4 `rules`). Domain lists are for a later phase.
MAX_EVIDENCE_PER_CLAIM: Final = 3

# The skill the agent is told to use (`tools/evidence-skill/`, EVD-005). The prompt is plain text
# so that it works the same in Cursor and in Claude Code.
SKILL_NAME: Final = "visio-evidence"
README_PROMPT: Final = (
    f"Use the {SKILL_NAME} skill to research every claim in brief/claims.json of this round, "
    "each on its own. Then run validate and show me the table of results."
)

STATUS_NONE: Final = "none"
STATUS_BRIEF_WRITTEN: Final = "brief_written"
STATUS_IMPORTED: Final = "imported"
STATUS_REVIEWED: Final = "reviewed"

NO_CLAIMS_MESSAGE: Final = "There are no claims to prove, so there is nothing to research."
CURRENT_MESSAGE: Final = (
    "The newest round already has these claims. Change a claim to write a new brief."
)
ALL_REVIEWED_MESSAGE: Final = (
    "Every claim already has reviewed evidence. Add or change a claim to write a new brief."
)
NOT_SEPARATE_MESSAGE: Final = (
    "Evidence needs the files folder on the Mac (VISIO_FILES_DIR in .env), because the research "
    "agent works in it."
)
_ROUND_FOLDER_TRIES: Final = 1000


class EvidenceRoundsError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- The brief (pure) ----------------------------------------------------------------------


def sentence_spans(script: str) -> list[tuple[int, int]]:
    """The `(start, end)` of each sentence of the script. The spans cover the whole script."""
    spans: list[tuple[int, int]] = []
    position = 0
    for piece in sentences(script):
        spans.append((position, position + len(piece)))
        position += len(piece)
    return spans


def _one_line(text: str) -> str:
    return " ".join(text.split())


def brief_claims(script: str, claims: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The claims as the brief states them (§4.4), in story order. `sentence` is the whole
    sentence the words are in (or the sentences, when they span a sentence end), and `context`
    the sentence before and the sentence after. Each is one line of text. Pure.
    """
    spans = sentence_spans(script)
    entries: list[dict[str, Any]] = []
    # Only a round with a sound bite says `want` and `speaker`, so every other brief stays as it
    # was before sound bites.
    with_want = any(evidence_claims.is_soundbite(claim) for claim in claims)
    for claim in sorted(claims, key=lambda item: item["start"]):
        start, end = claim["start"], claim["end"]
        first = next((i for i, (_, stop) in enumerate(spans) if stop > start), len(spans) - 1)
        last = next(
            (i for i in range(len(spans) - 1, -1, -1) if spans[i][0] < end),
            first,
        )
        last = max(first, last)
        sentence = script[spans[first][0] : spans[last][1]] if spans else claim["text"]
        around = [
            script[spans[index][0] : spans[index][1]]
            for index in (first - 1, last + 1)
            if 0 <= index < len(spans)
        ]
        entry = {
            "id": claim["id"],
            "origin": claim["origin"],
            "text": claim["text"],
            "sentence": _one_line(sentence),
            "context": _one_line(" ".join(around)),
            "hint": claim["hint"],
            "kind_hint": claim["kind_hint"],
        }
        if with_want:
            entry["want"] = claim.get("want", evidence_claims.WANT_EVIDENCE)
            entry["speaker"] = claim.get("speaker")
        entries.append(entry)
    return entries


def claim_key(entry: object) -> tuple[Any, ...]:
    """What decides that a round holds a claim as it is now: not the sentences around it. A
    brief with no sound bite does not say `want` and `speaker` (a claim is then evidence, and has
    no speaker), so a missing one reads as that. Pure. Anything that is not a claim entry gives a
    key no claim has.
    """
    if not isinstance(entry, dict):
        return ()
    return (
        entry.get("id"),
        entry.get("origin"),
        entry.get("text"),
        entry.get("sentence"),
        entry.get("hint"),
        entry.get("kind_hint"),
        entry.get("want") or evidence_claims.WANT_EVIDENCE,
        entry.get("speaker"),
    )


def claim_keys(entries: Sequence[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """`claim_key` of each entry. Pure."""
    return [claim_key(entry) for entry in entries]


def keys_by_id(entries: object) -> dict[str, tuple[Any, ...]]:
    """The `claim_key` of each claim entry that has an id, by id. Pure."""
    found: dict[str, tuple[Any, ...]] = {}
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            found[entry["id"]] = claim_key(entry)
    return found


def pending_reasons(claims: Sequence[dict[str, Any]]) -> list[str]:
    """Why the claims cannot be sent to research yet, as sentences for the owner. Empty when
    they can. `claims` are as `evidence_claims.state()` gives them. Pure.

    A proposal of GLM that the owner has not decided on, and a claim whose words changed in the
    story, both need the owner. A proposal whose words changed is not asked about: it cannot be
    kept. So does a sound bite whose quote no longer passes the rule of SB-005 (it carries
    `soundbite_block`, as `evidence_claims.state()` gives it).
    """
    reasons: list[str] = []
    undecided = [
        claim
        for claim in claims
        if evidence_claims.is_undecided(claim) and not claim["words_changed"]
    ]
    if undecided:
        many = len(undecided) > 1
        reasons.append(
            f"Keep or drop the {len(undecided)} claim{'s' if many else ''} GLM proposed."
        )
    changed = [
        claim
        for claim in claims
        if evidence_claims.is_active(claim)
        and claim["words_changed"]
        and not evidence_claims.is_undecided(claim)
    ]
    if changed:
        many = len(changed) > 1
        reasons.append(
            f"The words of {len(changed)} claim{'s' if many else ''} changed in the story: mark "
            f"{'them' if many else 'it'} again or remove {'them' if many else 'it'}."
        )
    broken = [
        claim
        for claim in claims
        if evidence_claims.is_active(claim)
        and evidence_claims.is_soundbite(claim)
        and not claim["words_changed"]
        and claim.get("soundbite_block") is not None
    ]
    if broken:
        many = len(broken) > 1
        reasons.append(
            f"The quote of {len(broken)} sound bite{'s' if many else ''} is no longer whole "
            "sentences in quotation marks: fix the story or make "
            f"{'them' if many else 'it'} ordinary evidence."
        )
    return reasons


def build_brief(
    *,
    round_id: str,
    project_id: int,
    title: str,
    orientation: str,
    topic: str,
    today: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """`brief/claims.json` exactly as §4.4 states it. Pure. The version is 2 when the entries
    carry `want` (a round with a sound bite) and 1 otherwise.
    """
    version = (
        BRIEF_VERSION_SOUNDBITE
        if any("want" in entry for entry in entries)
        else BRIEF_VERSION_PLAIN
    )
    return {
        "schema": BRIEF_SCHEMA,
        "version": version,
        "round_id": round_id,
        "project": {
            "id": project_id,
            "title": title,
            "topic": topic,
            "orientation": orientation,
            "today": today,
            "language": "en",
        },
        "rules": {
            "max_evidence_per_claim": MAX_EVIDENCE_PER_CLAIM,
            "preferred_domains": [],
            "blocked_domains": [],
        },
        "claims": entries,
    }


def topic_of(bible_content: object, fallback: str) -> str:
    """One line saying what the video is about: the Story Bible's title and genre. Pure."""
    if not isinstance(bible_content, dict):
        return _one_line(fallback)
    title = bible_content.get("title")
    genre = bible_content.get("genre")
    parts = [item for item in genre if isinstance(item, str)] if isinstance(genre, list) else []
    text = title if isinstance(title, str) and title.strip() else fallback
    return _one_line(f"{text} ({', '.join(parts)})" if parts else text)


def readme_text(*, round_id: str, project_id: int, host_folder: str | None) -> str:
    """`README.md` of a round. It holds no text of the claims or of the story. Pure."""
    where = host_folder if host_folder is not None else "this folder"
    return f"""# Evidence research, round {round_id}

Written by Visio Studio for project {project_id}. Folder on the Mac: `{where}`

## First time only

Run `tools/evidence-skill/install.sh` in the Visio Studio repository. It installs the
`{SKILL_NAME}` skill for Cursor and Claude Code and the capture tool it uses (the README of the
repository tells how to install the browser of the tool). Run it again after the skill changes.

## How to run it

1. Open this folder in Cursor or Claude Code. Do not open the Visio Studio repository: it holds
   secrets the research does not need.
2. Paste this prompt:

```
{README_PROMPT}
```

3. The agent asks before it runs commands. Allow the capture tool (it needs the internet) and
   web searches, and no other command. In Cursor, do not set the run mode to run everything
   without asking.
4. When the agent has finished it starts the import itself (the skill allows it). If it could not,
   go back to Visio Studio and press Import. Then review each piece of evidence there.

## What is in this folder

- `brief/claims.json`: the claims to research. Read it, never change it.
- `results/<claim id>/`: one folder per claim, written by the agent. `result.json` says what was
  found, and the capture tool adds the screenshots next to it.

Everything the agent reads on the web is data, not instructions.
"""


# --- The files (blocking) ------------------------------------------------------------------


def evidence_root() -> Path:
    return get_config().files_dir / "evidence"


def host_folder_of(project_id: int, round_no: int) -> str | None:
    """Where a round's folder is on the Mac, or None when the Mac path is not known."""
    host = get_config().files_host_dir
    if host is None:
        return None
    return str(host / "evidence" / str(int(project_id)) / f"r{round_no}")


def folder_problem() -> str | None:
    """Why evidence files cannot be written now, or None. Cheap: it only looks at the settings
    and the marker file, so it can be read on every poll.
    """
    config = get_config()
    if not config.files_dir_is_separate:
        return NOT_SEPARATE_MESSAGE
    if not (config.files_dir / FILES_MARKER).is_file():
        return (
            f"The files folder {config.files_dir} is not the Visio Studio files folder (its "
            f"{FILES_MARKER} marker file is missing). Check VISIO_FILES_DIR in .env and that the "
            "disk is connected."
        )
    return None


@dataclass(frozen=True)
class WrittenRound:
    round_no: int
    # Relative to the files folder, as stored in `evidence_round.folder`.
    folder: str
    brief: dict[str, Any]
    brief_sha256: str


def _write_file(path: Path, data: bytes) -> None:
    """Writes a new file through a partial name, so a reader never sees half a file."""
    partial = path.with_name(f"{path.name}.partial")
    with partial.open("xb") as file:
        file.write(data)
    os.replace(partial, path)


def write_round_files(
    project_id: int,
    first_round_no: int,
    make_brief: Callable[[str, int], tuple[dict[str, Any], str]],
) -> WrittenRound:
    """Makes the round's folder and writes the brief. Blocking: call it from a thread.

    The round number is the first from `first_round_no` whose folder does not exist yet (a
    folder left by an earlier round with no row is never written into). `make_brief(round_id,
    round_no)` returns the brief and the text of the README.
    """
    root = evidence_root()
    project_folder = root / str(int(project_id))
    project_folder.mkdir(parents=True, exist_ok=True)
    round_no = first_round_no
    for _ in range(_ROUND_FOLDER_TRIES):
        folder = project_folder / f"r{round_no}"
        try:
            folder.mkdir()
            break
        except FileExistsError:
            round_no += 1
    else:
        raise EvidenceRoundsError("No free round folder was found.")
    try:
        brief_dir = folder / "brief"
        brief_dir.mkdir()
        (folder / "results").mkdir()
        brief, readme = make_brief(f"r{round_no}", round_no)
        data = (json.dumps(brief, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _write_file(brief_dir / "claims.json", data)
        _write_file(brief_dir / "README.md", readme.encode("utf-8"))
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return WrittenRound(
        round_no=round_no,
        folder=f"evidence/{int(project_id)}/r{round_no}",
        brief=brief,
        brief_sha256=hashlib.sha256(data).hexdigest(),
    )


def discard_round_folder(project_id: int, round_no: int) -> None:
    """Removes a round folder written for a row that could not be saved. Blocking."""
    root = evidence_root().resolve()
    folder = (root / str(int(project_id)) / f"r{int(round_no)}").resolve()
    if folder.parent.parent != root or not folder.is_dir() or folder.is_symlink():
        return
    shutil.rmtree(folder, ignore_errors=True)


async def discard_round(project_id: int, round_no: int) -> None:
    """`discard_round_folder` from async code."""
    await anyio.to_thread.run_sync(discard_round_folder, project_id, round_no)


def _remove_project_folder(folder: Path, root: Path) -> bool:
    if folder.is_symlink() or not folder.is_dir():
        return False
    if folder.resolve().parent != root:
        raise StorageError(f"Not an evidence folder: {folder}")
    shutil.rmtree(folder)
    return True


async def remove_project_folder(project_id: int) -> bool:
    """Removes `evidence/<project_id>/` and everything in it, with the project. Only that one
    folder directly under `evidence/` is ever touched. Returns False when there was none, or
    when the files folder is not the right one. Raises StorageError or OSError.
    """
    if folder_problem() is not None:
        return False
    root = evidence_root().resolve()
    folder = root / str(int(project_id))
    return await anyio.to_thread.run_sync(_remove_project_folder, folder, root)


# --- Where a round stands --------------------------------------------------------------------


async def latest_round(session: AsyncSession, project_id: int) -> EvidenceRound | None:
    """The project's newest round (the highest round number), or None."""
    statement = (
        select(EvidenceRound)
        .where(EvidenceRound.project_id == project_id)
        .order_by(EvidenceRound.round_no.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalars().first()


async def round_status(session: AsyncSession, row: EvidenceRound | None) -> str:
    """Where a round stands: `none`, `brief_written`, `imported` or `reviewed`. The one place
    that says so; the import (EVD-006) and the review (EVD-007) only add rows.
    """
    if row is None:
        return STATUS_NONE
    newest_import = (
        await session.execute(
            select(EvidenceImport.id)
            .where(EvidenceImport.round_id == row.id)
            .order_by(EvidenceImport.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if newest_import is None:
        return STATUS_BRIEF_WRITTEN
    review = (
        (
            await session.execute(
                select(EvidenceReview)
                .where(EvidenceReview.round_id == row.id)
                .order_by(EvidenceReview.version.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    inputs = review.inputs if review is not None else None
    if (
        review is not None
        and review.done
        and isinstance(inputs, dict)
        and inputs.get("import_id") == newest_import
    ):
        return STATUS_REVIEWED
    return STATUS_IMPORTED


@dataclass(frozen=True)
class EvidenceState:
    """What the evidence panel and the pipeline step read."""

    # A continuous explainer with `evidence` on.
    wanted: bool
    # The claims that count and sit in the story now (never straight from a row).
    claims: list[dict[str, Any]]
    # Why the claims cannot be sent to research yet (`pending_reasons`).
    pending: list[str]
    round: EvidenceRound | None
    status: str
    # The newest round holds every waiting claim unchanged: a new brief would add nothing.
    current: bool
    job: Job | None
    # Why evidence files cannot be written now, or None.
    folder_problem: str | None
    host_folder: str | None
    # OVL-006. The claims that count and have a covering round, by claim id: the newest reviewed
    # round whose brief holds the claim as it is now.
    covered: dict[str, EvidenceRound] = field(default_factory=dict)
    # The claims that count and have no covering round yet, in story order: what a new brief
    # carries, and what the evidence step still waits for.
    waiting: list[dict[str, Any]] = field(default_factory=list)
    # The newest round holds at least one claim that counts, unchanged, so it can still be
    # imported and reviewed.
    live: bool = False


async def all_rounds(session: AsyncSession, project_id: int) -> list[EvidenceRound]:
    """The project's rounds, newest first."""
    statement = (
        select(EvidenceRound)
        .where(EvidenceRound.project_id == project_id)
        .order_by(EvidenceRound.round_no.desc())
    )
    return list((await session.execute(statement)).scalars().all())


async def _coverage(
    session: AsyncSession,
    rounds: Sequence[EvidenceRound],
    wanted: dict[str, tuple[Any, ...]],
) -> dict[str, EvidenceRound]:
    """For each claim of `wanted` (id to key), the newest reviewed round whose brief holds it with
    that key. A round's standing is only worked out when it holds one of the claims."""
    covered: dict[str, EvidenceRound] = {}
    for row in rounds:
        if len(covered) == len(wanted):
            break
        held = keys_by_id(row.brief.get("claims") if isinstance(row.brief, dict) else None)
        mine = [
            claim_id
            for claim_id, key in wanted.items()
            if claim_id not in covered and held.get(claim_id) == key
        ]
        if mine and await round_status(session, row) == STATUS_REVIEWED:
            for claim_id in mine:
                covered[claim_id] = row
    return covered


@memoized_state
async def state(session: AsyncSession, project: Project) -> EvidenceState:
    """Where the project's evidence stands. Worked out on every read. A project without evidence
    reads nothing from the tables (EVD-001).
    """
    if not evidence_claims.wanted(project):
        return EvidenceState(
            wanted=False,
            claims=[],
            pending=[],
            round=None,
            status=STATUS_NONE,
            current=False,
            job=None,
            folder_problem=None,
            host_folder=None,
        )
    all_claims = (await evidence_claims.state(session, project)).claims
    claims = evidence_claims.counting(all_claims)
    rounds = await all_rounds(session, project.id)
    row = rounds[0] if rounds else None
    current = False
    live = False
    covered: dict[str, EvidenceRound] = {}
    waiting = claims
    if project.script_text is not None:
        wanted = keys_by_id(brief_claims(project.script_text, claims))
        covered = await _coverage(session, rounds, wanted)
        waiting = [claim for claim in claims if claim["id"] not in covered]
        if row is not None:
            held = keys_by_id(row.brief.get("claims") if isinstance(row.brief, dict) else None)
            live = any(held.get(claim_id) == key for claim_id, key in wanted.items())
            current = all(held.get(claim["id"]) == wanted.get(claim["id"]) for claim in waiting)
    return EvidenceState(
        wanted=True,
        claims=claims,
        pending=pending_reasons(all_claims),
        round=row,
        status=await round_status(session, row),
        current=current,
        job=await store.latest_job(session, project.id, JOB_TYPE),
        folder_problem=folder_problem(),
        host_folder=host_folder_of(project.id, row.round_no) if row is not None else None,
        covered=covered,
        waiting=waiting,
        live=live,
    )


def refusal(current: EvidenceState, project: Project) -> str | None:
    """Why a brief cannot be written now, or None."""
    if not current.wanted:
        return evidence_claims.OFF_MESSAGE
    if project.script_text is None:
        return evidence_claims.NO_STORY_MESSAGE
    if current.pending:
        return " ".join(current.pending)
    if not current.claims:
        return NO_CLAIMS_MESSAGE
    if not current.waiting:
        return ALL_REVIEWED_MESSAGE
    if current.round is not None and current.current:
        return CURRENT_MESSAGE
    return current.folder_problem


def awaiting_text(current: EvidenceState) -> str | None:
    """What the owner has to do before the `evidence` step can go on, or None when it waits for
    nothing from the owner (it is done, or a brief has to be written).
    """
    if not current.wanted:
        return None
    if current.pending:
        return " ".join(current.pending)
    if not current.claims or not current.waiting:
        return None
    if current.round is None or not current.current:
        return None
    # With claims already reviewed, say that they stay on video while the new ones wait.
    reviewed = len(current.covered)
    kept = (
        f" ({len(current.waiting)} new {'claim' if len(current.waiting) == 1 else 'claims'}; "
        f"the {reviewed} reviewed {'claim stays' if reviewed == 1 else 'claims stay'} on video)"
        if reviewed
        else ""
    )
    if current.status == STATUS_BRIEF_WRITTEN:
        folder = current.host_folder or current.round.folder
        return (
            f"Run the research in {folder} with Cursor or Claude{kept}, "
            "then import the results here."
        )
    if current.status == STATUS_IMPORTED:
        return "Review the evidence, then press Review done."
    return None


def is_done(current: EvidenceState) -> bool:
    """The `evidence` step is complete: nothing to prove, or every claim that counts is covered by
    a reviewed round (nothing is waiting). Not applicable also counts (the caller checks
    `wanted`).
    """
    if not current.wanted:
        return True
    if current.pending:
        return False
    return not current.waiting


# --- Starting a brief ------------------------------------------------------------------------


async def start_brief(session: AsyncSession, project: Project) -> Job:
    """Queues the job that writes the next round's brief. If one is already waiting or running,
    that job is returned. Raises EvidenceRoundsError with the reason when a brief cannot be
    written now (`refusal`). Commits.
    """
    current = await state(session, project)
    reason = refusal(current, project)
    if reason is not None:
        raise EvidenceRoundsError(reason)
    row = await evidence_claims.latest(session, project.id)
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="local",
        input={"claim_list_version": row.version if row is not None else None},
    )
    return job


async def next_round_no(session: AsyncSession, project_id: int) -> int:
    highest = (
        await session.execute(
            select(func.max(EvidenceRound.round_no)).where(EvidenceRound.project_id == project_id)
        )
    ).scalar_one_or_none()
    return (highest or 0) + 1


async def make_round(session: AsyncSession, project: Project, job_id: int) -> EvidenceRound:
    """Writes the next round: its folder and brief, and its row (flushed, not committed: the job
    commits it with finishing itself). Raises EvidenceRoundsError when a brief cannot be written
    now. The brief is made from the claims and the story as they are now.
    """
    current = await state(session, project)
    reason = refusal(current, project)
    if reason is not None:
        raise EvidenceRoundsError(reason)
    script = project.script_text
    claim_list = await evidence_claims.latest(session, project.id)
    if script is None or claim_list is None:
        raise EvidenceRoundsError(evidence_claims.NO_STORY_MESSAGE)
    bible = await story_bible.latest(session, project.id)
    topic = topic_of(bible.content if bible is not None else None, project.name)
    # Only the claims that wait for research (OVL-006): the reviewed ones stay as they are.
    entries = brief_claims(script, current.waiting)
    today = utcnow().date().isoformat()
    # Plain values, read here: the brief is made in a thread, where the project is not touched.
    project_id, title, orientation = project.id, project.name, project.orientation

    def make_brief(round_id: str, round_no: int) -> tuple[dict[str, Any], str]:
        brief = build_brief(
            round_id=round_id,
            project_id=project_id,
            title=title,
            orientation=orientation,
            topic=topic,
            today=today,
            entries=entries,
        )
        readme = readme_text(
            round_id=round_id,
            project_id=project_id,
            host_folder=host_folder_of(project_id, round_no),
        )
        return brief, readme

    first = await next_round_no(session, project.id)
    written = await anyio.to_thread.run_sync(write_round_files, project.id, first, make_brief)
    row = EvidenceRound(
        project_id=project.id,
        round_no=written.round_no,
        claim_list_id=claim_list.id,
        job_id=job_id,
        folder=written.folder,
        brief=written.brief,
        brief_sha256=written.brief_sha256,
    )
    try:
        session.add(row)
        await session.flush()
    except BaseException:
        await discard_round(project_id, written.round_no)
        raise
    return row
