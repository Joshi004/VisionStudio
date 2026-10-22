"""The steps that follow a saved shot definition (PHASE-022 to PHASE-026, shared by PHASE-038).

A shot definition is saved by the `define_shot` job, and, since PHASE-038, also by the user's
own edit (`shot_definitions.save_manual`). Either way the same things follow, each a separate
step that is allowed to fail without undoing the definition:

1. the shot's reference pictures are chosen (`shot_references.select_if_ready`);
2. its generation request is planned (`generation_requests.plan_if_ready`);
3. its H3 prompt is compiled by a job (`shot_prompts.queue_after_planning`);
4. when it was the last shot of its scene to be defined, the scene's continuity is checked
   (`shot_continuity.queue_check_if_ready`).

Nothing here sends anything to the GPU: generating the clip is always the user's own press.
A version the user wrote is never replaced by these steps (each of them leaves it as it is).
Nothing here raises, and each step opens its own session, so it can be called after the
caller's commit.
"""

from __future__ import annotations

import logging

from app.services import generation_requests, shot_continuity, shot_prompts, shot_references

_logger = logging.getLogger(__name__)


async def after_definition_saved(project_id: int, scene_id: str, shot_id: str) -> None:
    """Runs the steps that follow a saved shot definition, and wakes the dispatcher for any job
    they queue. A step that cannot be done is logged and left for the user's own press.
    """
    # Imported here: the dispatcher imports the handlers, which import this module.
    from app.db.session import SessionLocal
    from app.jobs import dispatcher

    # The shot's reference pictures are chosen: by the fixed rule here, with no model call
    # (PHASE-024), or, when the setting says the language model chooses, by a job of its own
    # that is queued here and that plans the request and compiles the prompt when it is done
    # (PHASE-033). A shot that cannot be given its pictures yet is left for the user's
    # **Select references**.
    try:
        async with SessionLocal() as session:
            await shot_references.select_if_ready(session, project_id, scene_id, shot_id)
    except Exception:
        _logger.exception(
            "the references of shot '%s' of scene '%s' could not be chosen", shot_id, scene_id
        )

    # With the references chosen, the shot's generation request is planned by code too
    # (PHASE-025). A shot that cannot be planned yet (its speech is not ready, say) is left for
    # the user's **Plan**.
    planned = False
    try:
        async with SessionLocal() as session:
            planned = await generation_requests.plan_if_ready(
                session, project_id, scene_id, shot_id
            )
    except Exception:
        _logger.exception(
            "the generation request of shot '%s' of scene '%s' could not be planned",
            shot_id,
            scene_id,
        )

    # With the request planned, the shot's final prompt is compiled by the model (PHASE-026), a
    # job of its own.
    if planned:
        await shot_prompts.queue_after_planning(project_id, scene_id, shot_id)

    # When this was the last shot of its scene to be defined, the scene's continuity is
    # checked by itself (PHASE-023).
    try:
        async with SessionLocal() as session:
            check = await shot_continuity.queue_check_if_ready(session, project_id, scene_id)
    except Exception:
        _logger.exception(
            "the continuity check of scene '%s' of project %d could not be queued",
            scene_id,
            project_id,
        )
        return
    if check is not None:
        dispatcher.nudge()


async def after_references_saved(project_id: int, scene_id: str, shot_id: str) -> None:
    """Runs the steps that follow the user's own choice of a shot's reference pictures: the
    generation request is planned, and then the prompt is compiled by a job. A step that cannot
    be done is logged and left for the user's own press.
    """
    from app.db.session import SessionLocal

    planned = False
    try:
        async with SessionLocal() as session:
            planned = await generation_requests.plan_if_ready(
                session, project_id, scene_id, shot_id
            )
    except Exception:
        _logger.exception(
            "the generation request of shot '%s' of scene '%s' could not be planned",
            shot_id,
            scene_id,
        )
    if planned:
        await shot_prompts.queue_after_planning(project_id, scene_id, shot_id)
