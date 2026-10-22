"""Editing the lists of a story project's characters, environments and scenes (PHASE-037).

The user's edited list is saved as the next version (`source` is `manual`, `job_id` is NULL), the
way PHASE-047 saves hand-written relations. It is checked by the code that checks the model's
answer (`discovery_writer.check_items` and `scene_discovery_writer.check_scenes`), and it records
the story hash and the StoryBible version it was saved against, exactly as a version made by a
job does, so it goes out of date by the same rules.

- A save needs what a run needs: the saved story and an up-to-date StoryBible. It is refused
  while a job of the same kind is waiting or running, because that job would add a version of
  its own right after.
- **Ids are stable.** Removing a character or an environment that a scene still uses is refused,
  naming the scenes. A scene "uses" a character when the newest definition of the scene chooses
  it, or when the newest events of the scene have it as a speaker; it uses an environment when
  its newest definition chooses it. Only scenes of the newest list of scenes count. Library
  links and relations are not counted: the story workspace already reports links whose
  character is gone and relations that name one.
- A scene list is cut again from the story by code: the user edits titles, descriptions and
  opening words, and the slices are recomputed, so the scenes' texts still join into the whole
  story byte for byte (`scene_discovery_writer.check_scenes`).
"""

from __future__ import annotations

from typing import Any, Final, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, SceneDefinition, SceneEvents, StoryBible
from app.jobs import store
from app.services import discovery, provenance, scene_discovery_writer, story_bible
from app.services import discovery_writer as writer
from app.services.discovery import DiscoveryError

SOURCE_MANUAL: Final = "manual"


async def _require_inputs(
    session: AsyncSession, project: Project, kind: discovery.StageKind
) -> tuple[str, StoryBible]:
    """The saved story and its up-to-date StoryBible, and a check that no job of this kind is
    active. Raises DiscoveryError.
    """
    story = project.script_text
    if story is None or not story.strip():
        raise DiscoveryError(f"Save the story first: the {kind} are found in the story.")
    bible = await story_bible.latest(session, project.id)
    if bible is None:
        raise DiscoveryError(f"Run the Story Bible first: the {kind} are found with its help.")
    if story_bible.is_out_of_date(story, bible):
        raise DiscoveryError(
            "The Story Bible is out of date, because the story has changed since it was "
            f"written. Re-run the Story Bible first, then edit the {kind}."
        )
    job = await store.latest_job(session, project.id, discovery.SPECS[kind].job_type)
    if job is not None and job.status in store.ACTIVE_STATUSES:
        raise DiscoveryError(f"The {kind} are being found. Wait for the job to finish first.")
    return story, bible


async def _newest_content(
    session: AsyncSession, model: Any, project_id: int
) -> dict[str, dict[str, Any]]:
    """The content of the newest row of each scene of the project, by scene id. `model` is
    `SceneDefinition` or `SceneEvents`.
    """
    statement = (
        select(model)
        .where(model.project_id == project_id)
        .order_by(model.version.desc(), model.id.desc())
        .execution_options(populate_existing=True)
    )
    newest: dict[str, dict[str, Any]] = {}
    for row in (await session.execute(statement)).scalars():
        if row.scene_id not in newest:
            newest[row.scene_id] = row.content
    return newest


async def _users(
    session: AsyncSession, project: Project, kind: writer.Kind
) -> dict[str, list[str]]:
    """The titles of the scenes that use each character (or environment), by discovery id."""
    scenes = await discovery.latest(session, "scenes", project.id)
    if scenes is None:
        return {}
    titles = {scene["id"]: scene["title"] for scene in scenes.content["scenes"]}
    definitions = await _newest_content(session, SceneDefinition, project.id)
    events = await _newest_content(session, SceneEvents, project.id)

    users: dict[str, list[str]] = {}

    def add(discovery_id: str, scene_id: str) -> None:
        title = titles[scene_id]
        found = users.setdefault(discovery_id, [])
        if title not in found:
            found.append(title)

    for scene_id in titles:
        definition = definitions.get(scene_id)
        if definition is not None:
            if kind == "characters":
                for character_id in definition.get("characters", []):
                    add(character_id, scene_id)
            else:
                add(definition["environment_id"], scene_id)
        scene_events = events.get(scene_id)
        if kind == "characters" and scene_events is not None:
            for event in scene_events.get("events", []):
                speaker = event.get("speaker_id")
                if isinstance(speaker, str):
                    add(speaker, scene_id)
    return users


