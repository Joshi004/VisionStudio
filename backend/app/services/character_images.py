"""The Canonical Character Images stage of a story project (PHASE-010, `Path_ahead.md` Section 11).

Each discovered character that has a definition (`services/character_definitions.py`) gets one
look made by the story pipeline, by reusing the Character Lab's look pipeline
(`services/character_looks.py`):

1. `start_look(automatic=...)` starts a `write_character_look_prompt` job. The prompt is
   written from the library character's card, which the definition has filled in
   (`character_definition_writer.to_profile`), so the definition is read through the card.
2. **One** candidate picture is made and taken as the master as soon as it is stored (D-5), so
   nobody chooses. A look made by hand in the lab still makes four to choose from.
3. The four other angles are made from the master. When all five exist the look is `ready`,
   the library character gets a new version (`source = "ai"`) holding the look, and the
   project's pin moves to it (`character_looks._pin_pipeline_look`).

Re-choosing a master by hand is the lab's own "New look": it writes a `manual` version and
never moves a pin.

- `start_run` starts one character's look. It refuses, readably, a character that is not
  linked, not defined, whose definition is out of date, that is archived, or that was chosen
  from the library (`how = "mapped"`) when `confirm_overwrite` is not given, because making a
  look changes that library character's current look.
- `start_all` starts a look for every defined character the pipeline made that has no images
  yet or whose images are out of date, skipping (with the reason) the others.
- `state` is what the story workspace shows: per entry its definition's state, the newest look
  the pipeline made for it, its progress, why it failed and whether its images are out of
  date. **All of it is worked out on every read** and never stored (D-3): a look is
  `failed` when its own status says so or when the job of its candidate, its prompt or an
  angle failed; it is `out_of_date` when the definition it read differs from the one the project
  pins now.

There is no job type of its own: the work is the lab's jobs. A retry after a failure is a fresh
look; one angle can be made again with the lab's own "redo angle".

**Relations** (PHASE-047, `services/character_relations.py`). A character that is the same
person as another (a younger self, an older self, a twin) is drawn by editing the base
character's front picture, so both have one face: it needs the base's images first. When the
base's images are being made the variant's look is `waiting`, and `release_waiting` starts it
when the base's pinned version holds its front picture (`on_angle_image_stored`, called by the
image job). A character with family (a parent, a sibling, a grandparent) is drawn from its own
card plus the relatives' skin tone, eyes, face shape and hair, as words: no picture is edited.
A look records what it was made from (`inputs.base`, `inputs.relation_kind`,
`inputs.resemblance_sha256`), so it is out of date when the base's picture, the relation or a
relative's traits change.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CharacterLook,
    CharacterReference,
    Job,
    LabRun,
    LibraryCharacterVersion,
    Project,
)
from app.db.session import SessionLocal
from app.jobs import store
from app.services import (
    character_definitions,
    character_library,
    character_looks,
    character_relations,
    image_lab,
)
from app.services.character_definitions import EntryDefinition
from app.services.character_links import LinkInfo

_logger = logging.getLogger(__name__)

# The statuses of a job that will not produce a picture any more.
_DEAD_JOB_STATUSES: Final = ("failed", "cancelled")
_ACTIVE_LOOK_STATUSES: Final = ("waiting", "writing_prompt", "choosing", "making_angles")
_ALREADY_BEING_MADE: Final = "The images are already being made."

# `unavailable`: no look yet, and one cannot be started (see `blocked_reason`).
# `none`: no look yet, and one can be started.
# `in_progress`: a look is being made. `failed`: something it needs did not work.
# `ready`: five angles, pinned. `out_of_date`: ready, but made from an older definition.
Status = Literal["unavailable", "none", "in_progress", "failed", "ready", "out_of_date"]
# Where an `in_progress` look is: waiting for the images of the character it is drawn from,
# writing its prompt, drawing the master, or making the angles.
Stage = Literal["waiting_for_base", "writing_prompt", "making_master", "making_angles"]


class CharacterImageError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class FailedAngle:
    angle: str
    error: str | None


@dataclass(frozen=True)
class EntryImages:
    """One entry of the newest list of characters and where its canonical images stand."""

    definition: EntryDefinition
    status: Status
    # The newest look the pipeline made for this entry's current library character, whatever
    # its status. None when there is none.
    look: CharacterLook | None
    stage: Stage | None
    # How many of the five angles have a picture.
    angles_ready: int
    failed_angles: list[FailedAngle]
    # Why a `failed` look failed.
    error: str | None
    # Why a `ready` look is out of date, one sentence each. Empty unless `out_of_date`.
    reasons: list[str] = field(default_factory=list)
    can_run: bool = False
    blocked_reason: str | None = None
    # True for a character chosen from the library: a look changes its current look, so the
    # user is asked first.
    needs_confirmation: bool = False
    # The character this one is drawn from (a same-face relation, PHASE-047): its id, its name
    # and the kind of relation. None for any other character.
    made_from: MadeFrom | None = None
    # The part of `blocked_reason` that is only that the base has no images and none are being
    # made yet. "Make images for all" starts the base first and lifts it.
    base_refusal: str | None = None


@dataclass(frozen=True)
class MadeFrom:
    discovery_id: str
    name: str
    kind: str


@dataclass(frozen=True)
class Front:
    """The front picture of a character's pinned version: the lab image a same-face variant is
    edited from.
    """

    version: int
    look_id: int | None
    lab_image_id: int


@dataclass(frozen=True)
class _Plan:
    """What the project's relations say about how one character is drawn."""

    # The same-face base (a discovered character's id and name) and the kind, or None.
    base_id: str | None
    base_name: str | None
    kind: str | None
    # The family likeness as text, or None.
    resemblance: str | None


