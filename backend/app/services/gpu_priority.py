"""The priority every request to the GPU server carries (SCN-002).

The server orders its queue by `priority`, from 1 (most urgent) to 10 (least urgent, what it
uses when none is sent). It is strict, with no ageing, and it also orders jobs between models
when the global GPU limit is reached. One function, `level_for`, maps a job to the value, so
the levels are decided in one place:

| Level   | Jobs                                                                              |
| ------- | --------------------------------------------------------------------------------- |
| 1       | Clips of the project's pushed scene                                               |
| 2       | Short work: Qwen3.8 calls, speech, transcription, pictures, Lab clicks (H3, music) |
| 3 to 9  | Other clips, banded by the scene's place in story order                            |
| 10      | Story music generation (nothing is sent: 10 is the server's default)              |
| (none)  | LTX requests: the server ignores `priority` for them                               |

The local `input.priority` of a clip job (`shot_takes._chain_priority`) only orders our own
dispatcher. It is never sent.

A handler works out the level when it starts, so a retried or late-started clip always gets its
scene's band and a push that happened meanwhile. `push_scene` and `stop_push` also change the
clips that are already waiting on the server, with `PUT /v1/jobs/{job_id}/priority`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import Job, Project
from app.jobs import phases
from app.providers import gpu_server, music_generator, video_generator
from app.providers.gpu_server import GpuCallError
from app.services import discovery

_logger = logging.getLogger(__name__)

GPU_URL_KEY: Final = "gpu_api_base_url"

MOST_URGENT: Final = 1
SHORT_WORK: Final = 2
BAND_FIRST: Final = 3
BAND_LAST: Final = 9
BAND_COUNT: Final = BAND_LAST - BAND_FIRST + 1

CLIP_JOB_TYPE: Final = "generate_shot"
# The jobs that are short work at level 2, whichever project (or lab) they belong to.
SHORT_WORK_JOB_TYPES: Final = frozenset(
    {
        "synthesize_speech_unit",
        "lab_voice",
        "check_take_dialogue",
        "time_speech_words",
        "time_voice_recording",
        "time_lab_speech_words",
        "time_lab_graphic_words",
        "lab_image",
    }
)

# How many priority changes are sent to the server at once.
_MAX_PARALLEL_CHANGES: Final = 5


class PushError(ValueError):
    """A push that cannot be done. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class PushReport:
    """What a push (or a stop) did to the clips already waiting on the server."""

    scene_id: str | None
    changed: int
    already_running: int
    not_reached: int