async def save_manual_list(
    session: AsyncSession,
    project: Project,
    kind: writer.Kind,
    items: list[dict[str, Any]],
    *,
    accepting: discovery.Discovery | None = None,
) -> discovery.Discovery:
    """Stores the user's whole edited list of characters (or environments) as the next version
    (`source` is `manual`), and commits. With `accepting` (PHASE-039) it also records which
    version the user accepted as it is. Raises DiscoveryError, with a message fit for the user.
    """
    story, bible = await _require_inputs(session, project, kind)
    try:
        checked = writer.check_items(kind, {kind: items})
    except ValueError as exc:
        raise DiscoveryError(str(exc)) from exc

    newest = await discovery.latest(session, kind, project.id)
    if newest is not None:
        # An item the edit keeps stays matched to its library item (PHASE-048).
        matched = {
            item["id"]: item["library_id"] for item in newest.content[kind] if "library_id" in item
        }
        for item in checked[kind]:
            if item["id"] in matched:
                item["library_id"] = matched[item["id"]]
        kept = {item["id"] for item in checked[kind]}
        removed = [item for item in newest.content[kind] if item["id"] not in kept]
        if removed:
            users = await _users(session, project, kind)
            for item in removed:
                scenes_using = users.get(item["id"])
                if scenes_using:
                    raise DiscoveryError(
                        f"Cannot remove {item['name']} ({item['id']}): it is used in "
                        f"{', '.join(scenes_using)}. Change those scenes first."
                    )

    row = await discovery.add_version(
        session,
        kind,
        project_id=project.id,
        source=SOURCE_MANUAL,
        job_id=None,
        story_sha256=story_bible.story_sha256(story),
        bible_id=bible.id,
        bible_version=bible.version,
        content=checked,
        # The edit is the user's own list: a cast that changed earlier does not make it stale.
        cast_sha256=await discovery.current_cast_sha256(session, project.id, kind),
    )
    if accepting is not None:
        row.inputs = provenance.accepted_inputs(row.inputs, accepting, row.content)
    await session.commit()
    return row


async def save_manual_scenes(
    session: AsyncSession,
    project: Project,
    scenes: list[dict[str, Any]],
    *,
    accepting: discovery.Discovery | None = None,
) -> discovery.Discovery:
    """Stores the user's whole edited list of scenes as the next version (`source` is
    `manual`), and commits. Each scene is `{id, title, description, starts_with}`; code cuts the
    story again at the opening words. With `accepting` (PHASE-039) it also records which version
    the user accepted as it is. Raises DiscoveryError, with a message fit for the user.
    """
    story, bible = await _require_inputs(session, project, "scenes")
    try:
        checked = scene_discovery_writer.check_scenes({"scenes": scenes}, story)
    except ValueError as exc:
        raise DiscoveryError(str(exc)) from exc
    row = await discovery.add_version(
        session,
        "scenes",
        project_id=project.id,
        source=SOURCE_MANUAL,
        job_id=None,
        story_sha256=story_bible.story_sha256(story),
        bible_id=bible.id,
        bible_version=bible.version,
        content=cast(dict[str, Any], checked),
    )
    if accepting is not None:
        row.inputs = provenance.accepted_inputs(row.inputs, accepting, row.content)
    await session.commit()
    return row


async def accept_as_is(
    session: AsyncSession, project: Project, kind: discovery.StageKind
) -> discovery.Discovery:
    """Keeps the newest list of characters, environments or scenes as it is and records that
    it was made from the story and StoryBible as they are now (PHASE-039). Raises
    DiscoveryError.
    """
    newest = await discovery.latest(session, kind, project.id)
    if newest is None:
        raise DiscoveryError(f"There are no {kind} to accept.")
    if kind == "scenes":
        return await save_manual_scenes(
            session, project, newest.content["scenes"], accepting=newest
        )
    return await save_manual_list(session, project, kind, newest.content[kind], accepting=newest)
