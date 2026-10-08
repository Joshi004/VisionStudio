"""The phase labels a job shows in the UI (ANALYSIS.md Section 3.4).

`job.phase` is free text for people, but the dispatcher and the API also compare it
(a job "paused:" for the banner count, a job "not found on this server" that can be
cancelled or resubmitted), so every label lives here once.
"""

from __future__ import annotations

from typing import Final

# A job is tried at most this many times after pre-emption (ANALYSIS.md Section 5.8).
MAX_ATTEMPTS: Final = 3

# --- Queued: the job has not started, or is waiting to start again ----------------
WAITING_TO_START: Final = "waiting to start"
WAITING_FOR_SLOT: Final = "waiting for a free slot"
PAUSED_API_CHANGED: Final = "paused: GPU API changed"
PAUSED_API_NOT_APPROVED: Final = "paused: GPU API not approved"
WAITING_API_UNCHECKED: Final = "waiting: GPU API could not be checked"
WAITING_SERVER_UNREACHABLE: Final = "waiting: GPU server unreachable"
WAITING_SERVER_BUSY: Final = "waiting: server busy (HTTP 429)"
RESTARTED: Final = "restarted: starting again"
EXPIRED: Final = "expired on the server: submitting again"

# Every label that starts with this counts as "waiting because of the GPU API" in the banner.
PAUSED_PREFIX: Final = "paused:"

# --- Running ----------------------------------------------------------------------
STARTING: Final = "starting"
UPLOADING_VOICEOVER: Final = "uploading the voiceover"
SUBMITTING: Final = "submitting"
QUEUED_ON_CLUSTER: Final = "queued on cluster"
RUNNING_ON_CLUSTER: Final = "running on cluster"
DOWNLOADING_TRANSCRIPT: Final = "downloading the transcript"
MATCHING: Final = "matching to the script"
SERVER_UNREACHABLE_CHECKING: Final = "GPU server unreachable, checking again"
NOT_FOUND: Final = "not found on this server"

# --- Running: clip generation (Phase 9) ------------------------------------------------
PREPARING_FRAMES: Final = "preparing the frames"
UPLOADING_FRAMES: Final = "uploading the frames"
DOWNLOADING_CLIP: Final = "downloading the clip"
CHECKING_CLIP: Final = "checking the clip"
RESULT_NOT_READY: Final = "the server has not released the clip yet, checking again"

# While a job is in one of these, its result is being fetched and stored: it can no longer
# be cancelled (the server has already finished it).
FINISHING_PHASES: Final = frozenset({DOWNLOADING_CLIP, CHECKING_CLIP})

# --- Running: final render (Phase 10) --------------------------------------------------
CHECKING_CLIPS: Final = "checking the clips"
JOINING: Final = "joining the clips and mixing the sound"
CHECKING_VIDEO: Final = "checking the video"
SAVING_VIDEO: Final = "saving the video"

# --- Running: scene proposal (Phase 6) ------------------------------------------------
PREPARING_PROMPT: Final = "preparing the prompt"
REUSING_ANSWER: Final = "reusing the stored answer"
CHECKING_CUTS: Final = "checking the cuts"
MODEL_FAILED_SPLITTER: Final = "the language model failed: using the rule-based splitter"
SAVING_SCENES: Final = "saving the scenes"

# --- Running: scene descriptions (Phase 12) ----------------------------------------------
# It also uses PREPARING_PROMPT, REUSING_ANSWER and `asking_model` from above.
CHECKING_DESCRIPTIONS: Final = "checking the descriptions"
SAVING_DESCRIPTIONS: Final = "saving the descriptions"

# --- Running: image prompts (Phase 16) --------------------------------------------------
# It also uses PREPARING_PROMPT, REUSING_ANSWER and `asking_model` from above.
CHECKING_IMAGE_PROMPT: Final = "checking the image prompt"
SAVING_IMAGE_PROMPT: Final = "saving the image prompt"

# --- Running: first frames (Phase 17) ---------------------------------------------------
PREPARING_IMAGE_REQUEST: Final = "preparing the image request"
GENERATING_IMAGE: Final = "generating the image"
SAVING_IMAGE: Final = "saving the image"
CROPPING_FRAME: Final = "cropping the frame"
SAVING_FRAME: Final = "saving the frame"

# --- Finished ---------------------------------------------------------------------
DONE: Final = "done"
FAILED: Final = "failed"
CANCELLED: Final = "cancelled"


def preempted(next_attempt: int) -> str:
    return f"pre-empted: submitting again (attempt {next_attempt} of {MAX_ATTEMPTS})"


def trimming(number: int, total: int) -> str:
    return f"trimming clip {number} of {total}"


def asking_model(attempt: int, attempts: int) -> str:
    return f"asking the language model (attempt {attempt} of {attempts})"
