"""The `write_music_plan` job: a language model writes a story project's music plan, critics
review it and a reviser improves it (MUSIC-008, `Music_implementation_phases.md` Section 4.3,
levels 1 and 1b).

`services/music_plan.start_run` creates the job with a copy of everything it needs, taken when
the button was pressed: the Music Bible's content, the condensed timeline, the ids of the
Bible's themes, the number of review rounds and the upstream rows the version is built from
(`input.bible`, `timeline`, `theme_ids`, `critic_rounds`, `saved_inputs`).

The calls, in order:

1. **The plan** (level 1). A failure here stops the job.
2. **Rounds** (level 1b), at most `input.critic_rounds`. Each round asks four critics, one per
   lens, one after the other. When none asks for a change the review ends. Otherwise a reviser
   writes a new plan from the notes of those who did. A critic whose answer cannot be used is
   recorded as `failed` and counts as no objection. A reviser whose answer cannot be used ends
   the review and keeps the last plan that passed the checks. Neither fails the job: a plan
   that has been paid for and checked is not thrown away.

**A revision from the cues' objections** (`input.mode` is `pushback`, MUSIC-009). The cue
detail may find that the plan cannot work for a cue. `music_plan.start_pushback_revision` then
sends the plan, the objections (`input.previous_plan`, `input.notes`) and the round number. There
is no new plan and no critics: one reviser call reads the objections as the notes of one
reviewer (`PUSHBACK_LENS`) and writes the next version, whose `inputs.pushback` records the
round. A reviser whose answer cannot be used fails the job, since there is nothing to keep.

Each call builds its request in `services/music_plan_writer.py`, asks the model and checks the
answer there. The result is saved as the project's next version, in the same transaction that
marks the job succeeded.

The model is the **story role** (`llm_target.STORY_MODEL_KEY`). A paid job, so the rules in
`jobs/llm_call.py` hold for every call: at most 2 attempts, a refusal never retried, every
answer saved the moment it arrives, and a restart never re-runs it (`never_rerun`): the owner
asks again with a fresh job. The answers already paid for stay on the job's output.

It is a local-style job: everything happens in `start`. Logs hold the job id, what each attempt
did and its token counts, never the story or the answers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Final

from app.core.urls import docker_mapped
from app.db.session import SessionLocal
from app.jobs import llm_call, phases, store
from app.jobs.handlers import JobHandler
from app.providers import llm
from app.services import llm_target, music_plan, music_timeline
from app.services import music_plan_writer as writer
from app.services.llm_target import STORY_MODEL_KEY

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = music_plan.JOB_TYPE
# The longest one call may take. Qwen3.8 raises it to its own minimum.
REQUEST_TIMEOUT_S: Final = 600.0

_BAD_INPUT = "This job has no story material to read."
_TOO_LONG = "The model's answer was cut off because it reached the token limit."

# A critic whose answer could not be used.
VERDICT_FAILED: Final = "failed"

MODE_PUSHBACK: Final = "pushback"
# The "lens" under which the cues' objections are shown to the reviser and stored in `rounds`.
PUSHBACK_LENS: Final = music_plan.PUSHBACK_LENS


@dataclass(frozen=True)
class _Task:
    """The job's input, checked."""

    bible: dict[str, Any]
    timeline: dict[str, Any]
    theme_ids: set[str]
    critic_rounds: int
    saved_inputs: dict[str, Any]
    # Set for a revision from the cues' objections: the plan to revise and the objections.
    previous_plan: dict[str, Any] | None = None
    notes: list[dict[str, Any]] | None = None


def _read_task(job_input: dict[str, Any]) -> _Task | None:
    """The job's input as a task, or None when it is not complete."""
    bible = job_input.get("bible")
    timeline = job_input.get("timeline")
    theme_ids = job_input.get("theme_ids")
    rounds = job_input.get("critic_rounds")
    saved_inputs = job_input.get("saved_inputs")
    if (
        not isinstance(bible, dict)
        or not isinstance(timeline, dict)
        or not isinstance(theme_ids, list)
        or not isinstance(rounds, int)
        or isinstance(rounds, bool)
        or rounds < 0
        or not isinstance(saved_inputs, dict)
    ):
        return None
    for key in ("total_s", "scenes", "shots", "units", "events"):
        if key not in timeline:
            return None
    previous: dict[str, Any] | None = None
    notes: list[dict[str, Any]] | None = None
    if job_input.get("mode") == MODE_PUSHBACK:
        previous = job_input.get("previous_plan")
        notes = job_input.get("notes")
        if (
            not isinstance(previous, dict)
            or "cues" not in previous
            or "boundaries" not in previous
            or not isinstance(notes, list)
            or not notes
        ):
            return None
    return _Task(
        bible=bible,
        timeline=timeline,
        theme_ids={str(item) for item in theme_ids},
        critic_rounds=rounds,
        saved_inputs=saved_inputs,
        previous_plan=previous,
        notes=notes,
    )


def _cut_off(result: llm.ChatResult) -> bool:
    return result.finish_reason == "length"