def band(position: int, scene_count: int) -> int:
    """The level of a clip of the scene at `position` (from 0) of `scene_count` scenes in story
    order: the first scenes get 3 and the last ones 9.
    """
    if scene_count <= 0 or position < 0:
        return BAND_LAST
    return min(BAND_LAST, BAND_FIRST + position * BAND_COUNT // scene_count)


def with_priority(body: dict[str, Any], level: int | None) -> dict[str, Any]:
    """`body` with the priority set, or `body` itself when there is no level to send."""
    if level is None:
        return body
    return {**body, "priority": level}


def _scene_ids(scenes: object) -> list[str]:
    """The ids of the scenes of the newest scene discovery, in story order."""
    content = getattr(scenes, "content", None)
    items = content.get("scenes") if isinstance(content, dict) else None
    if not isinstance(items, list):
        return []
    return [
        item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _band_of(scene_id: str | None, scene_ids: list[str]) -> int:
    if scene_id is None or scene_id not in scene_ids:
        return BAND_LAST
    return band(scene_ids.index(scene_id), len(scene_ids))


async def _clip_level(session: AsyncSession, job: Job) -> int:
    recorded = job.input if isinstance(job.input, dict) else {}
    scene_id = recorded.get("scene_id")
    scene_id = scene_id if isinstance(scene_id, str) else None
    project = await session.get(Project, job.project_id) if job.project_id is not None else None
    if project is None:
        return BAND_LAST
    if scene_id is not None and project.pushed_scene_id == scene_id:
        return MOST_URGENT
    scenes = await discovery.latest(session, "scenes", project.id)
    return _band_of(scene_id, _scene_ids(scenes))


async def level_for(session: AsyncSession, job: Job) -> int | None:
    """The priority to send for this job, or None when none is to be sent (the server then
    uses 10, or ignores it, as for LTX). Reads the database; commits nothing.
    """
    recorded = job.input if isinstance(job.input, dict) else {}
    if job.type == CLIP_JOB_TYPE:
        return await _clip_level(session, job)
    if job.type == "lab_video":
        # A Lab click on MiniMax H3. LTX ignores the field, so it is not sent.
        return SHORT_WORK if video_generator.is_h3_endpoint(recorded.get("endpoint")) else None
    if job.type == "lab_music":
        # Music for a story is only needed by the renders, so it stays at 10. A Lab click is
        # short work. LTX audio ignores the field.
        if job.project_id is not None or recorded.get("endpoint") == music_generator.LTX_AUDIO_PATH:
            return None
        return SHORT_WORK
    if job.type in SHORT_WORK_JOB_TYPES:
        return SHORT_WORK
    return None


# --- Pushing a scene to the front ---------------------------------------------------


async def _queued_clips(session: AsyncSession, project_id: int, scene_id: str) -> list[Job]:
    """The clip jobs of one scene that wait on the server (they were submitted and have not
    started), where their priority can still be changed.
    """
    statement = select(Job).where(
        Job.project_id == project_id,
        Job.type == CLIP_JOB_TYPE,
        Job.status == "running",
        Job.provider_job_id.is_not(None),
        Job.phase == phases.QUEUED_ON_CLUSTER,
    )
    jobs = (await session.execute(statement)).scalars().all()
    return [
        job for job in jobs if isinstance(job.input, dict) and job.input.get("scene_id") == scene_id
    ]


async def _change(base_url: str, server_ids: list[str], level: int) -> tuple[int, int, int]:
    """Sets the level of each server job. Returns how many changed, how many were already
    running (or no longer there: 409 and 404 are not errors), and how many were not reached.
    """
    gate = asyncio.Semaphore(_MAX_PARALLEL_CHANGES)

    async def one(server_id: str) -> str:
        async with gate:
            try:
                await gpu_server.set_priority(base_url, server_id, level)
            except GpuCallError as exc:
                if exc.kind == "not_found" or (exc.kind == "rejected" and exc.status_code == 409):
                    return "already_running"
                _logger.warning("priority of server job %s was not changed: %s", server_id, exc)
                return "not_reached"
            return "changed"

    outcomes = await asyncio.gather(*(one(server_id) for server_id in server_ids))
    return (
        outcomes.count("changed"),
        outcomes.count("already_running"),
        outcomes.count("not_reached"),
    )


async def _apply(
    session: AsyncSession, project: Project, scene_id: str, level: int
) -> tuple[int, int, int]:
    """Gives the clips of a scene that wait on the server this level. The database session is
    ended before any call to the server.
    """
    jobs = await _queued_clips(session, project.id, scene_id)
    server_ids = [job.provider_job_id for job in jobs if job.provider_job_id is not None]
    base_url = await settings_service.get_str(session, GPU_URL_KEY)
    await session.commit()  # end the read before any network call
    if not server_ids:
        return 0, 0, 0
    return await _change(base_url, server_ids, level)


async def push_scene(session: AsyncSession, project: Project, scene_id: str) -> PushReport:
    """Pushes a scene to the front: its clips get level 1 from now on, the ones already waiting
    on the server are changed, and a scene pushed before goes back to its band. Commits.
    Raises `PushError` when the project has no such scene.
    """
    scene_ids = _scene_ids(await discovery.latest(session, "scenes", project.id))
    if scene_id not in scene_ids:
        raise PushError(f"This project has no scene '{scene_id}'.")
    previous = project.pushed_scene_id
    project.pushed_scene_id = scene_id
    await session.commit()
    if previous is not None and previous != scene_id:
        await _apply(session, project, previous, _band_of(previous, scene_ids))
    changed, running, missed = await _apply(session, project, scene_id, MOST_URGENT)
    return PushReport(scene_id, changed, running, missed)


async def stop_push(session: AsyncSession, project: Project) -> PushReport:
    """Ends the push: the scene's clips go back to their band. Commits. Does nothing when no
    scene is pushed.
    """
    previous = project.pushed_scene_id
    if previous is None:
        return PushReport(None, 0, 0, 0)
    scene_ids = _scene_ids(await discovery.latest(session, "scenes", project.id))
    project.pushed_scene_id = None
    await session.commit()
    level = _band_of(previous, scene_ids)
    changed, running, missed = await _apply(session, project, previous, level)
    return PushReport(previous, changed, running, missed)
