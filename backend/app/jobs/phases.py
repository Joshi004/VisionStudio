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
# be cancelled (the server has already finished it). A first frame's phases are listed with
# the other first-frame phases further down (`FRAME_FINISHING_PHASES`).
CLIP_FINISHING_PHASES: Final = frozenset({DOWNLOADING_CLIP, CHECKING_CLIP})

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

# --- Running: last frame prompts (Phase 23) ---------------------------------------------
# It also uses PREPARING_PROMPT, REUSING_ANSWER and `asking_model` from above.
CHECKING_LAST_FRAME_PROMPT: Final = "checking the last frame prompt"
SAVING_LAST_FRAME_PROMPT: Final = "saving the last frame prompt"

# --- Running: the Video lab (Phase 19) ---------------------------------------------------
# The lab's clips use the clip phases above. Its prompt helper also uses PREPARING_PROMPT and
# `asking_model`.
CHECKING_VIDEO_PROMPT: Final = "checking the video prompt"
# A lip-sync clip (Talking character lab) uploads the speech next to the frame. It also uses
# the clip phases above.
UPLOADING_AUDIO: Final = "uploading the speech"
# The Talking character lab's prompt writer. It also uses PREPARING_PROMPT and `asking_model`.
CHECKING_TALK_PROMPTS: Final = "checking the voice and video prompts"

# --- Running: speech (Phase 21) ------------------------------------------------------------
# A speech is made in one request per piece of the script. It also uses SUBMITTING and the
# cluster phases above, with the piece named (`speech_part`) when there is more than one.
UPLOADING_VOICE: Final = "uploading the voice recording"
DOWNLOADING_SPEECH: Final = "downloading the speech"
JOINING_SPEECH: Final = "joining the speech parts"
CHECKING_SPEECH: Final = "checking the speech"
SAVING_SPEECH: Final = "saving the speech"


def speech_part(label: str, part: int, parts: int) -> str:
    """A phase label with the piece it is about: "running on cluster (part 2 of 3)". A speech
    of one piece has no suffix.
    """
    return label if parts <= 1 else f"{label} (part {part} of {parts})"


# --- Running: first frames (Phase 17) ---------------------------------------------------
# The image is made on the GPU server, so a first frame also uses SUBMITTING and the cluster
# phases above. Once the server has finished, the image is fetched and stored: the phases below
# are in `FINISHING_PHASES`, so the job can no longer be cancelled.
PREPARING_IMAGE_REQUEST: Final = "preparing the image request"
# An edit (a last frame, Phase 23) uploads the picture it edits first.
UPLOADING_REFERENCE: Final = "uploading the reference image"
DOWNLOADING_IMAGE: Final = "downloading the image"
IMAGE_NOT_READY: Final = "the server has not released the image yet, checking again"
SAVING_IMAGE: Final = "saving the image"
FITTING_FRAME: Final = "fitting the frame to the size"
SAVING_FRAME: Final = "saving the frame"

FRAME_FINISHING_PHASES: Final = frozenset(
    {DOWNLOADING_IMAGE, SAVING_IMAGE, FITTING_FRAME, SAVING_FRAME}
)

# --- Running: the project's cast (characters and places) ---------------------------------
# The three language model jobs also use PREPARING_PROMPT and `asking_model` from above. A
# reference picture is made on the GPU server like a first frame, so it also uses SUBMITTING,
# the cluster phases, DOWNLOADING_IMAGE and SAVING_IMAGE.
SAVING_CAST: Final = "saving the cast"
SAVING_REFERENCE_PROMPT: Final = "saving the reference prompt"
SAVING_CAST_ASSIGNMENT: Final = "saving who is in each scene"
# A character's picture has its backdrop removed after it is downloaded.
REMOVING_BACKDROP: Final = "removing the backdrop"
SAVING_REFERENCE: Final = "saving the reference picture"

REFERENCE_FINISHING_PHASES: Final = frozenset(
    {DOWNLOADING_IMAGE, SAVING_IMAGE, REMOVING_BACKDROP, SAVING_REFERENCE}
)

# Every phase in which a remote job's result is being fetched and stored.
FINISHING_PHASES: Final = (
    CLIP_FINISHING_PHASES | FRAME_FINISHING_PHASES | REFERENCE_FINISHING_PHASES
)

# --- Finished ---------------------------------------------------------------------
DONE: Final = "done"
FAILED: Final = "failed"
CANCELLED: Final = "cancelled"


def preempted(next_attempt: int) -> str:
    return f"pre-empted: submitting again (attempt {next_attempt} of {MAX_ATTEMPTS})"


def auto_step(number: int, total: int, label: str, done: int, count: int) -> str:
    """Where an automatic run is: "step 5 of 7: make first frames (4 of 12 done)". `count` is
    the number of targets of the step; a project-level step has one, and shows no count.
    """
    text = f"step {number} of {total}: {label.lower()}"
    return f"{text} ({done} of {count} done)" if count > 1 else text


def trimming(number: int, total: int) -> str:
    return f"trimming clip {number} of {total}"


def asking_model(attempt: int, attempts: int) -> str:
    return f"asking the language model (attempt {attempt} of {attempts})"
