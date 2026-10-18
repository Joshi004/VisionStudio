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
        # `minimax-h3` since revision 0021 (before it only the labs could use MiniMax H3).
        CheckConstraint(
            "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5', 'minimax-h3')",
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
    # Added in Phase 19: the video model that makes this project's clips (`ltx-2.3`, `ltx-2.5`
    # or, since revision 0021, `minimax-h3`). NULL means "use the app's default" (the
    # `default_video_model` setting). A scene's own `video_model` wins over this one.
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
        CheckConstraint(
            "kind IN ('voiceover', 'frame', 'clip', 'final', 'reference')", name="kind_valid"
        ),
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
            "cast_assignment_source IN ('manual', 'ai')",
            name="cast_assignment_source_valid",
        ),
        # `minimax-h3` since revision 0021 (before it only the labs could use MiniMax H3).
        CheckConstraint(
            "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5', 'minimax-h3')",
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
    # Added with the project's cast: the place this scene shows (optional), chosen by the AI
    # (`assign_cast` job) or by hand. The characters it shows are rows of `scene_character`
    # (none, one or several). Only a scene that names a character or a place is made from their
    # reference pictures.
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("location.id", ondelete="SET NULL"), default=None
    )
    cast_assignment_source: Mapped[str | None] = mapped_column(default=None)
    cast_assignment_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL", use_alter=True), default=None
    )


