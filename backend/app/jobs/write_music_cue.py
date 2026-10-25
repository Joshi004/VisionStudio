"""The `write_music_cue` job: a language model details one cue of a story project's music plan and
writes the prompts for it (MUSIC-009, `Music_implementation_phases.md` Section 4.2, levels 2 and
3). One job runs for each cue, side by side with the others.

`services/music_cues.start_cue` creates the job with a copy of everything it needs, taken when
the button was pressed: the cue's id and the plan it belongs to, the Music Bible's content, the
names of the characters and who is visible in each shot, what is known about the cue's theme, the
number of wordings and the spare length, whether an objection may still send the plan back, what
the Bible says to avoid, and the upstream rows the version is built from.

The calls, in order:

1. **The detail** (level 2): the cue's exact anchors, the broad order of moods, hit requests and
   mix notes. A failure here stops the job. The answer may carry an **objection**: the cue
   says the plan cannot work for it. When a revision of the plan is still allowed
   (`input.pushback_allowed`) the job saves the detail with the objection (`sent` true) and
   stops, so the plan can be revised. When it is not, the objection is kept (`sent` false) and
   the job goes on.
2. **The wordings** (level 3): one call for the cue and one for each hit it asked for, each
   giving `input.wordings` different prompts. A call that cannot be used fails the job: a cue
   with a prompt missing is not saved.

Each call builds its request in `services/music_cue_writer.py`, asks the model and checks the
answer there. The result is saved as the cue's next version, in the same transaction that marks
the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold for every call: at most 2 attempts (the second told what was wrong with
the first answer), a refusal never retried, every answer saved the moment it arrives, and a
restart never re-runs it (`never_rerun`). The answers already paid for stay on the job's output.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answers.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, music_cue_writer, music_cues, music_timeline
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_cues.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no cue to read."
_PLAN_GONE = "The music plan this cue belongs to could not be found."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    cue_id: str
    plan_id: int
    bible: dict[str, Any]
    names: dict[str, str]
    shot_characters: dict[str, list[str]]
    theme: dict[str, Any] | None
    wordings: int
    handles_s: float
    pushback_allowed: bool
    avoid: list[str]
    saved_inputs: dict[str, Any]


def _is_count(value: object, low: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= low


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    cue_id = job_input.get("cue_id")
    plan_id = job_input.get("plan_id")
    bible = job_input.get("bible")
    names = job_input.get("names")
    shot_characters = job_input.get("shot_characters")
    theme = job_input.get("theme")
    wordings = job_input.get("wordings")
    handles = job_input.get("handles_s")
    allowed = job_input.get("pushback_allowed")
    avoid = job_input.get("avoid")
    saved_inputs = job_input.get("saved_inputs")
    if (
        not isinstance(cue_id, str)
        or not _is_count(plan_id, 1)
        or not isinstance(bible, dict)
        or not isinstance(names, dict)
        or not isinstance(shot_characters, dict)
        or not (theme is None or isinstance(theme, dict))
        or not _is_count(wordings, 1)
        or isinstance(handles, bool)
        or not isinstance(handles, int | float)
        or handles < 0
        or not isinstance(allowed, bool)
        or not isinstance(avoid, list)
        or not isinstance(saved_inputs, dict)
    ):
        return None
    return _Task(
        cue_id=cue_id,
        plan_id=plan_id,
        bible=bible,
        names=names,
        shot_characters=shot_characters,
        theme=theme,
        wordings=wordings,
        handles_s=float(handles),
        pushback_allowed=allowed,
        avoid=[str(item) for item in avoid],
        saved_inputs=saved_inputs,
    )


def _cut_off(result: llm.ChatResult) -> bool:
    return result.finish_reason == "length"


def _detail_reader(
    cue: dict[str, Any], plan: dict[str, Any], index: music_timeline.Index
) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, Any]:
        if _cut_off(result):
            return _TOO_LONG, None
        try:
            answer = music_cue_writer.parse_answer(result.content)
            detail, pushback = music_cue_writer.check_detail(
                answer, cue=cue, plan=plan, index=index
            )
            return None, {"detail": detail, "pushback": pushback}
        except ValueError as exc:
            return str(exc), None

    return read


def _wordings_reader(item: dict[str, Any], task: _Task) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, Any]:
        if _cut_off(result):
            return _TOO_LONG, None
        try:
            answer = music_cue_writer.parse_answer(result.content)
            return None, music_cue_writer.check_wordings(
                answer, item, count=task.wordings, avoid=task.avoid
            )
        except ValueError as exc:
            return str(exc), None

    return read


def _add_usage(total: dict[str, int], usage: dict[str, int] | None) -> None:
    for key, value in (usage or {}).items():
        total[key] = total.get(key, 0) + (value or 0)


class WriteMusicCueHandler(JobHandler):
    job_type = JOB_TYPE
    provider = "llm"
    restart_rule = "never_rerun"
    model_key = STORY_MODEL_KEY

    async def start(self, job_id: int) -> None:
        started = time.monotonic()
        async with SessionLocal() as session:
            job = await store.get_job(session, job_id)
            if job is None or job.status != "running" or not isinstance(job.input, dict):
                await session.commit()
                return
            job_input: dict[str, Any] = dict(job.input)
            project_id = job.project_id
            target = await llm_target.resolve(session, STORY_MODEL_KEY)
            await session.commit()

        task = _read_task(job_input)
        if project_id is None or task is None:
            await self._fail(job_id, _BAD_INPUT)
            return

        async with SessionLocal() as session:
            plan_row = await music_cues.get_plan(session, task.plan_id)
            if plan_row is None or plan_row.project_id != project_id:
                await session.commit()
                await self._fail(job_id, _PLAN_GONE)
                return
            plan: dict[str, Any] = plan_row.content
            timeline: dict[str, Any] = plan_row.timeline
            await session.commit()
        cue = next((item for item in plan["cues"] if item["id"] == task.cue_id), None)
        if cue is None or not music_cue_writer.needs_audio(cue):
            await self._fail(job_id, _BAD_INPUT)
            return

        await self._phase(job_id, phases.PREPARING_PROMPT)
        job_input.update(
            server_url=docker_mapped(target.base_url), endpoint=llm_target.endpoint(target)
        )
        sent: dict[str, Any] = {}
        calls: dict[str, Any] = {}
        usage: dict[str, int] = {}

        async def ask(
            name: str, body: dict[str, Any], read: llm_call.ReadAnswer
        ) -> llm_call.Outcome:
            """Records the request on the job, makes one call, and keeps what it came to."""
            sent[name] = {
                "instructions_sha256": llm_call.instructions_sha256(body),
                "request": body,
            }
            job_input["calls_sent"] = dict(sent)
            async with SessionLocal() as session:
                await store.update_input(session, job_id, job_input)
            outcome = await llm_call.ask_model(
                job_id,
                target,
                body,
                read,
                timeout_s=REQUEST_TIMEOUT_S,
                keep={"calls": dict(calls)},
                correct=True,
            )
            calls[name] = outcome.record()
            _add_usage(usage, outcome.usage)
            return outcome

        # Level 2: the detail of the cue.
        context = music_cue_writer.span_context(
            timeline, plan, cue, task.shot_characters, task.names
        )
        outcome = await ask(
            "detail",
            music_cue_writer.build_detail_request(task.bible, context, model=target.model),
            _detail_reader(cue, plan, music_timeline.index_of(timeline)),
        )
        if outcome.value is None:
            await self._fail(
                job_id, f"The cue '{task.cue_id}' could not be detailed: {outcome.failure}"
            )
            return
        detail: dict[str, Any] = outcome.value["detail"]
        objection: dict[str, str] | None = outcome.value["pushback"]

        items: list[dict[str, Any]] = []
        pushback: dict[str, Any] | None = None
        if objection is not None:
            pushback = {**objection, "sent": task.pushback_allowed}
        if objection is None or not task.pushback_allowed:
            items, failure = await self._write_prompts(
                ask, task, cue, detail, context, target.model
            )
            if failure is not None:
                await self._fail(
                    job_id,
                    f"The prompts of the cue '{task.cue_id}' could not be written: {failure}",
                )
                return

        await self._phase(job_id, phases.SAVING_MUSIC_CUES)
        async with SessionLocal() as session:
            row = await music_cues.save_cue(
                session,
                project_id=project_id,
                plan_id=task.plan_id,
                cue_id=task.cue_id,
                job_id=job_id,
                inputs=task.saved_inputs,
                detail=detail,
                items=items,
                pushback=pushback,
            )
            output = {
                "calls": calls,
                "usage": usage,
                "music_cue_id": row.id,
                "version": row.version,
                "objection_sent": bool(pushback and pushback["sent"]),
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: music cue %s version %d saved for project %d (%d items), usage=%s",
            job_id,
            task.cue_id,
            row.version,
            project_id,
            len(items),
            usage,
        )

    # --- Level 3 ------------------------------------------------------------------------

    async def _write_prompts(
        self,
        ask: Callable[[str, dict[str, Any], llm_call.ReadAnswer], Awaitable[llm_call.Outcome]],
        task: _Task,
        cue: dict[str, Any],
        detail: dict[str, Any],
        context: dict[str, Any],
        model: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One call per item (the cue, then each hit). Returns `(items with their wordings,
        None)`, or `([], why)` when a call gave no usable answer.
        """
        previous = context["previous_in_lane"]
        following = context["next_in_lane"]
        neighbours = [line["id"] for line in (previous, following) if line is not None]
        async with SessionLocal() as session:
            orders = await music_cues.saved_orders(session, task.plan_id, neighbours)
            await session.commit()

        finished: list[dict[str, Any]] = []
        for item in music_cue_writer.make_items(
            cue, detail, handles_s=task.handles_s, theme=task.theme
        ):
            is_hit = item["role"] == music_cue_writer.ROLE_HIT
            body = music_cue_writer.build_wording_request(
                item,
                bible=task.bible,
                cue=cue,
                detail=detail,
                previous=None
                if is_hit
                else music_cue_writer.neighbour_view(
                    previous, orders.get(previous["id"]) if previous else None
                ),
                following=None
                if is_hit
                else music_cue_writer.neighbour_view(
                    following, orders.get(following["id"]) if following else None
                ),
                joins=[] if is_hit else context["joins"],
                count=task.wordings,
                model=model,
            )
            outcome = await ask(f"wordings_{item['id']}", body, _wordings_reader(item, task))
            if outcome.value is None:
                return [], outcome.failure or "no usable answer"
            finished.append(music_cue_writer.finish_item(item, outcome.value))
        return finished, None

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
