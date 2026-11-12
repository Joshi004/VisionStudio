"""The phase labels a job shows in the UI (ANALYSIS.md Section 3.4).

`job.phase` is free text for people, but the dispatcher and the API also compare it
(a job "paused:" for the banner count, a job "not found on this server" that can be
cancelled or resubmitted), so every label lives here once.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

# A job is tried at most this many times after pre-emption (ANALYSIS.md Section 5.8).
MAX_ATTEMPTS: Final = 3

# --- Queued: the job has not started, or is waiting to start again ----------------
WAITING_TO_START: Final = "waiting to start"
WAITING_FOR_SLOT: Final = "waiting: job limit reached"
# The two shared pools (`jobs/pools.py`): every GPU job waits for the first, every paid language
# model call for the second, whatever kind of job it is.
WAITING_FOR_GPU_SLOT: Final = "waiting: remote server job limit reached"
WAITING_FOR_PAID_API_SLOT: Final = "waiting: paid API job limit reached"


def waiting_for_model_slot(model_label: str) -> str:
    """A job at the remote server held back by the limit of its own model (`pools.MODEL_LABELS`),
    not by the shared one: other models' jobs still start.
    """
    return f"waiting: {model_label} job limit reached"


WAITING_SERVER_UNREACHABLE: Final = "waiting: remote server unreachable"
WAITING_SERVER_BUSY: Final = "waiting: server busy (HTTP 429)"
# The upload or the submit got no answer: the job goes back to the queue and sends everything again.
# The reason is shown next to the badge (`live_status`), not in the label.
WAITING_TO_START_AGAIN: Final = "waiting to start again"
RESTARTED: Final = "restarted: starting again"
EXPIRED: Final = "expired on the server: submitting again"

# Every label that starts with this counts as "waiting because of the GPU API" in the banner.
PAUSED_PREFIX: Final = "paused:"

# --- Running ----------------------------------------------------------------------
STARTING: Final = "starting"
SUBMITTING: Final = "submitting"
QUEUED_ON_CLUSTER: Final = "queued on cluster"
RUNNING_ON_CLUSTER: Final = "running on cluster"
SERVER_UNREACHABLE_CHECKING: Final = "remote server unreachable, checking again"
# What these two labels said before the wording changed. Jobs saved with them keep showing them
# until their next phase is written, so `stage_of` still reads them.
_OLD_SERVER_PROBLEM_LABELS: Final = (
    "waiting: GPU server unreachable",
    "GPU server unreachable, checking again",
)
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

# --- Running: the Music lab ------------------------------------------------------------------
# The lab's audio uses SUBMITTING, the cluster phases and the clip phases above (the stored file
# is audio, but the phases say "clip"). Its prompt writer also uses PREPARING_PROMPT and
# `asking_model`.
CHECKING_MUSIC_PROMPT: Final = "checking the music prompt"
# An edit (repaint, cover, inpaint, transform) uploads its source recording before the submit.
UPLOADING_MUSIC_SOURCE: Final = "uploading the source audio"

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

# --- Running: the Music Bible (MUSIC-006) ------------------------------------------------
# `write_music_bible` also uses PREPARING_PROMPT and `asking_model` from above (once per call).
SAVING_MUSIC_BIBLE: Final = "saving the Music Bible"

# --- Running: the music themes (MUSIC-007) -----------------------------------------------
# `write_music_theme_prompt` also uses PREPARING_PROMPT and `asking_model` from above. It saves
# the theme's fields (and starts its candidate recordings) or the captions of its versions.
SAVING_MUSIC_THEME: Final = "saving the theme and starting its recordings"
SAVING_MUSIC_THEME_VERSIONS: Final = "saving the versions and starting their recordings"

# --- Running: the music plan (MUSIC-008) -------------------------------------------------
# `write_music_plan` also uses PREPARING_PROMPT and `asking_model` from above (once per call: the
# plan, then four critics and a reviser per round).
SAVING_MUSIC_PLAN: Final = "saving the music plan"

# --- Running: the callout plan (EXPLAINER-009) ------------------------------------------
# `write_callout_plan` also uses PREPARING_PROMPT and `asking_model` from above (one call).
SAVING_CALLOUT_PLAN: Final = "saving the callout plan"

# --- Running: the graphics theme of an explainer (EXG-002) -------------------------------
# `write_graphic_theme` also uses PREPARING_PROMPT and `asking_model` from above (one call).
SAVING_GRAPHIC_THEME: Final = "saving the graphics look"

# --- Running: the callout look of a motion explainer (CMO-002) ---------------------------
# `write_callout_look` also uses PREPARING_PROMPT and `asking_model` from above (one call).
SAVING_CALLOUT_LOOK: Final = "saving the callout look"

# --- Running: the thumbnail concepts ------------------------------------------------------
# `write_thumbnail_concepts` also uses PREPARING_PROMPT and `asking_model` from above (one call).
TAKING_FRAMES: Final = "taking frames from the video"
SAVING_THUMBNAIL_CONCEPTS: Final = "saving the thumbnail ideas"

# --- Running: the YouTube draft (YT-003) --------------------------------------------------
# `write_youtube_draft` also uses PREPARING_PROMPT and `asking_model` from above (one call).
SAVING_YOUTUBE_DRAFT: Final = "saving the YouTube draft"

# --- Running: the YouTube upload (YT-004) -------------------------------------------------
# `publish_youtube` is a local job. It sends the video to YouTube (the bytes sent are in
# `live_status`), then asks now and then whether YouTube has processed it: between two asks the
# job is queued again with `WAITING_FOR_YOUTUBE`.
UPLOADING_TO_YOUTUBE: Final = "uploading the video to YouTube"
CHECKING_YOUTUBE: Final = "asking YouTube if the video is processed"
WAITING_FOR_YOUTUBE: Final = "waiting for YouTube to process the video"
# YT-005: once the video is processed, the thumbnail and then the captions.
SETTING_YOUTUBE_THUMBNAIL: Final = "setting the thumbnail on YouTube"
SENDING_YOUTUBE_CAPTIONS: Final = "sending the captions to YouTube"

# --- Running: the Graphics lab brief (GFX-003) -------------------------------------------
# `write_lab_graphic_brief` also uses PREPARING_PROMPT and `asking_model` from above (one call).
# `write_shot_graphic_brief` (EXG-004) uses the same three phases, one call per graphic shot.
SAVING_GRAPHIC_BRIEF: Final = "saving the graphic brief"
# `write_lab_graphic_template_spec` (GFX-006) also uses PREPARING_PROMPT and `asking_model` from
# above (one call).
SAVING_TEMPLATE_SPEC: Final = "saving the template spec"
# `write_lab_graphic_block_scene` (GFX-009) also uses PREPARING_PROMPT and `asking_model` from
# above (the scene, then at most one more call with the layout problems).
CHECKING_BLOCK_LAYOUT: Final = "measuring the layout in the browser"
SAVING_BLOCK_SCENE: Final = "saving the block scene"
# `write_lab_graphic_component` (GFX-010) also uses PREPARING_PROMPT and `asking_model` from above
# (the component, then at most one more call with the errors of the browser check).
CHECKING_COMPONENT: Final = "compiling the component in the browser"
SAVING_COMPONENT: Final = "saving the component"
# `write_shot_graphic_component` and `write_shot_graphic_scene` (EXG-005) use the phases of the two
# lab jobs above, and `render_shot_graphic` those of `render_lab_graphic` below (minus the voice).

# --- Running: the music cues (MUSIC-009) -------------------------------------------------
# `write_music_cue` and `audit_music_cues` also use PREPARING_PROMPT and `asking_model` from above
# (once per call: the cue's detail, then one call per prompt to write; or the audit).
SAVING_MUSIC_CUES: Final = "saving the music cues"

# --- Running: music takes (MUSIC-010) ----------------------------------------------------
# `rewrite_music_prompt` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_MUSIC_TAKE: Final = "saving the new prompt and starting its recording"

# --- Running: music placement (MUSIC-011) ------------------------------------------------
# `place_music` also uses `asking_model` from above (once, only when code needs the model to choose
# among real points).
MEASURING_SOUNDS: Final = "measuring the sounds"
PLACING_MUSIC: Final = "placing the music"
SAVING_MUSIC_PLACEMENT: Final = "saving the music placement"

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

# --- Running: scene staging (PHASE-051) --------------------------------------------------
# `stage_scene` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_SCENE_STAGING: Final = "saving the scene staging"

# --- Running: environment views (PHASE-052) ----------------------------------------------
# `plan_environment_views` and `write_environment_view_prompt` also use PREPARING_PROMPT and
# `asking_model` from above.
SAVING_VIEW_PLAN: Final = "saving the view plan"
SAVING_VIEW_PROMPT: Final = "saving the view prompt"

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

# --- Running: repair of a cut between two shots (PHASE-023) ------------------------------
# `repair_shot_cut` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_CUT_REPAIR: Final = "saving the repaired shots"

# --- Running: choosing a shot's references (PHASE-033) -----------------------------------
# `select_shot_references` also uses PREPARING_PROMPT and `asking_model` from above.
USING_FIXED_RULE: Final = "choosing the references by the fixed rule"
SAVING_SHOT_REFERENCES: Final = "saving the shot references"

# --- Running: shot prompt compilation (PHASE-026) ----------------------------------------
# `compile_shot_prompt` also uses PREPARING_PROMPT and `asking_model` from above.
SAVING_SHOT_PROMPT: Final = "saving the shot prompt"

# --- Running: the story render (PHASE-028) ------------------------------------------------
# `render_story` is a local job: every step is an FFmpeg run on this machine.
CHECKING_RENDER_CLIPS: Final = "checking the clips"
# CMO-005: only for a project whose callouts are motion graphics; drawn before the shots are
# trimmed.
DRAWING_CALLOUTS: Final = "drawing the callouts"
MEASURING_LEVELS: Final = "measuring the sound levels"
PLACING_NARRATION: Final = "placing the narration"
# FLOW-008: the voice takes of a continuous explainer, in place of the narration.
PLACING_VOICE: Final = "placing the voice"
# MUSIC-012: the music layers, the mix of everything into the pre-master, its loudness, and the
# loudness of the finished video. `preview_music_mix` uses the same phases.
PLACING_MUSIC_LAYERS: Final = "placing the music layers"
MIXING_SOUND: Final = "mixing the sound"
MEASURING_MIX: Final = "measuring the mix"
# EXPLAINER-008, 010: only for an explainer with burned captions or callouts, before the final
# encode burns them in.
WRITING_CAPTIONS: Final = "writing the captions and callouts"
JOINING_STORY: Final = "joining the shots and encoding the video"
CHECKING_STORY_VIDEO: Final = "checking the video"
MEASURING_FINAL_SOUND: Final = "measuring the finished sound"
SAVING_STORY_VIDEO: Final = "saving the video"
# The preview of the music in context (MUSIC-012, MD-20).
PREPARING_PREVIEW: Final = "preparing the preview"
SAVING_PREVIEW: Final = "saving the preview"
# The two videos of an Audio video test (AVLAB): local FFmpeg runs.
PREPARING_AV_TEST: Final = "checking the test's clips"
RENDERING_AV_PICTURE: Final = "making the picture"
MIXING_AV_CLIP_SOUND: Final = "adding the speech and the clips' sound"
MIXING_AV_TTS_SOUND: Final = "adding the speech alone"
SAVING_AV_VIDEOS: Final = "saving the videos"
# The video of a Graphics lab render (GFX-005): the motion service (or the Python renderer) draws
# it, then the backend checks it, adds the voice and stores it.
SENDING_GRAPHIC: Final = "sending the graphic to the motion service"
DRAWING_GRAPHIC_IN_PYTHON: Final = "drawing the graphic in Python"
DOWNLOADING_GRAPHIC: Final = "downloading the video"
CHECKING_GRAPHIC: Final = "checking the video"
# Render again (GFX-011): the frames of the new video are compared with the earlier one's.
COMPARING_GRAPHIC_FRAMES: Final = "comparing the frames"
ADDING_GRAPHIC_VOICE: Final = "adding the voice"
SAVING_GRAPHIC: Final = "saving the video"


def rendering_graphic(percent: int) -> str:
    return f"rendering the graphic: {percent}%"


def trimming_shot(number: int, total: int) -> str:
    return f"trimming shot {number} of {total}"


# --- Running: the check of earlier takes (PHASE-029) ---------------------------------------
# `check_shot_takes` is a local job: ffprobe and FFmpeg on this machine.
def checking_take(number: int, total: int) -> str:
    return f"checking clip {number} of {total}"


# --- Running: the story pipeline (PHASE-030) ------------------------------------------------
# `story_pipeline` is a local job that only starts the jobs of the stages and waits for them.
_PIPELINE_STEPS_SHOWN: Final = 3


def pipeline_progress(done: int, total: int, running: Sequence[tuple[str, int, int]]) -> str:
    """Where a pipeline run is: "5 of 24 steps done; running: define the characters (2 of 5),
    extract the events". `running` holds each step that is going on as `(label, done, count)`,
    where `count` is the number of targets of the step: a step with one target shows no count.
    """
    text = f"{done} of {total} steps done"
    if not running:
        return text
    named = [
        f"{label.lower()} ({targets_done} of {count})" if count > 1 else label.lower()
        for label, targets_done, count in running[:_PIPELINE_STEPS_SHOWN]
    ]
    more = len(running) - _PIPELINE_STEPS_SHOWN
    if more > 0:
        named.append(f"{more} more")
    return f"{text}; running: {', '.join(named)}"


def pipeline_paused(label: str) -> str:
    """The phase of a run that waits for the user to press Continue."""
    return f"Paused after {label.lower()}: press Continue to go on"


def pipeline_review(label: str) -> str:
    """The phase of a run that waits at a review point (PHASE-041). `label` is the point's, as
    "After shot planning".
    """
    return f"Waiting for your review ({label[:1].lower()}{label[1:]}): press Continue to go on"


# --- Running: the dialogue check of a take (PHASE-031) ----------------------------------------
# `check_take_dialogue` is a GPU job (Parakeet), so it also uses SUBMITTING and the cluster phases
# above. Once the server has finished, the transcript is fetched and compared: the phases below
# are in `FINISHING_PHASES`, so the job can no longer be cancelled.
UPLOADING_CLIP_FOR_TRANSCRIPT: Final = "uploading the clip for transcription"
DOWNLOADING_TRANSCRIPT: Final = "downloading the transcript"
COMPARING_DIALOGUE: Final = "comparing the speech with the dialogue"

# `time_speech_words` (EXPLAINER-007) is the same kind of job, on a speech's WAV: it uploads the
# speech, then matches the heard words to the script's words.
UPLOADING_SPEECH_FOR_TRANSCRIPT: Final = "uploading the speech for transcription"
MATCHING_WORDS: Final = "matching the heard words to the script"

# `time_voice_recording` (REC-004) times a person's whole recording of a recorded explainer. It
# finds the pauses and cuts the file into pieces first (the pieces go to the server one after the
# other, shown with `speech_part`), and `split_voice_recording` cuts it into the scenes' takes.
FINDING_RECORDING_PAUSES: Final = "finding the pauses in the recording"
CUTTING_RECORDING_PIECE: Final = "cutting a piece of the recording"
NEXT_RECORDING_PIECE: Final = "waiting to send the next piece of the recording"
SPLITTING_RECORDING: Final = "splitting the recording into scenes"
SAVING_SCENE_TAKES: Final = "saving the scene takes"

# `splice_voice_recording` (REC-006) puts the patches a person recorded into the full recording.
MEASURING_PATCH_LOUDNESS: Final = "measuring the loudness around each patch"
SPLICING_PATCHES: Final = "splicing the patches into the recording"
SAVING_SPLICED_RECORDING: Final = "saving the new version of the recording"

TRANSCRIPT_FINISHING_PHASES: Final = frozenset(
    {DOWNLOADING_TRANSCRIPT, COMPARING_DIALOGUE, MATCHING_WORDS}
)

# Every phase in which a remote job's result is being fetched and stored.
FINISHING_PHASES: Final = (
    CLIP_FINISHING_PHASES
    | FRAME_FINISHING_PHASES
    | REFERENCE_FINISHING_PHASES
    | TRANSCRIPT_FINISHING_PHASES
)

# --- Finished ---------------------------------------------------------------------
DONE: Final = "done"
FAILED: Final = "failed"
CANCELLED: Final = "cancelled"


def preempted(next_attempt: int) -> str:
    return f"pre-empted: submitting again (attempt {next_attempt} of {MAX_ATTEMPTS})"


def asking_model(attempt: int, attempts: int) -> str:
    return f"asking the language model (attempt {attempt} of {attempts})"


def queued_again(reason: str, attempt: int, attempts: int) -> str:
    """Shown on a paid job the dispatcher put back in the queue by itself."""
    return f"{reason}: queued again (attempt {attempt} of {attempts})"


# --- The stage a job shows: worked out from its status and phase ------------------------------
# Only five statuses are stored, but a remote GPU job goes through many more steps. The stage
# names the step for people, and nothing is stored: `stage_of` reads `status` and `phase`.
JobStage = Literal[
    "waiting",
    "paused",
    "resubmitting",
    "starting",
    "waiting_to_upload",
    "uploading",
    "waiting_for_gpu",
    "running_on_server",
    "fetching_result",
    "server_unreachable",
    "not_found",
    "running",
    "completed",
    "failed",
    "cancelled",
]

# The job has a free slot and is waiting for one of the (at most 5) upload places.
# Written before the first upload, so a job that waits for its turn is not shown as uploading.
WAITING_TO_UPLOAD: Final = "waiting to upload"

# The steps in which a job sends its files and its request to the GPU server. A label may carry a
# suffix (`speech_part`: "submitting (part 2 of 3)"), so these are compared as prefixes.
_UPLOAD_PHASES: Final = (
    PREPARING_FRAMES,
    UPLOADING_FRAMES,
    UPLOADING_REFERENCE,
    UPLOADING_AUDIO,
    UPLOADING_VOICE,
    UPLOADING_MUSIC_SOURCE,
    UPLOADING_CLIP_FOR_TRANSCRIPT,
    UPLOADING_SPEECH_FOR_TRANSCRIPT,
    UPLOADING_TO_YOUTUBE,
    SUBMITTING,
)

# The steps in which the server has finished and the result is fetched, checked and stored.
_FETCH_PHASES: Final = (
    *sorted(FINISHING_PHASES),
    RESULT_NOT_READY,
    IMAGE_NOT_READY,
    DOWNLOADING_SPEECH,
    JOINING_SPEECH,
    CHECKING_SPEECH,
    SAVING_SPEECH,
)

_RESUBMITTING_PREFIXES: Final = ("pre-empted:", EXPIRED, RESTARTED)
_SERVER_PROBLEM_PREFIXES: Final = (
    SERVER_UNREACHABLE_CHECKING,
    WAITING_SERVER_UNREACHABLE,
    WAITING_SERVER_BUSY,
    "waiting: the server",
    *_OLD_SERVER_PROBLEM_LABELS,
)


def _starts_with(phase: str, labels: Sequence[str]) -> bool:
    return phase.startswith(tuple(labels))


def stage_of(status: str, phase: str | None) -> JobStage:
    """The stage a job is in, for the badge on the Activity page and in the panels.

    Only a job that goes to the GPU server has the stages between `starting` and
    `fetching_result`. Any other running job (a language model call, a local job) is `running`.
    """
    if status == "succeeded":
        return "completed"
    if status == "failed":
        return "failed"
    if status == "cancelled":
        return "cancelled"

    label = phase or ""
    if status == "queued":
        if label.startswith(PAUSED_PREFIX):
            return "paused"
        if _starts_with(label, _SERVER_PROBLEM_PREFIXES):
            return "server_unreachable"
        if _starts_with(label, _RESUBMITTING_PREFIXES):
            return "resubmitting"
        return "waiting"

    # Running.
    if not label or label == STARTING:
        return "starting"
    if label == NOT_FOUND:
        return "not_found"
    if _starts_with(label, _SERVER_PROBLEM_PREFIXES):
        return "server_unreachable"
    if label == WAITING_TO_UPLOAD:
        return "waiting_to_upload"
    if _starts_with(label, _UPLOAD_PHASES):
        return "uploading"
    if label.startswith(QUEUED_ON_CLUSTER):
        return "waiting_for_gpu"
    if label.startswith(RUNNING_ON_CLUSTER):
        return "running_on_server"
    if _starts_with(label, _FETCH_PHASES):
        return "fetching_result"
    return "running"
