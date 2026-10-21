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
# The two shared pools (`jobs/pools.py`): every GPU job waits for the first, every paid language
# model call for the second, whatever kind of job it is.
WAITING_FOR_GPU_SLOT: Final = "waiting for a free GPU server slot"
WAITING_FOR_PAID_API_SLOT: Final = "waiting for a free paid API slot"
WAITING_SERVER_UNREACHABLE: Final = "waiting: GPU server unreachable"
WAITING_SERVER_BUSY: Final = "waiting: server busy (HTTP 429)"
RESTARTED: Final = "restarted: starting again"
EXPIRED: Final = "expired on the server: submitting again"

# Every label that starts with this counts as "waiting because of the GPU API" in the banner.
PAUSED_PREFIX: Final = "paused:"

# --- Running ----------------------------------------------------------------------
STARTING: Final = "starting"
SUBMITTING: Final = "submitting"
QUEUED_ON_CLUSTER: Final = "queued on cluster"
RUNNING_ON_CLUSTER: Final = "running on cluster"
SERVER_UNREACHABLE_CHECKING: Final = "GPU server unreachable, checking again"
NOT_FOUND: Final = "not found on this server"

# --- Running: video generation (Phase 9) -----------------------------------------------
PREPARING_FRAMES: Final = "preparing the frames"
UPLOADING_FRAMES: Final = "uploading the frames"
DOWNLOADING_CLIP: Final = "downloading the clip"
CHECKING_CLIP: Final = "checking the clip"
RESULT_NOT_READY: Final = "the server has not released the clip yet, checking again"

# While a job is in one of these, its result is being fetched and stored: it can no longer
# be cancelled (the server has already finished it). An image's phases are listed with
# the other image phases further down (`FRAME_FINISHING_PHASES`).
CLIP_FINISHING_PHASES: Final = frozenset({DOWNLOADING_CLIP, CHECKING_CLIP})

# --- Running: language model prompts ------------------------------------------------------
PREPARING_PROMPT: Final = "preparing the prompt"

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


# --- Running: images (Phase 17) ---------------------------------------------------------
# The image is made on the GPU server, so it also uses SUBMITTING and the cluster
# phases above. Once the server has finished, the image is fetched and stored: the phases below
# are in `FINISHING_PHASES`, so the job can no longer be cancelled.
# An edit uploads the picture it edits first.
UPLOADING_REFERENCE: Final = "uploading the reference image"
DOWNLOADING_IMAGE: Final = "downloading the image"
IMAGE_NOT_READY: Final = "the server has not released the image yet, checking again"
SAVING_IMAGE: Final = "saving the image"
FITTING_FRAME: Final = "fitting the frame to the size"
SAVING_FRAME: Final = "saving the frame"

FRAME_FINISHING_PHASES: Final = frozenset(
    {DOWNLOADING_IMAGE, SAVING_IMAGE, FITTING_FRAME, SAVING_FRAME}
)

# --- Running: a character's reference picture ----------------------------------------------
# A reference picture is made on the GPU server like any image, so it also uses SUBMITTING,
# the cluster phases, DOWNLOADING_IMAGE and SAVING_IMAGE.
# A character's picture has its backdrop removed after it is downloaded.
REMOVING_BACKDROP: Final = "removing the backdrop"
SAVING_REFERENCE: Final = "saving the reference picture"

REFERENCE_FINISHING_PHASES: Final = frozenset(
    {DOWNLOADING_IMAGE, SAVING_IMAGE, REMOVING_BACKDROP, SAVING_REFERENCE}
)

# --- Running: the Character lab (Phase 25) -----------------------------------------------
# `write_character_look_prompt` and `write_character_take_prompt` also use PREPARING_PROMPT
# and `asking_model` from above. A look's angle pictures have their backdrop removed after
# download, so they also use REMOVING_BACKDROP.
CHECKING_LOOK_PROMPT: Final = "checking the look prompt"
SAVING_LOOK_PROMPT: Final = "saving the look prompt"
CHECKING_AUDITION_LINE: Final = "checking the audition line"
SAVING_AUDITION_LINE: Final = "saving the audition line"
CHECKING_TAKE_PROMPTS: Final = "checking the take's prompts"
SAVING_TAKE_PROMPTS: Final = "saving the take's prompts"
SAVING_LOOK_REFERENCE: Final = "saving the reference picture"

# --- Running: the story stages (PHASE-004) -----------------------------------------------
# `write_story_bible` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_STORY_BIBLE: Final = "saving the Story Bible"

# --- Running: character and environment discovery (PHASE-005) ----------------------------
# `discover_characters` and `discover_environments` also use PREPARING_PROMPT and
# `asking_model` from above.
SAVING_CHARACTERS: Final = "saving the characters"
SAVING_ENVIRONMENTS: Final = "saving the environments"

# --- Running: scene discovery (PHASE-006) ------------------------------------------------
# `discover_scenes` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_SCENES: Final = "saving the scenes"

# --- Running: character definition (PHASE-009) -------------------------------------------
# `define_character` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_DEFINITION: Final = "saving the definition"

# --- Running: character relations (PHASE-047) --------------------------------------------
# `discover_relations` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_RELATIONS: Final = "saving the relations"

# --- Running: story voices (PHASE-011) ---------------------------------------------------
# `design_voice` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_VOICE_DESCRIPTION: Final = "saving the voice description"

# --- Running: environment reference prompts (PHASE-012) ----------------------------------
# `write_environment_prompt` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_ENVIRONMENT_PROMPT: Final = "saving the environment prompt"

# --- Running: environment definition (PHASE-013) -----------------------------------------
# `define_environment` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_ENVIRONMENT_DEFINITION: Final = "saving the environment definition"

# --- Running: scene definition (PHASE-014) -----------------------------------------------
# `define_scene` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_SCENE_DEFINITION: Final = "saving the scene definition"

# --- Running: event extraction (PHASE-015) -----------------------------------------------
# `extract_events` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_SCENE_EVENTS: Final = "saving the scene events"

# --- Running: look and environment-state resolution (PHASE-016) --------------------------
# `resolve_looks_states` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_RESOLUTION: Final = "saving the resolved looks and states"

# --- Running: shot planning (PHASE-020) ---------------------------------------------------
# `plan_shots` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_SHOT_PLAN: Final = "saving the shot plan"

# --- Running: shot definition (PHASE-022) -------------------------------------------------
# `define_shot` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_SHOT_DEFINITION: Final = "saving the shot definition"

# --- Running: shot continuity check (PHASE-023) ------------------------------------------
# `check_shot_continuity` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_CONTINUITY_CHECK: Final = "saving the continuity check"

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


def asking_model(attempt: int, attempts: int) -> str:
    return f"asking the language model (attempt {attempt} of {attempts})"
