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
RESTARTED: Final = "restarted: submitting again"
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

# --- Running: scene proposal (Phase 6) ------------------------------------------------
PREPARING_PROMPT: Final = "preparing the prompt"
REUSING_ANSWER: Final = "reusing the stored answer"
CHECKING_CUTS: Final = "checking the cuts"
MODEL_FAILED_SPLITTER: Final = "the language model failed: using the rule-based splitter"
SAVING_SCENES: Final = "saving the scenes"

# --- Finished ---------------------------------------------------------------------
DONE: Final = "done"
FAILED: Final = "failed"
CANCELLED: Final = "cancelled"


def preempted(next_attempt: int) -> str:
    return f"pre-empted: submitting again (attempt {next_attempt} of {MAX_ATTEMPTS})"


def asking_model(attempt: int, attempts: int) -> str:
    return f"asking the language model (attempt {attempt} of {attempts})"
