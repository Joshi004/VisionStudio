"""What the jobs of the graphic shots of an explainer share (EXG-005): the browser checks of the
motion service, the sentences and records made from them, the warnings of a component, and how an
attempt is marked failed.

The jobs are `write_shot_graphic_component`, `write_shot_graphic_scene` and
`render_shot_graphic`. They follow the Graphics lab's jobs of the same shape; the differences are
that they read an attempt (`shot_graphic` row) and not a lab run, that their numbers are checked
against the context of the shot and not against one line, and that a component that cannot work
is marked `failed_outright` (§3.7).

A check never fails a job because the motion service could not be reached: that says nothing about
the graphic, so the code is saved as "not checked" and the render then reports the service's
message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

from app.core import settings as settings_service
from app.db.models import ShotGraphic
from app.db.session import SessionLocal
from app.jobs import phase_writer, phases, store
from app.providers import motion_renderer
from app.services import graphics_blocks, graphics_code_checks

_logger = logging.getLogger(__name__)

TOO_LONG: Final = "The model's answer was cut off because it reached the token limit."


@dataclass(frozen=True)
class Checked:
    """What the browser check of a component came to. `answer` is the service's answer, or None
    when the check could not be made, and `reason` says why.
    """

    answer: dict[str, Any] | None
    reason: str | None = None

    @property
    def failed(self) -> bool:
        return self.answer is not None and not self.answer.get("ok")


@dataclass(frozen=True)
class Measured:
    """What the layout check of a block scene came to: `problems` is None when the scene could
    not be measured, and `reason` says why.
    """

    problems: list[str] | None
    reason: str | None = None


def errors_of(answer: dict[str, Any]) -> list[str]:
    """The errors of a failed check, as sentences for the card and for the model."""
    sentences: list[str] = []
    for item in answer.get("errors") or []:
        message = str(item.get("message"))
        if answer.get("stage") == "transpile":
            sentences.append(f"The code does not compile: {message}")
        elif item.get("frame") is not None:
            sentences.append(f"Drawing frame {item['frame']} failed: {message}")
        else:
            sentences.append(message)
    return sentences or ["The component could not be drawn."]


async def _motion_url() -> str:
    async with SessionLocal() as session:
        return await settings_service.get_str(session, settings_service.MOTION_URL_KEY)


async def check_component(job_id: int, resolved: dict[str, Any], code: str) -> Checked:
    """Has the motion service compile `code` and draw still frames of it. A service that cannot
    be reached, or cannot run the check, is not a failure of the job.
    """
    await phase_writer.note(job_id, phases.CHECKING_COMPONENT)
    body = {
        "width": int(resolved["width"]),
        "height": int(resolved["height"]),
        "fps": int(resolved["fps"]),
        "frames": int(resolved["frames"]),
        "resolved": resolved,
        "code": code,
    }
    try:
        answer = await motion_renderer.checks(await _motion_url(), body)
    except motion_renderer.MotionServiceError as exc:
        _logger.warning("job %d: the component could not be checked: %s", job_id, exc)
        return Checked(None, str(exc))
    return Checked(answer)


async def measure_layout(job_id: int, resolved: dict[str, Any], scene: dict[str, Any]) -> Measured:
    """Has the motion service lay `scene` out and turns its report into problems. A service that
    cannot be reached, or does not accept the scene, is not a failure of the job.
    """
    await phase_writer.note(job_id, phases.CHECKING_BLOCK_LAYOUT)
    body = {
        "width": int(resolved["width"]),
        "height": int(resolved["height"]),
        "fps": int(resolved["fps"]),
        "frames": int(resolved["frames"]),
        "resolved": resolved,
        "input": scene,
        "at_frames": graphics_blocks.layout_frames(scene, resolved),
    }
    try:
        report = await motion_renderer.layout(await _motion_url(), body)
    except motion_renderer.MotionServiceError as exc:
        _logger.warning("job %d: the layout could not be measured: %s", job_id, exc)
        return Measured(None, str(exc))
    return Measured(graphics_blocks.layout_problems(report, resolved))


def checks_record(checked: Checked, asked_again: bool) -> dict[str, Any]:
    """What is stored of the browser check: `checked` is false when it could not be made."""
    answer = checked.answer
    record: dict[str, Any] = {
        "checked": answer is not None,
        "passed": None if answer is None else bool(answer.get("ok")),
        "stage": None if answer is None else answer.get("stage"),
        "errors": [] if answer is None or answer.get("ok") else errors_of(answer),
        "check_s": None if answer is None else answer.get("check_s"),
        "asked_again": asked_again,
    }
    if answer is None:
        record["reason"] = checked.reason
    return record


def component_warnings(
    code: str,
    checked: Checked,
    brief: dict[str, Any],
    context: str,
    resolved: dict[str, Any],
) -> list[str]:
    """The warnings of a component: the numbers its code types (G-7), and the numbers in the text
    the browser showed that neither the context of the shot nor a fact says (the soft rule,
    §3.2).
    """
    warnings = graphics_code_checks.code_warnings(code, resolved, brief)
    if checked.answer is not None and checked.answer.get("ok"):
        warnings += graphics_code_checks.text_warnings(
            checked.answer.get("texts") or [], context, resolved
        )
    return warnings


def sum_usage(*counts: dict[str, int] | None) -> dict[str, int]:
    """The tokens of the calls that were answered, added up. Empty when none was."""
    total: dict[str, int] = {}
    for one in counts:
        for key, value in (one or {}).items():
            total[key] = total.get(key, 0) + value
    return total


async def fail_attempt(
    job_id: int,
    row_id: int,
    message: str,
    *,
    saved: Any = None,
    metrics: dict[str, Any] | None = None,
    outright: bool = False,
) -> None:
    """Fails the job and puts the message on its attempt, so the card shows it. `saved` (code
    that was written but does not work) goes on the attempt as its input. `outright` marks a
    component that has failed outright (§3.7). A job that was cancelled meanwhile leaves the
    attempt alone.
    """
    async with SessionLocal() as session:
        job = await store.get_job(session, job_id)
        row = await session.get(ShotGraphic, row_id)
        if job is not None and job.status == "running" and row is not None:
            if saved is not None:
                row.input = saved
            if metrics is not None:
                row.metrics = metrics
            row.last_error = message[: store.ERROR_MAX_CHARS]
            row.failed_outright = outright
        await store.fail_job(session, job_id, message)
