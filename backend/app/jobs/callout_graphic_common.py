"""What the jobs of the callout graphics share (CMO-003): the browser checks of a callout
component and how an attempt is marked failed.

The jobs are `write_callout_component` and `render_callout_preview`. They follow the jobs of the
graphic shots (`shot_graphic_common`), which this module reuses for the sentences and records.
The differences are that they read an attempt of `callout_graphic` and that the check draws the
component with the motion service's `callout_component` engine at every zone of the callout and
then applies the callout rules (`services/callout_component_checks`).

A check never fails a job because the motion service could not be reached: that says nothing about
the component, so the code is saved as "not checked" and the preview then reports the service's
message.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from app.core import settings as settings_service
from app.db.models import CalloutGraphic
from app.db.session import SessionLocal
from app.jobs import phase_writer, phases, shot_graphic_common, store
from app.providers import motion_renderer
from app.services import callout_component_checks, graphics_code_checks

_logger = logging.getLogger(__name__)

# The engine of the motion service that draws a callout's component.
MOTION_ENGINE: Final = "callout_component"
# The stage of a check that drew every frame but broke a callout rule.
STAGE_RULES: Final = "rules"


async def _motion_url() -> str:
    async with SessionLocal() as session:
        return await settings_service.get_str(session, settings_service.MOTION_URL_KEY)


def part_texts(resolved: dict[str, Any]) -> list[str]:
    return [str(part["text"]) for part in resolved["parts"]]


async def check_callout_component(
    job_id: int, resolved: dict[str, Any], code: str
) -> shot_graphic_common.Checked:
    """Has the motion service compile `code` and draw still frames of it at each zone of the
    callout, then applies the callout rules to what it drew. A service that cannot be reached, or
    cannot run the check, is not a failure of the job.

    The answer has the shape of a `POST /checks` answer: `ok`, `stage` (`transpile`, `render` or
    `rules`), `errors` (`{frame, message}`; a broken rule has no frame), `texts` and `check_s`.
    """
    await phase_writer.note(job_id, phases.CHECKING_COMPONENT)
    url = await _motion_url()
    frames = callout_component_checks.check_frames(resolved)
    merged: dict[str, Any] = {
        "ok": True,
        "stage": None,
        "errors": [],
        "texts": [],
        "check_s": 0.0,
    }
    for zone in resolved["zones"]:
        body = {
            "engine": MOTION_ENGINE,
            "width": int(zone["width"]),
            "height": int(zone["height"]),
            "fps": int(resolved["fps"]),
            "frames": int(resolved["frames"]),
            "resolved": callout_component_checks.motion_resolved(resolved, zone),
            "code": code,
            "at_frames": frames,
        }
        try:
            answer = await motion_renderer.checks(url, body)
        except motion_renderer.MotionServiceError as exc:
            _logger.warning("job %d: the callout component could not be checked: %s", job_id, exc)
            return shot_graphic_common.Checked(None, str(exc))
        merged["check_s"] = round(merged["check_s"] + float(answer.get("check_s") or 0), 3)
        if not answer.get("ok"):
            # The same code fails the same way at the next zone: report this one and stop.
            merged.update(ok=False, stage=answer.get("stage"), errors=list(answer["errors"]))
            if answer.get("stage") == "render":
                label = f"In the {zone['placement']} zone: "
                merged["errors"] = [
                    {**item, "message": label + str(item["message"])} for item in answer["errors"]
                ]
            return shot_graphic_common.Checked(merged)
        if not merged["texts"]:
            merged["texts"] = list(answer.get("texts") or [])
        for sentence in callout_component_checks.rule_errors(resolved, zone, answer):
            merged["errors"].append({"frame": None, "message": sentence})
    if merged["errors"]:
        merged.update(ok=False, stage=STAGE_RULES)
    return shot_graphic_common.Checked(merged)


def component_warnings(code: str, resolved: dict[str, Any]) -> list[str]:
    """The warnings of a component: the numbers its code types that a part's text shows."""
    return graphics_code_checks.part_number_warnings(code, part_texts(resolved))


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
    component that has failed outright. A job that was cancelled meanwhile leaves the attempt
    alone.
    """
    async with SessionLocal() as session:
        job = await store.get_job(session, job_id)
        row = await session.get(CalloutGraphic, row_id)
        if job is not None and job.status == "running" and row is not None:
            if saved is not None:
                row.input = saved
            if metrics is not None:
                row.metrics = metrics
            row.last_error = message[: store.ERROR_MAX_CHARS]
            row.failed_outright = outright
        await store.fail_job(session, job_id, message)
