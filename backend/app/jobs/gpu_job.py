"""What every remote GPU job handler shares: the settings it reads, its retry numbers, and the
small rules for pre-emption, a poll that got no answer, and a result that was already removed.

These lived in the narration pipeline's jobs until PHASE-046 retired them (they are readable
at the git tag `narration-final`). The image, voice and video handlers (`remote_image`,
`synthesize_speech`, `remote_video`) import them from here.
"""

from __future__ import annotations

import re
from typing import Final, Literal

from app.jobs import phases
from app.providers.gpu_server import GpuCallError

GPU_URL_KEY: Final = "gpu_api_base_url"

SERVER_RETRY_DELAY_S: Final = 5.0
# How many ticks the download is tried again while the server answers 410 but still says the
# result is ready (about two minutes at the default poll interval).
MAX_RESULT_RETRIES: Final = 8

# ANALYSIS.md Section 5.8: a job killed by a higher-priority one is resubmitted unchanged.
_PREEMPTION: Final = re.compile(r"pre-?empt|sigterm|exit code:? ?(?:137|143)", re.IGNORECASE)


def is_preemption(error: str) -> bool:
    return _PREEMPTION.search(error) is not None


def phase_for_poll_error(exc: GpuCallError) -> str:
    """What to show while the server cannot be asked. None of these fails the job."""
    if exc.kind == "unreachable":
        return phases.SERVER_UNREACHABLE_CHECKING
    if exc.kind == "not_found":
        return phases.NOT_FOUND
    if exc.status_code is not None:
        return f"waiting: the server answered HTTP {exc.status_code}, checking again"
    return "waiting: the server's answer was not usable, checking again"


def after_gone_result(
    remote_status: str, result_ready: bool, *, retries: int, attempt: int
) -> Literal["try_again", "resubmit", "fail"]:
    """What to do when the result download answered 410 and the status was asked again.

    The server still calls the job finished with its result ready: it has not released the
    file yet, so try the download again at the next tick (a limited number of times).
    Otherwise the result is gone: submit the same request again, up to `MAX_ATTEMPTS`.
    """
    if remote_status == "succeeded" and result_ready and retries < MAX_RESULT_RETRIES:
        return "try_again"
    return "resubmit" if attempt < phases.MAX_ATTEMPTS else "fail"
