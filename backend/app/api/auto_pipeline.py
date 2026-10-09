"""Automatic generation (the `auto_pipeline` job; ANALYSIS.md Section 3.3).

`POST /api/projects/{id}/auto-generate` starts one run and returns at once with HTTP 202. The
run goes through the manual steps one after the other (transcribe, propose scenes,
descriptions, image prompts, first frames, clips, final render), and starts a step only when
every scene has finished the one before. A scene whose job fails is tried again, up to
`max_tries` jobs in a step, and then the run stops and says what is wrong. The dispatcher does
the work (`jobs/auto_pipeline.py`).

Starting is the one consent for everything the run does, paid calls included, so the page asks
first. `GET .../auto-generate` carries what it must ask: the two questions the manual "Propose
scenes" asks (`ConfirmationsOut`). The start refuses with 409 until they are confirmed, the
same as that button does.

`GET .../auto-generate` reads the database only: the newest run, and where it is.

Stopping a run is `POST /api/jobs/{id}/cancel` (`api/jobs.py`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, StrictBool

from app.api.errors import ErrorResponse
from app.api.jobs import JobDetail, JobSummary, job_detail, job_summary
from app.api.projects import load_project
from app.db.session import SessionDep
from app.jobs import dispatcher, store
from app.jobs.store import JobRow
from app.services import auto_pipeline as auto

router = APIRouter()

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "No project has this id."}}
_CANNOT_START = {
    422: {
        "model": ErrorResponse,
        "description": "A run cannot start: there is no voiceover or script, or another job of "
        "the project is waiting or running.",
    }
}
_NEEDS_CONFIRMATION = {
    409: {
        "model": ErrorResponse,
        "description": "The recording differs from the script, or scenes with inputs would be "
        "replaced, and the request did not confirm it.",
    }
}


class AutoGenerateRequest(BaseModel):
    """What the user has confirmed. Every flag is off unless sent."""

    model_config = ConfigDict(extra="forbid")

    # Go on although the recording differs from the script (`ConfirmationsOut.mismatch`).
    accept_mismatch: StrictBool = False
    # Replace scenes that have a description, frames or a clip. Their files stay on disk.
    discard_scenes_with_inputs: StrictBool = False


class StepOut(BaseModel):
    key: str
    label: str
    # "skipped": the step was already complete when the run got to it. "stopped": the step a
    # cancelled run was at.
    status: auto.StepStatus
    # Scenes (or, for a project-level step, the project) finished, and how many there are.
    # Both are 0 until the run has reached the step.
    done: int
    total: int


class ProblemOut(BaseModel):
    # None when the problem is about the project, not one scene.
    scene_id: int | None
    scene_number: int | None
    # How many jobs the run made for it.
    tries: int
    message: str


class ConfirmationsOut(BaseModel):
    """What the page asks before a run starts. Both only matter when the run will propose
    scenes, and are empty otherwise.
    """

    # The warning about the recording and the script, when there is one.
    mismatch: str | None
    # How many scenes have a description, frames or a clip, and would be replaced.
    scenes_with_inputs: int


class AutoGenerateOut(BaseModel):
    # The newest run, whatever its status. None if there never was one.
    job: JobSummary | None
    steps: list[StepOut]
    # What stopped the run, or what it is waiting on. Empty while all goes well.
    problems: list[ProblemOut]
    # Why a run cannot start now, or None when it can.
    start_blocked_reason: str | None
    confirmations: ConfirmationsOut
    # A scene is tried at most this many times in a step.
    max_tries: int


def _is_active(status_: str | None) -> bool:
    return status_ in store.ACTIVE_STATUSES


@router.post(
    "/projects/{project_id}/auto-generate",
    response_model=JobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_CANNOT_START, **_NEEDS_CONFIRMATION},
)
async def start_auto_generate(
    project_id: int,
    session: SessionDep,
    body: AutoGenerateRequest | None = None,
) -> JobDetail:
    """Starts the automatic flow (every step to the final video, with paid calls), or returns
    the run that is already active.
    """
    flags = body or AutoGenerateRequest()
    project = await load_project(session, project_id)

    run = await store.latest_job(session, project.id, auto.JOB_TYPE)
    if run is not None and _is_active(run.status):
        return job_detail(JobRow(job=run, project_name=project.name, scene_index=None))

    block = auto.start_block(project, await auto.active_jobs(session, project.id))
    if block is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, block)

    needs = await auto.confirmations(session, project)
    if needs.mismatch is not None and not flags.accept_mismatch:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The recording differs from the script. {needs.mismatch} Confirm to go on anyway.",
        )
    if needs.scenes_with_inputs and not flags.discard_scenes_with_inputs:
        noun = "scene has" if needs.scenes_with_inputs == 1 else "scenes have"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{needs.scenes_with_inputs} {noun} a description, frames or a clip. The automatic "
            "flow proposes scenes again, which replaces all the scenes and discards those "
            "inputs (their files stay on disk). Confirm to continue.",
        )

    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=auto.JOB_TYPE,
        provider="local",
        input={
            "accept_mismatch": flags.accept_mismatch,
            "discard_scenes_with_inputs": flags.discard_scenes_with_inputs,
        },
    )
    dispatcher.nudge()
    return job_detail(JobRow(job=job, project_name=project.name, scene_index=None))


@router.get(
    "/projects/{project_id}/auto-generate",
    response_model=AutoGenerateOut,
    responses=_NOT_FOUND,
)
async def get_auto_generate(project_id: int, session: SessionDep) -> AutoGenerateOut:
    """The newest automatic run of the project and where it is. Reads the database only."""
    project = await load_project(session, project_id)
    run = await store.latest_job(session, project.id, auto.JOB_TYPE)
    state = auto.describe(run.output if run is not None else None, run.status if run else "none")

    if run is not None and _is_active(run.status):
        blocked = "An automatic run is in progress."
    else:
        blocked = auto.start_block(project, await auto.active_jobs(session, project.id))
    needs = await auto.confirmations(session, project)

    return AutoGenerateOut(
        job=(
            job_summary(JobRow(job=run, project_name=project.name, scene_index=None))
            if run is not None
            else None
        ),
        steps=[
            StepOut(
                key=step.key,
                label=step.label,
                status=step.status,
                done=step.done,
                total=step.total,
            )
            for step in state.steps
        ],
        problems=[
            ProblemOut(
                scene_id=problem.scene_id,
                scene_number=problem.scene_number,
                tries=problem.tries,
                message=problem.message,
            )
            for problem in state.problems
        ],
        start_blocked_reason=blocked,
        confirmations=ConfirmationsOut(
            mismatch=needs.mismatch, scenes_with_inputs=needs.scenes_with_inputs
        ),
        max_tries=auto.MAX_TRIES,
    )