class Character(Base):
    """A character of a project's story: who it is, what it looks like and the reference picture
    that pins the look, so every scene that shows it is made from the same picture. The text is
    written by the AI that reads the script (`extract_cast` job) and edited by hand. The
    reference picture is a Qwen image on a plain white backdrop with the backdrop removed
    (`reference_asset_id`, an asset of kind `reference`). `status` follows its steps: `pending`
    (nothing yet), `prompted` (the prompt for the picture is written), `ready` (the picture is
    made) and `failed` (the picture could not be made).

    `voice_description` is only a note for the AI that writes prompts. Nothing speaks: a story is
    told by its voiceover.
    """

    __tablename__ = "character"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'prompted', 'ready', 'failed')", name="status_valid"
        ),
        Index("idx_character_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    name: Mapped[str]
    appearance_description: Mapped[str]
    personality_description: Mapped[str | None] = mapped_column(default=None)
    voice_description: Mapped[str | None] = mapped_column(default=None)
    reference_prompt: Mapped[str | None] = mapped_column(default=None)
    # `use_alter`, written the same way as a place's: `job.scene_id` -> `scene.location_id` ->
    # `location` -> `job` is a cycle, and the two tables are kept alike.
    reference_prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL", use_alter=True), default=None
    )
    reference_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(default="pending", server_default=text("'pending'"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class Location(Base):
    """A place of a project's story (a palace, a forest): the same as a `Character`, without a
    personality or a voice.
    """

    __tablename__ = "location"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'prompted', 'ready', 'failed')", name="status_valid"
        ),
        Index("idx_location_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    name: Mapped[str]
    appearance_description: Mapped[str]
    reference_prompt: Mapped[str | None] = mapped_column(default=None)
    reference_prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL", use_alter=True), default=None
    )
    reference_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(default="pending", server_default=text("'pending'"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class SceneCharacter(Base):
    """A character a scene shows. A scene shows none, one or several, so the characters are rows
    here instead of a column of `scene`. `position` is the order of the characters' reference
    pictures when the scene's first frame is made (0 is image 1), and it is part of what the
    scene's image prompt is written from. The rows go with the scene or the character
    (`ON DELETE CASCADE`).
    """

    __tablename__ = "scene_character"
    __table_args__ = (Index("idx_scene_character_character", "character_id"),)

    scene_id: Mapped[int] = mapped_column(
        ForeignKey("scene.id", ondelete="CASCADE"), primary_key=True
    )
    character_id: Mapped[int] = mapped_column(
        ForeignKey("character.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int]


class Job(Base):
    """Every unit of background work (ANALYSIS.md Section 3.3, 4.2–4.3; DB Section 4.5)."""

    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(
            "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', "
            "'write_image_prompt', 'generate_frame', 'generate_clip', 'render_final', "
            "'lab_video', 'write_lab_video_prompt', 'auto_pipeline', 'lab_voice', "
            "'generate_voiceover', 'lab_image', 'write_last_frame_prompt', "
            "'generate_last_frame', 'extract_cast', "
            "'write_character_reference_prompt', 'generate_character_reference', "
            "'assign_cast', 'write_character_look_prompt', 'write_character_take_prompt')",
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
        # The lab has taken MiniMax H3 since revision 0017; `project` and `scene` since 0021.
        CheckConstraint(
            "video_model IN ('ltx-2.3', 'ltx-2.5', 'minimax-h3')", name="video_model_valid"
        ),
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
    # Added in revision 0017 (MiniMax H3 reference mode): the pictures the clip was made from,
    # in the order the prompt names them, as a list of {source: "lab" | "asset", id}. Else NULL.
    references: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # Added in revision 0020 (GPU API 0.14.0): the audios of a MiniMax H3 reference clip, in the
    # order the prompt names them (`<Audio 1>`, ...), as a list of {source: "voice_run" |
    # "voice", id}. NULL for every other clip and for a reference clip made without audio.
    audio_references: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
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


class LibraryCharacter(Base):
    """A character of the Character lab's library (Phase 25): a reusable, project-independent
    character an author builds once (profile, look, voice) and then draws on to make audio,
    pictures and clips.

    Unrelated to a project's own cast (`character`/`location`, Phase 24): the two never touch.
    `species` and `gender` are free text with no fixed list: the API offers whatever the author
    has typed before, as a growing list of suggestions, computed from what every character
    already holds (`services/character_card.suggested_options`).

    Never deleted in iteration 1.
    """

    __tablename__ = "library_character"
    __table_args__ = (
        CheckConstraint("era_kind IN ('present', 'past', 'future')", name="era_kind_valid"),
        Index("idx_library_character_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    name: Mapped[str]
    age: Mapped[int | None] = mapped_column(default=None)
    gender: Mapped[str] = mapped_column(default="", server_default=text("''"))
    species: Mapped[str] = mapped_column(default="", server_default=text("''"))
    era_kind: Mapped[str] = mapped_column(default="present", server_default=text("'present'"))
    # past or future only: how many years from the present. NULL for "present".
    era_years: Mapped[int | None] = mapped_column(default=None)
    # past or future only: what that time looks like here (optional free text).
    era_setting: Mapped[str | None] = mapped_column(default=None)
    appearance: Mapped[str] = mapped_column(default="", server_default=text("''"))
    outfit: Mapped[str | None] = mapped_column(default=None)
    personality: Mapped[str | None] = mapped_column(default=None)
    # Anything else worth telling the image, video and voice models (mannerisms, props, a
    # catchphrase, a limp, anything that keeps the character consistent).
    notes: Mapped[str | None] = mapped_column(default=None)
    # False only for a character with no mouth to lip-sync (a robot with a screen face, an
    # animal, an object): hides lip-sync and disables it even when asked for.
    has_visible_mouth: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    # Optional: a character may be mute. A saved voice that clones or is directed.
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice.id", ondelete="SET NULL"), default=None
    )
    # A description of the voice, used only while there is no `voice_id` (a voice made from a
    # description, Breeze TTS "design" mode).
    voice_description: Mapped[str | None] = mapped_column(default=None)
    # The look currently used to make new takes. NULL until a look is chosen. `use_alter`:
    # `character_look.character_id` points back at this table, the intended cycle (as `asset`'s
    # own circular reference above): `character_look` is created after this table, and this
    # column is added by a later ALTER in the same migration.
    current_look_id: Mapped[int | None] = mapped_column(
        ForeignKey("character_look.id", ondelete="SET NULL", use_alter=True), default=None
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))


class CharacterLook(Base):
    """One attempt at a library character's reference pictures (Phase 25): a master picture (on
    a white backdrop, like a project's cast reference) plus four more angles made by editing it,
    so every later picture, scene and clip of the character can be made consistent with it.

    `version` numbers a character's looks from 1. `status` moves `writing_prompt` ->
    `choosing` (candidates are ready, waiting for one to be picked as the master) ->
    `making_angles` -> `ready`, or `failed`. The four candidates to choose the master from are
    `character_look_candidate` rows; the five angle pictures of a ready look are
    `character_reference` rows.

    `reference_image_id` is the author's own picture a look was started from: its candidates
    are then edits of that picture instead of text-to-image pictures. NULL for a look made from
    the profile alone.
    """

    __tablename__ = "character_look"
    __table_args__ = (
        CheckConstraint(
            "status IN ('writing_prompt', 'choosing', 'making_angles', 'ready', 'failed')",
            name="status_valid",
        ),
        Index("idx_character_look_character", "character_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("library_character.id", ondelete="CASCADE")
    )
    version: Mapped[int]
    status: Mapped[str] = mapped_column(
        default="writing_prompt", server_default=text("'writing_prompt'")
    )
    # The master prompt, once the language model (or the author) has written it.
    prompt: Mapped[str | None] = mapped_column(default=None)
    prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    error: Mapped[str | None] = mapped_column(default=None)
    reference_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_image.id", ondelete="SET NULL"), default=None
    )


class CharacterLookCandidate(Base):
    """One of the (usually four) master pictures generated for a look to choose from
    (Phase 25). A pure link to the `lab_run`/`lab_image` that made it: its own status is read
    from that run, never duplicated here.
    """

    __tablename__ = "character_look_candidate"
    __table_args__ = (Index("idx_character_look_candidate_look", "look_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    look_id: Mapped[int] = mapped_column(ForeignKey("character_look.id", ondelete="CASCADE"))
    lab_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_run.id", ondelete="SET NULL"), default=None
    )


class CharacterReference(Base):
    """One angle picture of a ready look (Phase 25): the master ("front") or one of the four
    edited angles. `(look_id, angle)` is unique: redoing an angle updates this row in place, so
    the character keeps its old picture until the new one is ready.

    `lab_image_id` is the picture exactly as it came from the image model (always on its white
    backdrop): it is what a later edit (another angle, a take's picture) is made from. The
    `cutout_*` columns are the same picture with its backdrop removed, for display and for use
    on any background; they stay NULL when the cutout could not be made (the raw picture on
    white is still a usable reference).
    """

    __tablename__ = "character_reference"
    __table_args__ = (
        CheckConstraint(
            "angle IN ('front', 'three_quarter', 'profile', 'back', 'face')", name="angle_valid"
        ),
        UniqueConstraint("look_id", "angle"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    look_id: Mapped[int] = mapped_column(ForeignKey("character_look.id", ondelete="CASCADE"))
    angle: Mapped[str]
    lab_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_run.id", ondelete="SET NULL"), default=None
    )
    lab_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_image.id", ondelete="SET NULL"), default=None
    )
    cutout_path: Mapped[str | None] = mapped_column(default=None)
    cutout_mime: Mapped[str | None] = mapped_column(default=None)
    cutout_width: Mapped[int | None] = mapped_column(default=None)
    cutout_height: Mapped[int | None] = mapped_column(default=None)
    cutout_size_bytes: Mapped[int | None] = mapped_column(default=None)
    cutout_sha256: Mapped[str | None] = mapped_column(default=None)


class CharacterTake(Base):
    """One thing made from a library character in the Character lab (Phase 25): a line of
    dialogue spoken (audio), a picture, or a clip, with or without dialogue.

    Made in up to three steps, each a job or run the other labs already know how to run, exactly
    like a Talking character lab take did: `prompt_job_id` writes the texts the other steps need
    (an image prompt, a video prompt and/or a delivery instruction, depending on `output` and
    whether `dialogue` is set), then `image_run_id` and/or `voice_run_id` are made, and finally
    (for a video) `video_run_id`. `look_id` freezes which look was used, so a later new look
    never changes an old take.
    """

    __tablename__ = "character_take"
    __table_args__ = (
        CheckConstraint("output IN ('image', 'audio', 'video')", name="output_valid"),
        # A take can use MiniMax H3 too (revision 0019), unlike a project's scenes.
        CheckConstraint(
            "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5', 'minimax-h3')",
            name="video_model_valid",
        ),
        CheckConstraint(
            "audio_marker IS NULL OR audio_marker IN "
            "('fully_copy', 'partially_copy', 'reference', 'weak_reference')",
            name="audio_marker_valid",
        ),
        CheckConstraint("framing IN ('close_up', 'medium', 'wide')", name="framing_valid"),
        CheckConstraint("orientation IN ('portrait', 'landscape')", name="orientation_valid"),
        Index("idx_character_take_character", "character_id"),
        Index("idx_character_take_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("library_character.id", ondelete="CASCADE")
    )
    look_id: Mapped[int | None] = mapped_column(
        ForeignKey("character_look.id", ondelete="SET NULL"), default=None
    )
    output: Mapped[str]
    # What happens in the picture/clip, in the author's words. Ignored for an audio-only take.
    action: Mapped[str | None] = mapped_column(default=None)
    # What the character says. NULL: no dialogue (image or silent video).
    dialogue: Mapped[str | None] = mapped_column(default=None)
    # Video only. NULL for an image or audio take.
    video_model: Mapped[str | None] = mapped_column(default=None)
    lip_sync: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    framing: Mapped[str] = mapped_column(default="medium", server_default=text("'medium'"))
    orientation: Mapped[str] = mapped_column(default="portrait", server_default=text("'portrait'"))
    seed: Mapped[int | None] = mapped_column(default=None)
    # Video with no dialogue only: the clip's length in seconds. NULL when it follows the
    # speech instead (a video with dialogue), or for an image or audio take.
    duration_s: Mapped[float | None] = mapped_column(default=None)
    # Video (LTX) only.
    negative_prompt: Mapped[str | None] = mapped_column(default=None)
    # True for a take made with "run all": each step starts by itself once the step before it
    # finishes, until the take is done or a step cannot start.
    auto_continue: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # {"image_prompt", "video_prompt", "delivery_instruction"}: written by the language model,
    # or left out and written by hand. Only the texts this take's steps need are asked for.
    prompts: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    image_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_run.id", ondelete="SET NULL"), default=None
    )
    voice_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_voice_run.id", ondelete="SET NULL"), default=None
    )
    video_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_video_run.id", ondelete="SET NULL"), default=None
    )
    # MiniMax H3 video takes only (revision 0019); NULL or off for every other take.
    # How the speech is used, in MiniMax's own words: fully_copy, partially_copy, reference or
    # weak_reference. Only a take with dialogue has one.
    audio_marker: Mapped[str | None] = mapped_column(default=None)
    # The clip is as long as the speech (else `duration_s` says how long it is).
    match_audio_duration: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0")
    )
    # 4 to 100 denoising steps. NULL: the pipeline's own default.
    num_inference_steps: Mapped[int | None] = mapped_column(default=None)
    # The look's pictures are sent as extra reference pictures after the frames.
    identity_refs: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # {source: "lab" | "asset", id} when the author picked the first frame instead of having
    # one made. NULL: the take makes it (`image_run_id`).
    first_frame: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # The last frame: made by editing the first frame (`make_last_frame`, then
    # `last_frame_run_id`) or picked (`last_frame`, the shape of `first_frame`). Neither: the
    # clip has no last frame.
    make_last_frame: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    last_frame: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    last_frame_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_run.id", ondelete="SET NULL"), default=None
    )
    # {source: "voice_run" | "voice", id} when the author picked the speech instead of having
    # one made. NULL: the take makes it (`voice_run_id`).
    audio_input: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    last_error: Mapped[str | None] = mapped_column(default=None)
