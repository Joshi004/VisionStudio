"""ORM models for every table, exactly as DATABASE_STRUCTURE.md Section 4
describes: same columns, nullability, defaults, CHECK constraints, foreign
keys (with their ON DELETE rules) and indexes. Table names are the
lowercase snake_case identifiers from that document (Section 8, item 2);
class names are the PascalCase names from ANALYSIS.md Section 4.3.

No `relationship()` is declared (Phase 1 decision): these are plain
foreign-key columns only. A later phase that needs one uses `lazy="raise"`
and loads it explicitly — lazy loading fails under async SQLAlchemy
(ITERATION_1_PHASES.md Phase 1 pitfalls).

Every column with a database-level DEFAULT also gets the matching
Python-side `default=`, so the value is known on the model instance right
after a flush, with no reload needed (`session.py` sets
`expire_on_commit=False` for the same reason).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import utcnow

_CURRENT_TIMESTAMP = text("CURRENT_TIMESTAMP")


class Project(Base):
    """One row per video (ANALYSIS.md Section 4.3; DB Section 4.1)."""

    __tablename__ = "project"
    __table_args__ = (
        CheckConstraint("orientation IN ('portrait', 'landscape')", name="orientation_valid"),
        CheckConstraint(
            "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5')",
            name="video_model_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    orientation: Mapped[str]
    gen_width: Mapped[int]
    gen_height: Mapped[int]
    out_width: Mapped[int]
    out_height: Mapped[int]
    fps: Mapped[int] = mapped_column(default=24, server_default=text("24"))
    min_scene_seconds: Mapped[float] = mapped_column(default=2.0, server_default=text("2.0"))
    max_scene_seconds: Mapped[float] = mapped_column(default=6.0, server_default=text("6.0"))
    style_prefix: Mapped[str | None] = mapped_column(default=None)
    prompt_suffix: Mapped[str | None] = mapped_column(default=None)
    negative_prompt: Mapped[str | None] = mapped_column(default=None)
    clip_sound_volume: Mapped[float] = mapped_column(default=0.2, server_default=text("0.2"))
    cut_instructions: Mapped[str | None] = mapped_column(default=None)
    # Added in Phase 12: wishes for the AI that writes scene descriptions (characters,
    # places, look, sound), the counterpart of `cut_instructions`.
    description_instructions: Mapped[str | None] = mapped_column(default=None)
    script_text: Mapped[str | None] = mapped_column(default=None)
    # Added in Phase 19: the video model that makes this project's clips (`ltx-2.3` or
    # `ltx-2.5`). NULL means "use the app's default" (the `default_video_model` setting). A
    # scene's own `video_model` wins over this one.
    video_model: Mapped[str | None] = mapped_column(default=None)
    language: Mapped[str] = mapped_column(default="en", server_default=text("'en'"))
    # Circular reference with `asset` (DATABASE_STRUCTURE.md Section 3): `asset.project_id`
    # points back at this table. `use_alter=True` tells SQLAlchemy's dependency sorter the
    # cycle is intended, which matters for `alembic revision --autogenerate` (it walks the
    # ORM metadata and would otherwise raise on the cycle). SQLite has no ALTER TABLE ADD
    # CONSTRAINT, so the migration still writes this foreign key inline in `CREATE TABLE
    # project`, created before `asset`; SQLite allows the forward reference and only
    # checks foreign keys at write time.
    voiceover_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL", use_alter=True), default=None
    )
    # Added in Phase 21: the saved voice that speaks the script when the voiceover is made by
    # the app (Breeze TTS) instead of uploaded. NULL: none chosen.
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice.id", ondelete="SET NULL"), default=None
    )


class Asset(Base):
    """Any file on disk, uploaded or generated (ANALYSIS.md 4.2–4.3; DB Section 4.2)."""

    __tablename__ = "asset"
    __table_args__ = (
        CheckConstraint("kind IN ('voiceover', 'frame', 'clip', 'final')", name="kind_valid"),
        CheckConstraint("source IN ('upload', 'ai', 'derived')", name="source_valid"),
        Index("idx_asset_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    kind: Mapped[str]
    path: Mapped[str]
    mime: Mapped[str]
    size_bytes: Mapped[int]
    duration_s: Mapped[float | None] = mapped_column(default=None)
    width: Mapped[int | None] = mapped_column(default=None)
    height: Mapped[int | None] = mapped_column(default=None)
    sha256: Mapped[str]
    source: Mapped[str]
    provenance: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class Transcript(Base):
    """Word times from the transcription endpoint, matched to the script
    (ANALYSIS.md Section 4.3 and 5.1; DB Section 4.3).
    """

    __tablename__ = "transcript"
    __table_args__ = (Index("idx_transcript_project", "project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    provider: Mapped[str]
    language: Mapped[str]
    words: Mapped[Any] = mapped_column(JSON)
    script_words: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    # Added in Phase 5: which voiceover and which script this transcript was made from, so
    # the app can tell when either has changed since (the transcript is then out of date).
    voiceover_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL"), default=None
    )
    script_sha256: Mapped[str]


class Scene(Base):
    """One cut = one clip (ANALYSIS.md Section 4.3, 5.2, 5.7; DB Section 4.4)."""

    __tablename__ = "scene"
    __table_args__ = (
        CheckConstraint("cut_source IN ('ai', 'rule', 'manual')", name="cut_source_valid"),
        CheckConstraint(
            "scene_description_source IN ('manual', 'ai')", name="scene_description_source_valid"
        ),
        CheckConstraint(
            "first_frame_description_source IN ('manual', 'ai')",
            name="first_frame_description_source_valid",
        ),
        CheckConstraint(
            "last_frame_description_source IN ('manual', 'ai')",
            name="last_frame_description_source_valid",
        ),
        CheckConstraint(
            "image_prompt_source IN ('manual', 'ai')", name="image_prompt_source_valid"
        ),
        CheckConstraint(
            "last_frame_prompt_source IN ('manual', 'ai')",
            name="last_frame_prompt_source_valid",
        ),
        CheckConstraint(
            "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5')",
            name="video_model_valid",
        ),
        UniqueConstraint("project_id", "index"),
        Index("idx_scene_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    index: Mapped[int] = mapped_column("index")
    start_s: Mapped[float]
    end_s: Mapped[float]
    text: Mapped[str]
    cut_source: Mapped[str]
    cut_note: Mapped[str | None] = mapped_column(default=None)
    scene_description: Mapped[str | None] = mapped_column(default=None)
    scene_description_source: Mapped[str | None] = mapped_column(default=None)
    # Added in Phase 12. What the first and last frame should show: written by the AI that
    # drafts descriptions, or by hand. Since Phase 15 each text has its own source (they
    # shared one before), and the AI writes only the first: the last-frame description is
    # for a last frame the author adds by hand. `description_job_id` is the
    # `draft_descriptions` job that wrote the AI text, so a scene can be traced back to the
    # exact prompt that produced it.
    first_frame_description: Mapped[str | None] = mapped_column(default=None)
    last_frame_description: Mapped[str | None] = mapped_column(default=None)
    first_frame_description_source: Mapped[str | None] = mapped_column(default=None)
    last_frame_description_source: Mapped[str | None] = mapped_column(default=None)
    # `use_alter`: `job.scene_id` points back at this table, the same intended cycle as
    # project and asset (see `Project.voiceover_asset_id`).
    description_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL", use_alter=True), default=None
    )
    # Added in Phase 16: the detailed prompt for the image model that makes the first frame,
    # written by the AI (one `write_image_prompt` job per scene) or by hand. The job keeps the
    # exact request and a hash of the inputs, so whether the prompt is out of date is worked
    # out when it is read, never stored.
    image_prompt: Mapped[str | None] = mapped_column(default=None)
    image_prompt_source: Mapped[str | None] = mapped_column(default=None)
    image_prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL", use_alter=True), default=None
    )
    # Added in Phase 23: the instruction for the image model's edit that turns the first frame
    # into the last frame, written by the AI (one `write_last_frame_prompt` job per scene) or
    # by hand. Same rules as `image_prompt`: whether it is out of date is worked out when it is
    # read, never stored.
    last_frame_prompt: Mapped[str | None] = mapped_column(default=None)
    last_frame_prompt_source: Mapped[str | None] = mapped_column(default=None)
    last_frame_prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL", use_alter=True), default=None
    )
    first_frame_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL"), default=None
    )
    last_frame_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL"), default=None
    )
    use_clip_sound: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    selected_clip_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL"), default=None
    )
    # Added in Phase 19: the video model that makes this scene's clips. NULL means "use the
    # project's" (and, when that is NULL too, the app's default).
    video_model: Mapped[str | None] = mapped_column(default=None)


class Job(Base):
    """Every unit of background work (ANALYSIS.md Section 3.3, 4.2–4.3; DB Section 4.5)."""

    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(
            "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', "
            "'write_image_prompt', 'generate_frame', 'generate_clip', 'render_final', "
            "'lab_video', 'write_lab_video_prompt', 'auto_pipeline', 'lab_voice', "
            "'generate_voiceover', 'lab_image', 'write_last_frame_prompt', "
            "'generate_last_frame', 'write_talk_prompts')",
            name="type_valid",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("provider IN ('gpu', 'llm', 'image', 'local')", name="provider_valid"),
        Index("idx_job_project", "project_id"),
        Index("idx_job_scene", "scene_id"),
        Index("idx_job_status", "status"),
        Index("idx_job_type_status", "type", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL only for the jobs of the Video lab (Phase 19), which belongs to no project.
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), default=None
    )
    scene_id: Mapped[int | None] = mapped_column(
        ForeignKey("scene.id", ondelete="CASCADE"), default=None
    )
    type: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued", server_default=text("'queued'"))
    phase: Mapped[str | None] = mapped_column(default=None)
    provider: Mapped[str]
    provider_job_id: Mapped[str | None] = mapped_column(default=None)
    input: Mapped[Any] = mapped_column(JSON)
    output: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    result_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL"), default=None
    )
    attempt: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    error: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    last_checked_at: Mapped[datetime | None] = mapped_column(default=None)


class Setting(Base):
    """Global settings edited in the UI (ANALYSIS.md Section 3.7; DB Section 4.6)."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ApiSnapshot(Base):
    """The recorded GPU API contract (ANALYSIS.md Section 6.5; DB Section 4.7)."""

    __tablename__ = "api_snapshot"
    __table_args__ = (
        CheckConstraint("state IN ('approved', 'pending')", name="state_valid"),
        Index("idx_api_snapshot_source", "source", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str]
    url: Mapped[str]
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    fingerprint: Mapped[str]
    server_content_hash: Mapped[str | None] = mapped_column(default=None)
    api_version: Mapped[str | None] = mapped_column(default=None)
    body: Mapped[Any] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(default="pending", server_default=text("'pending'"))
    approved_at: Mapped[datetime | None] = mapped_column(default=None)


class LabRun(Base):
    """One manual test of an image model from the Image lab page (Phase 13).

    A Seedream run is one synchronous call, not a `job`: the lab is not tied to a project. A run
    on the GPU server's Qwen-Image-2.1 takes minutes, so it is a `lab_image` job (`job_id`) and
    the row is `running` until the job ends. Either way the row keeps the exact request and
    the raw response (image data replaced by sizes), so results can be compared later. Never
    deleted in iteration 1.
    """

    __tablename__ = "lab_run"
    __table_args__ = (
        CheckConstraint("mode IN ('text_to_image', 'image_to_image', 'edit')", name="mode_valid"),
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status_valid"),
        Index("idx_lab_run_created", "created_at"),
        Index("idx_lab_run_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    # Added in Phase 22: the `lab_image` job that makes a run on the GPU server. NULL for a
    # Seedream run.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    mode: Mapped[str]
    endpoint: Mapped[str]
    model: Mapped[str]
    prompt: Mapped[str]
    # What the form held: size, watermark, seed, image set, the two toggles, the extra JSON.
    params: Mapped[Any] = mapped_column(JSON)
    # [{source: "lab" | "asset", id}] in the order they were sent. (Not named `references`:
    # that is an SQL keyword.)
    reference_images: Mapped[Any] = mapped_column(JSON)
    status: Mapped[str]
    http_status: Mapped[int | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(default=None)
    seconds: Mapped[float | None] = mapped_column(default=None)
    request_bytes: Mapped[int | None] = mapped_column(default=None)
    usage: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    request: Mapped[Any] = mapped_column(JSON)
    response: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)


class LabImage(Base):
    """An image the Image lab holds: one the user uploaded, or one a run produced. Files live
    under `media/lab/` (Phase 13). A project's frames are not copied here: a run refers to
    them by their `asset` id.
    """

    __tablename__ = "lab_image"
    __table_args__ = (
        CheckConstraint("origin IN ('upload', 'result')", name="origin_valid"),
        Index("idx_lab_image_run", "run_id"),
        Index("idx_lab_image_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    origin: Mapped[str]
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_run.id", ondelete="SET NULL"), default=None
    )
    # The position among the run's results, from 0. None for an upload.
    output_index: Mapped[int | None] = mapped_column(default=None)
    path: Mapped[str]
    mime: Mapped[str]
    width: Mapped[int]
    height: Mapped[int]
    size_bytes: Mapped[int]
    sha256: Mapped[str]


class LabVideoRun(Base):
    """One video the Video lab made, or is making (Phase 19).

    The lab belongs to no project, so its work runs as `job` rows with `project_id` NULL
    (`lab_video`). The job holds the status, the phase and the exact request that was sent;
    this row holds what the page lists and compares: the model, the prompt, the form's
    parameters and, once the job has finished, the file under `media/lab/`. The runs that one
    "run on both models" click starts share a `group_key`, so the page shows them side by side.
    """

    __tablename__ = "lab_video_run"
    __table_args__ = (
        CheckConstraint("video_model IN ('ltx-2.3', 'ltx-2.5')", name="video_model_valid"),
        Index("idx_lab_video_run_created", "created_at"),
        Index("idx_lab_video_run_group", "group_key"),
        Index("idx_lab_video_run_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    group_key: Mapped[str | None] = mapped_column(default=None)
    video_model: Mapped[str]
    endpoint: Mapped[str]
    prompt: Mapped[str]
    # What the form held: mode, orientation, size, fps, duration, frame count, seed and, for
    # LTX-2.3 only, the negative prompt.
    params: Mapped[Any] = mapped_column(JSON)
    # {source: "lab" | "asset", id} when the run started from a first frame, else NULL.
    first_frame: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # Same shape as `first_frame`, only on a run that moves from a first to a last frame.
    last_frame: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # Added in Phase 24 (Talking character lab): {source: "voice_run" | "voice", id} when the
    # clip is lip-synced to a recorded speech (audio-to-video), else NULL.
    audio_input: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # The result, NULL until the job has finished and the clip was stored.
    path: Mapped[str | None] = mapped_column(default=None)
    size_bytes: Mapped[int | None] = mapped_column(default=None)
    sha256: Mapped[str | None] = mapped_column(default=None)
    width: Mapped[int | None] = mapped_column(default=None)
    height: Mapped[int | None] = mapped_column(default=None)
    frame_count: Mapped[int | None] = mapped_column(default=None)
    duration_s: Mapped[float | None] = mapped_column(default=None)
    audio: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)


class Voice(Base):
    """A saved voice: a clean recording and its exact transcript, which Breeze TTS clones
    (Phase 21). A voice made in the Voice lab points at the lab run that made it and shares
    that run's file. A voice is never deleted, like every stored file.
    """

    __tablename__ = "voice"
    __table_args__ = (
        CheckConstraint("origin IN ('upload', 'lab_run')", name="origin_valid"),
        Index("idx_voice_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    name: Mapped[str]
    # The stored recording, under `media/lab/`.
    path: Mapped[str]
    mime: Mapped[str]
    size_bytes: Mapped[int]
    sha256: Mapped[str]
    duration_s: Mapped[float]
    # What the recording says, word for word. The server needs it to clone the voice.
    transcript: Mapped[str]
    origin: Mapped[str]
    # The lab run the recording came from (origin `lab_run`). Not a foreign key: it is only
    # a note of where the file came from.
    lab_voice_run_id: Mapped[int | None] = mapped_column(default=None)


class LabVoiceRun(Base):
    """One speech the Voice lab made, or is making (Phase 21).

    Like `lab_video_run`, the job holds the status and the exact request, and this row holds
    what the page lists: the mode, the text, the settings and, once the job has finished, the
    stored WAV under `media/lab/`.
    """

    __tablename__ = "lab_voice_run"
    __table_args__ = (
        CheckConstraint("mode IN ('design', 'clone', 'direction')", name="mode_valid"),
        Index("idx_lab_voice_run_created", "created_at"),
        Index("idx_lab_voice_run_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    # design: a voice made from a description. clone: a saved voice reads the text.
    # direction: a saved voice reads the text, steered by the instruction.
    mode: Mapped[str]
    text: Mapped[str]
    instruction: Mapped[str | None] = mapped_column(default=None)
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice.id", ondelete="SET NULL"), default=None
    )
    # seed and cfg_scale.
    params: Mapped[Any] = mapped_column(JSON)
    # The result, NULL until the job has finished and the speech was stored.
    path: Mapped[str | None] = mapped_column(default=None)
    size_bytes: Mapped[int | None] = mapped_column(default=None)
    sha256: Mapped[str | None] = mapped_column(default=None)
    duration_s: Mapped[float | None] = mapped_column(default=None)


class LabCharacter(Base):
    """A character of the Talking character lab's cast (Phase 24): a name, the picture that
    pins how it looks, and what to say about it to the AI that writes prompts.

    The picture is referred to by `{source: "lab" | "asset", id}` like a Video lab frame, and is
    never copied. A character may have a default voice (a saved voice that clones or is directed)
    or a default description of its voice (for a voice made from a description). Never deleted
    in iteration 1.
    """

    __tablename__ = "lab_character"
    __table_args__ = (Index("idx_lab_character_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    name: Mapped[str]
    # Who the character is and what they look like, in words. The language model cannot see the
    # picture, so this is all it knows of the character.
    description: Mapped[str] = mapped_column(default="", server_default=text("''"))
    image: Mapped[Any] = mapped_column(JSON)
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice.id", ondelete="SET NULL"), default=None
    )
    voice_instruction: Mapped[str | None] = mapped_column(default=None)


class LabTalkRun(Base):
    """One take of the Talking character lab (Phase 24): a line of dialogue spoken by a
    character picture, made in up to three steps, each a job of its own.

    1. `prompt_job_id`: a `write_talk_prompts` job writes `voice_instruction` and
       `video_prompt` (or the author writes them).
    2. `voice_run_id`: a `lab_voice_run` makes the speech (or an earlier run is reused).
    3. `video_run_id`: a `lab_video_run` on the audio-to-video endpoint makes the clip.

    With `auto_continue` the backend starts the next step by itself when one finishes.
    """

    __tablename__ = "lab_talk_run"
    __table_args__ = (
        CheckConstraint(
            "voice_mode IS NULL OR voice_mode IN ('design', 'clone', 'direction')",
            name="voice_mode_valid",
        ),
        CheckConstraint("orientation IN ('portrait', 'landscape')", name="orientation_valid"),
        Index("idx_lab_talk_run_created", "created_at"),
        Index("idx_lab_talk_run_voice_run", "voice_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    dialogue: Mapped[str]
    character_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_character.id", ondelete="SET NULL"), default=None
    )
    # {source: "lab" | "asset", id}: the picture the speaker is made from.
    image: Mapped[Any] = mapped_column(JSON)
    # What the author said about the character, word for word. Blank: the cast character's
    # description or the prompt that made the picture is used.
    character_note: Mapped[str | None] = mapped_column(default=None)
    delivery_note: Mapped[str | None] = mapped_column(default=None)
    # design | clone | direction when the take makes a new speech. NULL when it reuses one.
    voice_mode: Mapped[str | None] = mapped_column(default=None)
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice.id", ondelete="SET NULL"), default=None
    )
    voice_instruction: Mapped[str | None] = mapped_column(default=None)
    video_prompt: Mapped[str | None] = mapped_column(default=None)
    orientation: Mapped[str]
    video_seed: Mapped[int | None] = mapped_column(default=None)
    negative_prompt: Mapped[str | None] = mapped_column(default=None)
    auto_continue: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # Why the take could not start its next step by itself (for example, the GPU API was not
    # approved for the endpoint). NULL when there is nothing to say.
    last_error: Mapped[str | None] = mapped_column(default=None)
    prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    voice_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_voice_run.id", ondelete="SET NULL"), default=None
    )
    video_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_video_run.id", ondelete="SET NULL"), default=None
    )