def _plan_reader(task: _Task) -> llm_call.ReadAnswer:
    index = music_timeline.index_of(task.timeline)

    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if _cut_off(result):
            return _TOO_LONG, None
        try:
            answer = writer.parse_answer(result.content)
            return None, writer.check_plan(answer, index=index, theme_ids=task.theme_ids)
        except ValueError as exc:
            return str(exc), None

    return read


def _critic_reader(plan: dict[str, Any]) -> llm_call.ReadAnswer:
    def read(result: llm.ChatResult) -> tuple[str | None, dict[str, Any] | None]:
        if _cut_off(result):
            return _TOO_LONG, None
        try:
            return None, writer.check_critique(writer.parse_answer(result.content), plan)
        except ValueError as exc:
            return str(exc), None

    return read


def _add_usage(total: dict[str, int], usage: dict[str, int] | None) -> None:
    for key, value in (usage or {}).items():
        total[key] = total.get(key, 0) + (value or 0)


class WriteMusicPlanHandler(JobHandler):
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
                job_id, target, body, read, timeout_s=REQUEST_TIMEOUT_S, keep={"calls": dict(calls)}
            )
            calls[name] = outcome.record()
            _add_usage(usage, outcome.usage)
            return outcome

        rounds: list[dict[str, Any]] = []
        if task.previous_plan is not None and task.notes is not None:
            # A revision from the cues' objections: no new plan and no critics.
            draft: dict[str, Any] = task.previous_plan
            outcome = await ask(
                "revise_pushback",
                writer.build_revise_request(
                    writer.plan_for_model(draft),
                    [{"lens": PUSHBACK_LENS, "notes": task.notes}],
                    task.bible,
                    task.timeline,
                    model=target.model,
                ),
                _plan_reader(task),
            )
            if outcome.value is None:
                await self._fail(job_id, f"The music plan could not be revised: {outcome.failure}")
                return
            current = outcome.value
            rounds.append(
                {
                    "round": 1,
                    "critiques": [
                        {
                            "lens": PUSHBACK_LENS,
                            "verdict": writer.VERDICT_CHANGE,
                            "notes": task.notes,
                            "failure": None,
                        }
                    ],
                    "revised": True,
                    "failure": None,
                }
            )
            review_rounds = 0
        else:
            outcome = await ask(
                "plan",
                writer.build_plan_request(task.bible, task.timeline, model=target.model),
                _plan_reader(task),
            )
            first: dict[str, Any] | None = outcome.value
            if first is None:
                await self._fail(job_id, f"The music plan could not be written: {outcome.failure}")
                return
            draft = first
            current = draft
            review_rounds = task.critic_rounds

        for number in range(1, review_rounds + 1):
            shown = writer.plan_for_model(current)
            critiques: list[dict[str, Any]] = []
            for lens in writer.LENSES:
                outcome = await ask(
                    f"critic_{number}_{lens}",
                    writer.build_critic_request(
                        lens, shown, task.bible, task.timeline, model=target.model
                    ),
                    _critic_reader(current),
                )
                if outcome.value is None:
                    critiques.append(
                        {
                            "lens": lens,
                            "verdict": VERDICT_FAILED,
                            "notes": [],
                            "failure": outcome.failure,
                        }
                    )
                else:
                    critiques.append({"lens": lens, **outcome.value, "failure": None})

            asked = [
                {"lens": item["lens"], "notes": item["notes"]}
                for item in critiques
                if item["verdict"] == writer.VERDICT_CHANGE
            ]
            record: dict[str, Any] = {
                "round": number,
                "critiques": critiques,
                "revised": False,
                "failure": None,
            }
            rounds.append(record)
            if not asked:
                break

            outcome = await ask(
                f"revise_{number}",
                writer.build_revise_request(
                    shown, asked, task.bible, task.timeline, model=target.model
                ),
                _plan_reader(task),
            )
            if outcome.value is None:
                record["failure"] = f"The revision could not be used: {outcome.failure}"
                break
            current = outcome.value
            record["revised"] = True

        await self._phase(job_id, phases.SAVING_MUSIC_PLAN)
        async with SessionLocal() as session:
            row = await music_plan.save_version(
                session,
                project_id=project_id,
                job_id=job_id,
                inputs=task.saved_inputs,
                timeline=task.timeline,
                draft=draft,
                rounds=rounds,
                content=current,
            )
            output = {
                "calls": calls,
                "usage": usage,
                "music_plan_id": row.id,
                "version": row.version,
                "seconds": round(time.monotonic() - started, 1),
            }
            if not await store.finish_job(session, job_id, output):
                # The job was cancelled meanwhile: the version is not kept.
                await session.rollback()
                return
            await session.commit()

        _logger.info(
            "job %d: music plan version %d saved for project %d (%d rounds), usage=%s",
            job_id,
            row.version,
            project_id,
            len(rounds),
            usage,
        )

    # --- Small helpers ------------------------------------------------------------------

    @staticmethod
    async def _phase(job_id: int, phase: str) -> None:
        async with SessionLocal() as session:
            await store.set_phase(session, job_id, phase, status="running")

    @staticmethod
    async def _fail(job_id: int, message: str) -> None:
        async with SessionLocal() as session:
            await store.fail_job(session, job_id, message)