@dataclass(frozen=True)
class ImagesState:
    """What the story workspace shows. `discovery_version` is None when no list exists."""

    discovery_version: int | None
    entries: list[EntryImages]
    # What `_start` needs, by the entry's id: how each character is drawn, and the front
    # picture of each linked character's pinned version.
    plans: dict[str, _Plan] = field(default_factory=dict)
    fronts: dict[str, Front | None] = field(default_factory=dict)


@dataclass(frozen=True)
class Skipped:
    """An entry that "Make images for all" did not start, and why."""

    discovery_id: str
    name: str
    reason: str


@dataclass(frozen=True)
class StartAllResult:
    look_ids: list[int]
    skipped: list[Skipped]


# --- Inputs -------------------------------------------------------------------------------


def definition_sha256(definition: dict[str, Any]) -> str:
    """A name for the definition a look was made from."""
    text = json.dumps(definition, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text_sha256(text: str | None) -> str:
    """A name for a piece of text. The empty string for no text, which is also what a look made
    before relations existed counts as having recorded.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


# --- Reading the state --------------------------------------------------------------------


@dataclass(frozen=True)
class Progress:
    stage: Stage | None
    angles_ready: int
    failed_angles: list[FailedAngle]
    error: str | None


def job_error(job: Job, what: str) -> str:
    if job.error:
        return job.error
    return f"The {what} was cancelled." if job.status == "cancelled" else f"The {what} failed."


async def look_progress(session: AsyncSession, look: CharacterLook) -> Progress:
    """Where one look stands, from its own status and the jobs of the step it is in."""
    if look.status == "ready":
        return Progress(None, len(character_library.ANGLES), [], None)
    if look.status == "failed":
        return Progress(None, 0, [], look.error or "The look failed.")

    if look.status == "waiting":
        return Progress("waiting_for_base", 0, [], None)

    if look.status == "writing_prompt":
        prompt_job = (
            await session.get(Job, look.prompt_job_id) if look.prompt_job_id is not None else None
        )
        if prompt_job is not None and prompt_job.status in _DEAD_JOB_STATUSES:
            error = job_error(prompt_job, "image prompt")
            return Progress(None, 0, [], f"The look's prompt could not be written: {error}")
        return Progress("writing_prompt", 0, [], None)

    if look.status == "choosing":
        candidates = await character_looks.candidates_for(session, look.id)
        run_ids = [c.lab_run_id for c in candidates if c.lab_run_id is not None]
        jobs = await image_lab.jobs_for_runs(session, await _runs(session, run_ids))
        if jobs and all(job.status in _DEAD_JOB_STATUSES for job in jobs.values()):
            first = next(iter(jobs.values()))
            error = job_error(first, "master picture")
            return Progress(None, 0, [], f"The master picture could not be made: {error}")
        return Progress("making_master", 0, [], None)

    # making_angles: each angle's row is filled once its picture is stored.
    references = await character_looks.references_for_look(session, look.id)
    run_ids = [r.lab_run_id for r in references if r.lab_image_id is None and r.lab_run_id]
    jobs = await image_lab.jobs_for_runs(session, await _runs(session, run_ids))
    ready = 0
    pending = 0
    failed: list[FailedAngle] = []
    for reference in references:
        if reference.lab_image_id is not None:
            ready += 1
            continue
        job = jobs.get(reference.lab_run_id or 0)
        if job is not None and job.status in _DEAD_JOB_STATUSES:
            failed.append(FailedAngle(reference.angle, job_error(job, "picture")))
        else:
            pending += 1
    if failed and pending == 0:
        names = ", ".join(item.angle.replace("_", " ") for item in failed)
        return Progress(None, ready, failed, f"These angles could not be made: {names}.")
    return Progress("making_angles", ready, failed, None)


async def _runs(session: AsyncSession, run_ids: list[int]) -> list[LabRun]:
    if not run_ids:
        return []
    found = await session.execute(select(LabRun).where(LabRun.id.in_(run_ids)))
    return list(found.scalars())


def _out_of_date_reasons(look: CharacterLook, entry: EntryDefinition) -> list[str]:
    """Why a ready look no longer matches the definition the project pins, if it does not."""
    definition = entry.definition
    inputs = look.inputs if isinstance(look.inputs, dict) else {}
    if definition is None:
        return []
    if inputs.get("definition_sha256") != definition_sha256(definition):
        return ["The character's definition has changed since these images were made."]
    return []


def _start_refusal(entry: EntryDefinition) -> str | None:
    """Why images cannot be made for this entry now, or None when they can."""
    info = entry.entry.info
    name = entry.item["name"]
    if info is None:
        return f"'{name}' is not linked to a Character Lab character yet. Link it first."
    if info.character.archived:
        return f"{info.character.name} is archived. Unarchive it in the Character Lab first."
    if entry.job is not None and entry.job.status in store.ACTIVE_STATUSES:
        return "A definition is being written. Wait for it to finish."
    if entry.status == "not_defined":
        return f"{name} has no definition yet. Define the character first: it is drawn from it."
    if entry.status == "out_of_date":
        return f"The definition of {name} is out of date. Define the character again first."
    return None


async def _newest_looks(
    session: AsyncSession, project_id: int
) -> dict[tuple[str, int], CharacterLook]:
    """The newest pipeline look of each `(discovered character id, library character id)`."""
    statement = (
        select(CharacterLook)
        .where(
            CharacterLook.project_id == project_id,
            CharacterLook.discovery_id.is_not(None),
            # The pictures of a named look (PHASE-017) are not the character's canonical images.
            CharacterLook.named_look_id.is_(None),
        )
        .order_by(CharacterLook.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[tuple[str, int], CharacterLook] = {}
    for look in (await session.execute(statement)).scalars():
        key = (look.discovery_id or "", look.character_id)
        if key not in newest:
            newest[key] = look
    return newest


# How a relative's traits are named in the family likeness, and the keys of the definition's
# `visual_identity` they come from.
_LIKENESS_TRAITS: Final = (
    ("skin tone", "skin_tone"),
    ("eyes", "eyes"),
    ("face shape", "face_shape"),
    ("hair", "hair"),
)


async def pinned_front(session: AsyncSession, info: LinkInfo) -> Front | None:
    """The front picture of the character's pinned version, or None when that version holds no
    look.
    """
    statement = select(LibraryCharacterVersion).where(
        LibraryCharacterVersion.character_id == info.character.id,
        LibraryCharacterVersion.version == info.link.pinned_version,
    )
    version = (await session.execute(statement)).scalars().first()
    if version is None:
        return None
    for picture in version.look_references or []:
        if (
            isinstance(picture, dict)
            and picture.get("angle") == "front"
            and isinstance(picture.get("lab_image_id"), int)
        ):
            return Front(version.version, version.look_id, picture["lab_image_id"])
    return None


def _likeness(
    entry_id: str, relations: list[dict[str, str]], entries: dict[str, EntryDefinition]
) -> str | None:
    """The family likeness of a character as text: for each relative that has a definition,
    what the relative is to it and the relative's skin tone, eyes, face shape and hair. No
    names. None when there is no such relative.
    """
    parts: list[str] = []
    for relation in character_relations.family_of(relations, entry_id):
        other_id = relation["of"] if relation["character"] == entry_id else relation["character"]
        other = entries.get(other_id)
        if other is None or other.definition is None:
            continue
        role = character_relations.relation_to(relations, entry_id, other_id)
        identity = other.definition.get("visual_identity")
        if role is None or not isinstance(identity, dict):
            continue
        traits = [
            f"{label} {identity[key]}"
            for label, key in _LIKENESS_TRAITS
            if isinstance(identity.get(key), str) and identity[key].strip()
        ]
        if traits:
            parts.append(f"{role}: {', '.join(traits)}")
    return "; ".join(parts) or None


def _plan_for(
    entry_id: str, relations: list[dict[str, str]], entries: dict[str, EntryDefinition]
) -> _Plan:
    """How the project's relations say this character is drawn: from its same-face base's
    picture, or with its relatives' likeness as words.
    """
    base = character_relations.same_face_base(relations, entry_id)
    if base is not None:
        base_entry = entries.get(base["of"])
        name = base_entry.item["name"] if base_entry is not None else base["of"]
        return _Plan(base["of"], name, base["kind"], None)
    return _Plan(None, None, None, _likeness(entry_id, relations, entries))


def _relation_reasons(
    look: CharacterLook, plan: _Plan, fronts: dict[str, Front | None]
) -> list[str]:
    """Why a ready look no longer matches what the project's relations say now, if it does not.
    A look made before relations existed recorded none, which is what a character with no
    relations reads as.
    """
    inputs = look.inputs if isinstance(look.inputs, dict) else {}
    recorded_base = inputs.get("base") if isinstance(inputs.get("base"), dict) else {}
    reasons: list[str] = []
    if (
        inputs.get("relation_kind") != plan.kind
        or recorded_base.get("discovery_id") != plan.base_id
    ):
        reasons.append("The character's relations have changed since these images were made.")
    elif plan.base_id is not None:
        front = fronts.get(plan.base_id)
        if front is not None and front.lab_image_id != recorded_base.get("front_lab_image_id"):
            reasons.append(f"{plan.base_name}'s images have changed since these were made.")
    if inputs.get("resemblance_sha256", "") != _text_sha256(plan.resemblance):
        reasons.append("A relative's looks have changed since these images were made.")
    return reasons


def _with_relations(
    item: EntryImages,
    plan: _Plan,
    by_id: dict[str, EntryImages],
    fronts: dict[str, Front | None],
) -> EntryImages:
    """The entry with what the project's relations add: the character it is drawn from, why a
    waiting look cannot go on, why a variant cannot start, and why a ready look is out of date.
    """
    if plan.base_id is None or plan.base_name is None or plan.kind is None:
        made_from = None
    else:
        made_from = MadeFrom(plan.base_id, plan.base_name, plan.kind)
    status, stage, error = item.status, item.stage, item.error
    reasons = list(item.reasons)
    blocked, base_refusal = item.blocked_reason, None

    if made_from is not None:
        base = by_id[made_from.discovery_id]
        base_in_progress = base.status == "in_progress"
        if item.look is not None and item.look.status == "waiting" and not base_in_progress:
            # Nothing will release it: the images it waits for are not being made.
            status, stage = "failed", None
            if blocked == _ALREADY_BEING_MADE:
                blocked = None
            error = (
                f"{made_from.name}'s images could not be made, so these were not started. "
                "Make them again."
                if base.status == "failed"
                else f"{made_from.name}'s images are not being made, so these did not start. "
                "Make them again."
            )
        elif (
            blocked is None
            and status != "in_progress"
            and not base_in_progress
            and fronts.get(made_from.discovery_id) is None
        ):
            base_refusal = (
                f"Make images for {made_from.name} first: {item.definition.item['name']} is "
                "drawn from its picture."
            )
            blocked = base_refusal
            if status == "none":
                status = "unavailable"

    if item.look is not None and status in ("ready", "out_of_date") and item.look.status == "ready":
        reasons.extend(_relation_reasons(item.look, plan, fronts))
        status = "out_of_date" if reasons else "ready"

    return replace(
        item,
        status=status,
        stage=stage,
        error=error,
        reasons=reasons,
        can_run=blocked is None,
        blocked_reason=blocked,
        made_from=made_from,
        base_refusal=base_refusal,
    )


async def state(session: AsyncSession, project: Project) -> ImagesState:
    """The newest list of characters with where each one's images stand. Worked out on every
    read; nothing here is stored.
    """
    definitions = await character_definitions.state(session, project)
    relations = (await character_relations.state(session, project)).relations
    looks = await _newest_looks(session, project.id)
    by_definition = {entry.item["id"]: entry for entry in definitions.entries}
    plans = {entry_id: _plan_for(entry_id, relations, by_definition) for entry_id in by_definition}
    fronts: dict[str, Front | None] = {}
    for entry_id, entry in by_definition.items():
        if entry.entry.info is not None:
            fronts[entry_id] = await pinned_front(session, entry.entry.info)

    first_pass: list[EntryImages] = []
    for entry in definitions.entries:
        info = entry.entry.info
        look = looks.get((entry.item["id"], info.character.id)) if info is not None else None
        refusal = _start_refusal(entry)
        progress = await look_progress(session, look) if look is not None else None

        status: Status
        reasons: list[str] = []
        if look is None or progress is None:
            status = "none" if refusal is None else "unavailable"
        elif look.status == "ready":
            reasons = _out_of_date_reasons(look, entry)
            status = "out_of_date" if reasons else "ready"
        elif progress.stage is None:
            # Not ready, and not waiting on any job: it failed.
            status = "failed"
        else:
            status = "in_progress"

        blocked = refusal
        if blocked is None and status == "in_progress":
            blocked = _ALREADY_BEING_MADE
        first_pass.append(
            EntryImages(
                definition=entry,
                status=status,
                look=look,
                stage=progress.stage if progress is not None else None,
                angles_ready=progress.angles_ready if progress is not None else 0,
                failed_angles=progress.failed_angles if progress is not None else [],
                error=progress.error if progress is not None else None,
                reasons=reasons,
                can_run=blocked is None,
                blocked_reason=blocked,
                needs_confirmation=entry.needs_confirmation,
            )
        )

    by_id = {item.definition.item["id"]: item for item in first_pass}
    entries = [
        _with_relations(item, plans[item.definition.item["id"]], by_id, fronts)
        for item in first_pass
    ]
    return ImagesState(
        discovery_version=definitions.discovery_version,
        entries=entries,
        plans=plans,
        fronts=fronts,
    )


# --- Starting runs ------------------------------------------------------------------------


def _relation(plan: _Plan, base: EntryImages, item: EntryImages) -> dict[str, Any]:
    """What the prompt job is told about a same-face variant: the kind and both ages."""

    def age(entry: EntryImages) -> int | None:
        definition = entry.definition.definition or {}
        identity = definition.get("visual_identity")
        value = identity.get("apparent_age") if isinstance(identity, dict) else None
        return value if isinstance(value, int) else None

    return {"kind": plan.kind, "base_age": age(base), "age": age(item)}


def _base_record(base: EntryImages, front: Front | None) -> dict[str, Any]:
    """What a look records about the base it is drawn from. Without `front` the look is still
    waiting for the base's picture, and only the base is named.
    """
    info = base.definition.entry.info
    record: dict[str, Any] = {
        "discovery_id": base.definition.item["id"],
        "character_id": info.character.id if info is not None else None,
    }
    if front is not None:
        record.update(
            version=front.version, look_id=front.look_id, front_lab_image_id=front.lab_image_id
        )
    return record


async def _start(
    session: AsyncSession,
    project: Project,
    item: EntryImages,
    context: ImagesState,
    started: set[str],
) -> CharacterLook:
    """Starts a fresh automatic look for an entry that `can_run`, and commits. `started` holds
    the ids of the characters whose images this same call has started already: a same-face
    variant of one of them waits for it. Raises CharacterImageError.
    """
    entry = item.definition
    info = entry.entry.info
    definition = entry.definition
    assert info is not None and definition is not None  # `_start_refusal` made sure
    entry_id = entry.item["id"]
    plan = context.plans[entry_id]

    reference_image_id: int | None = None
    relation: dict[str, Any] | None = None
    base_record: dict[str, Any] | None = None
    wait = False
    if plan.base_id is not None:
        base = next(e for e in context.entries if e.definition.item["id"] == plan.base_id)
        if base.status == "in_progress" or plan.base_id in started:
            wait = True
            base_record = _base_record(base, None)
        else:
            front = context.fronts.get(plan.base_id)
            if front is None:
                raise CharacterImageError(
                    item.base_refusal or f"Make images for {plan.base_name} first."
                )
            reference_image_id = front.lab_image_id
            relation = _relation(plan, base, item)
            base_record = _base_record(base, front)

    inputs = {
        "project_id": project.id,
        "discovery_id": entry_id,
        "character_version": info.link.pinned_version,
        "definition_sha256": definition_sha256(definition),
        "relation_kind": plan.kind,
        "base": base_record,
        "resemblance_sha256": _text_sha256(plan.resemblance),
    }
    automatic = character_looks.AutomaticLook(
        project_id=project.id, discovery_id=entry_id, inputs=inputs
    )
    try:
        look = await character_looks.start_look(
            session,
            info.character.id,
            reference_image_id,
            automatic=automatic,
            relation=relation,
            resemblance=plan.resemblance,
            wait=wait,
        )
    except character_looks.CharacterLookError as exc:
        raise CharacterImageError(str(exc)) from exc
    _logger.info(
        "project %d: images started for '%s': character=%d look=%d waiting=%s",
        project.id,
        entry_id,
        info.character.id,
        look.id,
        wait,
    )
    if wait and plan.base_id is not None and plan.base_id not in started:
        # The base may have finished while this look was being made: nothing else would
        # release it then.
        await release_waiting(session, project, plan.base_id)
    return look


async def start_run(
    session: AsyncSession,
    project: Project,
    discovery_id: str,
    *,
    confirm_overwrite: bool = False,
) -> tuple[CharacterLook, bool]:
    """Starts the look of one character, and commits. Returns `(look, created)`: when the
    character already has a look being made, that look is returned and `created` is False.

    A character the user chose from the library (`mapped`) is changed only when
    `confirm_overwrite` is true. A same-face variant needs its base's images first. Raises
    CharacterImageError.
    """
    result = await state(session, project)
    item = next((e for e in result.entries if e.definition.item["id"] == discovery_id), None)
    if item is None:
        raise CharacterImageError(
            f"There is no character '{discovery_id}' in the newest list of characters."
        )
    if item.status == "in_progress" and item.look is not None:
        return item.look, False
    if item.blocked_reason is not None:
        raise CharacterImageError(item.blocked_reason)
    if item.needs_confirmation and not confirm_overwrite:
        name = item.definition.item["name"]
        raise CharacterImageError(
            f"{name} was chosen from the Character Lab. Making images for it makes a new look "
            "its current look, so it has to be confirmed."
        )
    return await _start(session, project, item, result, set()), True


async def start_all(session: AsyncSession, project: Project) -> StartAllResult:
    """Starts a look for every defined character that the pipeline made and that has no images
    yet or whose images are out of date, and commits each. Everything else is skipped, with
    the reason. The characters other characters are drawn from go first, and a same-face
    variant of one that was just started waits for it. Raises CharacterImageError when there is
    no list of characters.
    """
    result = await state(session, project)
    if result.discovery_version is None:
        raise CharacterImageError("Find the characters first: there is nothing to draw yet.")
    look_ids: list[int] = []
    skipped: list[Skipped] = []
    started: set[str] = set()
    # False sorts first and the sort is stable: bases and everyone else, then the variants.
    ordered = sorted(
        result.entries, key=lambda e: result.plans[e.definition.item["id"]].base_id is not None
    )
    for item in ordered:
        entry_id = item.definition.item["id"]
        name = item.definition.item["name"]
        reason = _skip_reason(item, result.plans[entry_id], started)
        if reason is not None:
            skipped.append(Skipped(entry_id, name, reason))
            continue
        look = await _start(session, project, item, result, started)
        started.add(entry_id)
        look_ids.append(look.id)
    return StartAllResult(look_ids=look_ids, skipped=skipped)


def _skip_reason(item: EntryImages, plan: _Plan, started: set[str]) -> str | None:
    """Why "Make images for all" leaves this entry alone, or None when it starts it."""
    if item.status == "in_progress":
        return "Already being made."
    blocked = item.blocked_reason
    if blocked is not None and blocked == item.base_refusal and plan.base_id in started:
        # The base has no images yet, but this call has just started them.
        blocked = None
    if blocked is not None:
        return blocked
    if item.needs_confirmation:
        return "Chosen from the Character Lab: make its images on its own, which asks first."
    if item.status == "ready":
        return "Already has images. Use Make again to replace them."
    return None


# --- Starting the looks that wait for a base ----------------------------------------------


async def release_waiting(
    session: AsyncSession, project: Project, base_discovery_id: str
) -> list[int]:
    """Starts the `waiting` looks of the same-face variants of one character, once that
    character's newest look is ready and its pinned version holds a front picture. Returns the
    ids of the looks started, and commits each. A look whose picture has gone is marked failed.
    """
    context = await state(session, project)
    by_id = {e.definition.item["id"]: e for e in context.entries}
    base = by_id.get(base_discovery_id)
    front = context.fronts.get(base_discovery_id)
    if base is None or front is None or base.status not in ("ready", "out_of_date"):
        return []
    released: list[int] = []
    for item in context.entries:
        plan = context.plans[item.definition.item["id"]]
        look = item.look
        if plan.base_id != base_discovery_id or look is None or look.status != "waiting":
            continue
        inputs = dict(look.inputs) if isinstance(look.inputs, dict) else {}
        inputs["base"] = _base_record(base, front)
        look_id = look.id
        try:
            started = await character_looks.release_look(
                session,
                look_id,
                reference_image_id=front.lab_image_id,
                relation=_relation(plan, base, item),
                resemblance=None,
                inputs=inputs,
            )
        except character_looks.CharacterLookError as exc:
            failed = await session.get(CharacterLook, look_id)
            if failed is not None and failed.status == "waiting":
                failed.status = "failed"
                failed.error = f"The picture to draw this from could not be used: {exc}"
            await session.commit()
            continue
        if started is not None:
            released.append(look_id)
    return released


async def on_angle_image_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_image` job has stored its picture. When the picture
    finished a look the story pipeline made, so that look is ready and its character's pin
    has moved, starts the looks of the characters drawn from it that were waiting. Returns
    True when any started. Does nothing (False) for any other picture.
    """
    async with SessionLocal() as session:
        reference = (
            (
                await session.execute(
                    select(CharacterReference).where(CharacterReference.lab_run_id == run_id)
                )
            )
            .scalars()
            .first()
        )
        look = await session.get(CharacterLook, reference.look_id) if reference else None
        if (
            look is None
            or look.status != "ready"
            or look.project_id is None
            or look.discovery_id is None
            or look.named_look_id is not None
        ):
            await session.commit()
            return False
        project = await session.get(Project, look.project_id)
        if project is None:
            await session.commit()
            return False
        released = await release_waiting(session, project, look.discovery_id)
    return bool(released)
