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
    """One row per project (ANALYSIS.md Section 4.3; DB Section 4.1).

    Since revision 0022 a project keeps only its name, orientation, sizes, frame rate and
    script text. The columns the narration pipeline used were dropped.
    """

    __tablename__ = "project"
    __table_args__ = (
        CheckConstraint("orientation IN ('portrait', 'landscape')", name="orientation_valid"),
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
    script_text: Mapped[str | None] = mapped_column(default=None)


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


class Job(Base):
    """Every unit of background work (ANALYSIS.md Section 3.3, 4.2–4.3; DB Section 4.5)."""

    __tablename__ = "job"
    __table_args__ = (
        # The six lab job types, since revision 0022 retired the narration ones, the first
        # story stage, since revision 0023, the two discovery stages, since revision 0024,
        # scene discovery, since revision 0025, character definition, since revision 0028, and
        # relation discovery, since revision 0030, voice design, since revision 0031, and the
        # environment prompt, since revision 0032, and environment definition, since revision
        # 0033, and scene definition, since revision 0034, and event extraction, since
        # revision 0035, and look and state resolution, since revision 0036, and speech
        # unit audio, since revision 0039, and shot planning, since revision 0040, and shot
        # definition, since revision 0041, and shot continuity, since revision 0042, and the
        # repair of a cut between two shots, since revision 0045, and the compilation of a
        # shot's H3 prompt, since revision 0046, and the generation of a shot's clip, since
        # revision 0047, and the render of the story's video, since revision 0048.
        CheckConstraint(
            "type IN ('lab_image', 'lab_video', 'write_lab_video_prompt', 'lab_voice', "
            "'write_character_look_prompt', 'write_character_take_prompt', 'write_story_bible', "
            "'discover_characters', 'discover_environments', 'discover_scenes', "
            "'define_character', 'discover_relations', 'design_voice', "
            "'write_environment_prompt', 'define_environment', 'define_scene', "
            "'extract_events', 'resolve_looks_states', 'synthesize_speech_unit', "
            "'plan_shots', 'define_shot', 'check_shot_continuity', 'repair_shot_cut', "
            "'compile_shot_prompt', 'generate_shot', 'render_story')",
            name="type_valid",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("provider IN ('gpu', 'llm', 'image', 'local')", name="provider_valid"),
        Index("idx_job_project", "project_id"),
        Index("idx_job_status", "status"),
        Index("idx_job_type_status", "type", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL for the jobs of the labs (Phase 19), which belong to no project.
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), default=None
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


class StoryBible(Base):
    """One version of a story project's StoryBible (PHASE-004).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every run
    or edit is a new row with the next `version`, and a stored row is never changed. `inputs`
    records what the version was built from (`story_sha256`, the hash of the exact
    `project.script_text` the job read), so "out of date" is worked out when it is read.
    `content` is the bible itself (title, language, genre, tone, visual style, time period,
    storytelling style and world rules).
    """

    __tablename__ = "story_bible"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_story_bible_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int]
    source: Mapped[str]
    # The job that produced it. NULL for a manual version.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class CharacterDiscovery(Base):
    """One version of a story project's list of discovered characters (PHASE-005).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1) exactly as
    `StoryBible` does: every run is a new row with the next `version`, and a stored row is
    never changed. `inputs` records the story hash and the StoryBible version the list was made
    from, so "out of date" is worked out when it is read. `content` is
    `{"characters": [{"id", "name", "description"}, ...]}`. Relations between characters are
    not part of this list: they are their own artifact, `CharacterRelations` (D-14, PHASE-047).
    """

    __tablename__ = "character_discovery"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_character_discovery_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int]
    source: Mapped[str]
    # The job that produced it. NULL for a manual version.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class EnvironmentDiscovery(Base):
    """One version of a story project's list of discovered environments (PHASE-005). The same
    shape as `CharacterDiscovery`; `content` is
    `{"environments": [{"id", "name", "description"}, ...]}`.
    """

    __tablename__ = "environment_discovery"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_environment_discovery_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int]
    source: Mapped[str]
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class CharacterRelations(Base):
    """One version of a story project's list of relations between its discovered characters
    (PHASE-047). The same provenance shape as `CharacterDiscovery`: every run or edit is a new
    row, and a stored row is never changed. `content` is
    `{"relations": [{"character", "kind", "of"}, ...]}`: `character` and `of` are slug ids of
    the discovered characters, and `kind` says what `character` is to `of`
    (`younger_self`, `older_self`, `twin`, `parent`, `sibling`, `grandparent`).
    """

    __tablename__ = "character_relations"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_character_relations_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int]
    source: Mapped[str]
    # The job that produced it. NULL for a manual version.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class SceneDiscovery(Base):
    """One version of a story project's list of discovered scenes (PHASE-006). The same
    provenance shape as `CharacterDiscovery`. `content` is
    `{"scenes": [{"index", "id", "title", "description", "starts_with", "start", "end",
    "text"}, ...]}`: the model gave `id`, `title`, `description` and `starts_with`, and code set
    the rest. `text` is `story[start:end]` of the story whose hash is in `inputs`, so the
    scenes' texts joined in order are that whole story. Scenes carry no character or
    environment ids (D-15).
    """

    __tablename__ = "scene_discovery"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_scene_discovery_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int]
    source: Mapped[str]
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class SceneDefinition(Base):
    """One version of one scene's definition (PHASE-014, `Path_ahead.md` Section 16).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every run is
    a new row with the next `version` of that scene, and a stored row is never changed.
    `scene_id` is the slug `id` of the scene inside the project's `scene_discovery` content, so
    a re-run of scene discovery that keeps the id keeps the scene's definitions. `inputs`
    records what the version was built from (the story hash, the scene's own hash, and the
    artifacts: StoryBible, the discovered lists, and the definition of each character and the
    environment the scene chose). `content` is the Section 16 definition.
    """

    __tablename__ = "scene_definition"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "version"),
        Index("idx_scene_definition_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    version: Mapped[int]
    source: Mapped[str]
    # The job that produced it. NULL for a manual version.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class SceneEvents(Base):
    """One version of one scene's list of events (PHASE-015, `Path_ahead.md` Section 17).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every run is
    a new row with the next `version` of that scene, and a stored row is never changed.
    `scene_id` is the slug `id` of the scene inside the project's `scene_discovery` content.
    `inputs` records what the version was built from (the story hash, the scene text's hash,
    and the artifacts: StoryBible, the discovered lists, the scene's definition and the
    definition of each of the scene's characters). `content` is the Section 17 list of events
    with the pieces of the scene's text that no speech event covers.
    """

    __tablename__ = "scene_events"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "version"),
        Index("idx_scene_events_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    version: Mapped[int]
    source: Mapped[str]
    # The job that produced it. NULL for a manual version.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ShotPlan(Base):
    """One version of one scene's list of shot skeletons (PHASE-020, `Path_ahead.md` Sections
    22 and 25).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every run is
    a new row with the next `version` of that scene, and a stored row is never changed.
    `scene_id` is the slug `id` of the scene inside the project's `scene_discovery` content.
    `inputs` records what the version was built from (the story hash, the scene text's hash, the
    artifacts: StoryBible, the scene's definition, events, speech units, the audio of each unit
    with its measured length, and the definitions of the scene's characters and environment)
    and the duration rules it was given. `content` is the list of shots; each names its source
    events and the speech units it carries.
    """

    __tablename__ = "shot_plan"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "version"),
        Index("idx_shot_plan_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    version: Mapped[int]
    source: Mapped[str]
    # The job that produced it. NULL for a manual version.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ShotDefinition(Base):
    """One version of one shot's cinematic specification (PHASE-022, `Path_ahead.md` Section 26).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every run is
    a new row with the next `version` of that shot, and a stored row is never changed.
    `scene_id` is the slug `id` of the scene inside the project's `scene_discovery` content and
    `shot_id` is the shot's id inside that scene's shot plan; `shot_plan_id` is the plan row the
    shot was defined from. `inputs` records what the version was built from (the story hash, the
    artifacts: StoryBible, the scene's definition, the shot plan, the look and state resolution
    and the definitions of the scene's characters and environment) and the shot's length.
    `content` is the specification.
    """

    __tablename__ = "shot_definition"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "shot_id", "version"),
        Index("idx_shot_definition_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    shot_id: Mapped[str]
    # The shot plan row this was defined from. NULL when that row was deleted.
    shot_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot_plan.id", ondelete="SET NULL"), default=None
    )
    version: Mapped[int]
    source: Mapped[str]
    # The job that produced it. NULL for a manual version.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ShotContinuityCheck(Base):
    """One check of one scene's shots for continuity (PHASE-023, `Path_ahead.md` Section 26).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every check
    is a new row with the next `version` of that scene, and a stored row is never changed.
    `scene_id` is the slug `id` of the scene inside the project's `scene_discovery` content and
    `shot_plan_id` is the plan row the shots belong to. `round` is how many waves of cut repairs for
    continuity came before this check (0 for a check after a definition the user asked for).
    `inputs` records what the check was made from (the story hash, the artifacts: the scene's
    definition, the shot plan and every shot definition read). `content` is the verdict: one
    entry per boundary (the scene's start, each cut, the scene's end) and the number that do not
    match.
    """

    __tablename__ = "shot_continuity_check"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "version"),
        Index("idx_shot_continuity_check_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    # The shot plan row the shots belong to. NULL when that row was deleted.
    shot_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot_plan.id", ondelete="SET NULL"), default=None
    )
    version: Mapped[int]
    round: Mapped[int]
    source: Mapped[str]
    # The job that produced it. NULL for a manual version.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ShotReferenceManifest(Base):
    """One version of one shot's reference manifest: the pictures it is generated from
    (PHASE-024, `Path_ahead.md` Section 28).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every
    selection is a new row with the next `version` of that shot, and a stored row is never
    changed. `scene_id` is the slug `id` of the scene inside the project's `scene_discovery`
    content, `shot_id` is the shot's id inside that scene's shot plan and `shot_definition_id` is
    the specification row the pictures were chosen for. `inputs` records what the selection was
    built from (the shot definition, the look and state resolution, and the pinned definitions
    of the characters and the environment). `content` is the manifest: the ordered pictures and
    the catalog they were chosen from. There is no job: deterministic code makes it.
    """

    __tablename__ = "shot_reference_manifest"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "shot_id", "version"),
        Index("idx_shot_reference_manifest_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    shot_id: Mapped[str]
    # The shot definition row the pictures were chosen for. NULL when that row was deleted.
    shot_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot_definition.id", ondelete="SET NULL"), default=None
    )
    version: Mapped[int]
    source: Mapped[str]
    # Always NULL for now: no job makes a manifest.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class GenerationRequest(Base):
    """One version of one shot's generation request: the exact request the video model is asked
    for (PHASE-025, `Path_ahead.md` Section 29).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every
    planning is a new row with the next `version` of that shot, and a stored row is never
    changed. `scene_id` is the slug `id` of the scene inside the project's `scene_discovery`
    content, `shot_id` is the shot's id inside that scene's shot plan and
    `shot_reference_manifest_id` is the manifest row the request was planned from. `inputs`
    records what it was built from (the manifest, the shot definition, the shot plan and the
    audio of each dialogue line) and the rules used. `content` is the request: route, endpoint,
    frame count, size, the ordered pictures and the ordered dialogue audios. There is no job:
    deterministic code makes it.
    """

    __tablename__ = "generation_request"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "shot_id", "version"),
        Index("idx_generation_request_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    shot_id: Mapped[str]
    # The manifest row the request was planned from. NULL when that row was deleted.
    shot_reference_manifest_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot_reference_manifest.id", ondelete="SET NULL"), default=None
    )
    version: Mapped[int]
    source: Mapped[str]
    # Always NULL for now: no job makes a request.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ShotPrompt(Base):
    """One version of one shot's compiled H3 prompt (PHASE-026, `Path_ahead.md` Section 30).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every
    compilation is a new row with the next `version` of that shot, and a stored row is never
    changed. `scene_id` is the slug `id` of the scene inside the project's `scene_discovery`
    content, `shot_id` is the shot's id inside that scene's shot plan and
    `generation_request_id` is the request row the prompt was compiled for. `inputs` records
    what it was built from; `content` holds the finished prompt, the model's pieces, the
    labels and the warnings.
    """

    __tablename__ = "shot_prompt"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "shot_id", "version"),
        Index("idx_shot_prompt_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    shot_id: Mapped[str]
    # The request row the prompt was compiled for. NULL when that row was deleted.
    generation_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_request.id", ondelete="SET NULL"), default=None
    )
    version: Mapped[int]
    source: Mapped[str]
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ShotTake(Base):
    """One take of one shot: one run of the video model for it (PHASE-027, `Path_ahead.md`
    Section 31).

    The row is made when the job is queued; `path`, `size_bytes`, `sha256`, `width`, `height`,
    `frame_count`, `duration_s` and `audio` are NULL until the job finishes, and are filled in
    the same transaction that finishes it. `scene_id` is the slug `id` of the scene inside the
    project's `scene_discovery` content and `shot_id` is the shot's id inside that scene's shot
    plan. `shot_prompt_id` and `generation_request_id` are the rows the take was made from
    (`inputs` records them with their versions, D-3). A shot's takes are numbered from 1 and a
    stored take is never changed, except that `selected_at` is set each time the take is chosen:
    when its job finishes, and when the user selects it. The selected take of a shot is its
    ready take with the newest `selected_at`.
    """

    __tablename__ = "shot_take"
    __table_args__ = (
        UniqueConstraint("project_id", "scene_id", "shot_id", "take_number"),
        Index("idx_shot_take_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    shot_id: Mapped[str]
    take_number: Mapped[int]
    # The rows the take was made from. NULL when that row was deleted.
    shot_prompt_id: Mapped[int | None] = mapped_column(
        ForeignKey("shot_prompt.id", ondelete="SET NULL"), default=None
    )
    generation_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_request.id", ondelete="SET NULL"), default=None
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    seed: Mapped[int]
    inputs: Mapped[Any] = mapped_column(JSON)
    path: Mapped[str | None] = mapped_column(default=None)
    size_bytes: Mapped[int | None] = mapped_column(default=None)
    sha256: Mapped[str | None] = mapped_column(default=None)
    width: Mapped[int | None] = mapped_column(default=None)
    height: Mapped[int | None] = mapped_column(default=None)
    frame_count: Mapped[int | None] = mapped_column(default=None)
    duration_s: Mapped[float | None] = mapped_column(default=None)
    audio: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    selected_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class StoryRender(Base):
    """One finished render of a project's story video (PHASE-028, `Path_ahead.md` Section 33).

    The row is made only when a `render_story` job succeeds, in the same transaction that finishes
    it, so it always has its video; a failed render leaves its failed job and nothing else.
    Renders are numbered from 1 per project and a stored render is never changed. `inputs` holds
    the frozen timeline the job rendered (the takes it used for each shot, the narration units, the
    audio values and the plans' ids and versions, D-3) and its warnings; `levels` the loudness
    that was measured and the gain that was applied to each shot's sound and to the narration.
    Whether a render is out of date is worked out on every read, never stored.
    """

    __tablename__ = "story_render"
    __table_args__ = (
        UniqueConstraint("project_id", "render_number"),
        Index("idx_story_render_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    render_number: Mapped[int]
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    levels: Mapped[Any] = mapped_column(JSON)
    path: Mapped[str]
    size_bytes: Mapped[int]
    sha256: Mapped[str]
    width: Mapped[int | None] = mapped_column(default=None)
    height: Mapped[int | None] = mapped_column(default=None)
    frame_count: Mapped[int | None] = mapped_column(default=None)
    duration_s: Mapped[float | None] = mapped_column(default=None)
    audio: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class SpeechUnits(Base):
    """One version of one scene's plan of speech units (PHASE-018, `Path_ahead.md` Section 19).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every run is
    a new row with the next `version` of that scene, and a stored row is never changed.
    `scene_id` is the slug `id` of the scene inside the project's `scene_discovery` content.
    The plan is made by code in the request, so `job_id` is NULL. `inputs` records the
    `scene_events` version the units were cut from and the speech rules used; `content` holds
    the ordered units and the warnings.
    """

    __tablename__ = "speech_units"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "version"),
        Index("idx_speech_units_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    version: Mapped[int]
    source: Mapped[str]
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class SpeechUnitAudio(Base):
    """One speech made, or being made, for one speech unit (PHASE-019, `Path_ahead.md`
    Section 20).

    `audio_key` is a hash of what the audio depends on (the text, the voice, the Breeze mode and
    the instruction), not of the unit's id, which a new plan renumbers: a unit that did not change
    keeps its audio. A row is made when the job is queued and is filled in, in the same
    transaction that finishes the job: `path`, `size_bytes`, `sha256`, `sample_rate` and
    `duration_s`, the length **measured** with ffprobe. They are NULL until then. `inputs` records
    the `speech_units` row and where the voice came from (D-3).
    """

    __tablename__ = "speech_unit_audio"
    __table_args__ = (
        CheckConstraint("kind IN ('narration', 'dialogue')", name="kind_valid"),
        CheckConstraint("mode IN ('clone', 'direction')", name="mode_valid"),
        Index("idx_speech_unit_audio_project_key", "project_id", "audio_key"),
        Index("idx_speech_unit_audio_project_scene", "project_id", "scene_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    scene_id: Mapped[str]
    unit_id: Mapped[str]
    kind: Mapped[str]
    # The discovered character's slug id, NULL for narration.
    speaker_id: Mapped[str | None] = mapped_column(default=None)
    text: Mapped[str]
    mode: Mapped[str]
    instruction: Mapped[str | None] = mapped_column(default=None)
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice.id", ondelete="SET NULL"), default=None
    )
    audio_key: Mapped[str]
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    path: Mapped[str | None] = mapped_column(default=None)
    size_bytes: Mapped[int | None] = mapped_column(default=None)
    sha256: Mapped[str | None] = mapped_column(default=None)
    duration_s: Mapped[float | None] = mapped_column(default=None)
    sample_rate: Mapped[int | None] = mapped_column(default=None)
    inputs: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class LookStateResolution(Base):
    """One version of a project's resolution of the looks and environment states its scenes
    asked for (PHASE-016, `Path_ahead.md` Section 16).

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every run is
    a new row with the next `version` of the project, and a stored row is never changed.
    `inputs` records what the version was built from (the story hash, and the artifacts:
    StoryBible, the list of scenes, the definition of every scene, and the library character or
    environment each subject was linked to). `content` holds, for each scene, the request in the
    model's own words and what it resolved to (`default`, an existing named look or state, or a
    new one).
    """

    __tablename__ = "look_state_resolution"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_look_state_resolution_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int]
    source: Mapped[str]
    # The job that produced it. NULL for a manual version.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


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
        # The lab has taken MiniMax H3 since revision 0017.
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
        CheckConstraint(
            "subject IS NULL OR subject IN ('character', 'narrator')", name="subject_valid"
        ),
        Index("idx_lab_voice_run_created", "created_at"),
        Index("idx_lab_voice_run_job", "job_id"),
        Index("idx_lab_voice_run_project", "project_id"),
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
    # Only for a sample the story pipeline made by itself (PHASE-011): the project, what the
    # voice is for (`character` or `narrator`), the discovered character's slug id, the
    # `design_voice` job that wrote the description, and the provenance (D-3). NULL for a run
    # made by hand in a lab.
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), default=None
    )
    subject: Mapped[str | None] = mapped_column(default=None)
    discovery_id: Mapped[str | None] = mapped_column(default=None)
    design_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)


class NarratorVoice(Base):
    """One version of a story project's narrator voice (PHASE-011). The same provenance shape as
    `StoryBible`: every derivation or choice is a new row with the next `version`, and a stored
    row is never changed. `source` is `ai` for a voice derived from the StoryBible's narration
    style (with the `design_voice` job in `job_id`) and `manual` for a saved voice chosen by
    hand. `inputs` is `{story_bible_version, narration_sha256}` for an `ai` version.
    """

    __tablename__ = "narrator_voice"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_narrator_voice_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int]
    source: Mapped[str]
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice.id", ondelete="SET NULL"), default=None
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class LibraryCharacter(Base):
    """A character of the Character lab's library (Phase 25): a reusable, project-independent
    character an author builds once (profile, look, voice) and then draws on to make audio,
    pictures and clips.

    The narration cast tables (`character`/`location`) that this once stayed apart from are gone
    (PHASE-046). A story project now links each discovered character to one of these rows and
    pins one of its versions (`ProjectCharacterLink`, PHASE-008). A character the pipeline made
    for a project carries that project and the discovered character's id in `origin_project_id`
    and `origin_discovery_id`; a character made in the lab has neither.
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
    # Only for a character the pipeline created from a project's discovered character
    # (PHASE-008): that project, and the discovered character's slug id in it. NULL for a
    # character made in the lab, and for one whose project was deleted.
    origin_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), default=None
    )
    origin_discovery_id: Mapped[str | None] = mapped_column(default=None)
    # The newest structured definition the Character Definition stage wrote (PHASE-009): the
    # `Path_ahead.md` Section 11 JSON, with the species, the visible-mouth flag and the era. NULL
    # until a definition is written. A lab edit of the profile never changes it: it stays as the
    # record of what the model wrote (editing definitions is PHASE-037).
    definition: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)


class CharacterLook(Base):
    """One attempt at a library character's reference pictures (Phase 25): a master picture (on
    a white backdrop) plus four more angles made by editing it, so every later picture and
    clip of the character can be made consistent with it.

    `version` numbers a character's looks from 1. `status` moves `writing_prompt` ->
    `choosing` (candidates are ready, waiting for one to be picked as the master) ->
    `making_angles` -> `ready`, or `failed`. A look the story pipeline makes for a same-person
    variant (PHASE-047) starts as `waiting`, held until its base character's images are ready,
    and then moves to `writing_prompt`. The four candidates to choose the master from are
    `character_look_candidate` rows; the five angle pictures of a ready look are
    `character_reference` rows.

    `reference_image_id` is the author's own picture a look was started from: its candidates
    are then edits of that picture instead of text-to-image pictures. NULL for a look made from
    the profile alone.
    """

    __tablename__ = "character_look"
    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting', 'writing_prompt', 'choosing', 'making_angles', 'ready', "
            "'failed')",
            name="status_valid",
        ),
        Index("idx_character_look_character", "character_id"),
        Index("idx_character_look_project", "project_id"),
        Index("idx_character_look_named_look", "named_look_id"),
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
    # Only for a look the story pipeline made by itself (PHASE-010): the project and the
    # discovered character's slug id it was made for, and its provenance (D-3). NULL for a look
    # made by hand in the Character Lab.
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), default=None
    )
    discovery_id: Mapped[str | None] = mapped_column(default=None)
    inputs: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # Only for a look that holds the pictures of a named look (PHASE-017): such a look is an
    # edit of the character's canonical front picture and never becomes its current look.
    # `use_alter`: `character_named_look.look_id` points back at this table, the intended cycle.
    named_look_id: Mapped[int | None] = mapped_column(
        ForeignKey("character_named_look.id", ondelete="SET NULL", use_alter=True), default=None
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
        # A take can use MiniMax H3 too (revision 0019).
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
    # The number of the character's newest version when the take was made (PHASE-007). NULL for
    # a take made before the character had a version. A plain number, not a link: a version row
    # is found by `(character_id, character_version)`.
    character_version: Mapped[int | None] = mapped_column(default=None)
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


class LibraryCharacterVersion(Base):
    """One immutable snapshot of what defines a library character for production (PHASE-007):
    its profile, its voice and its current look with that look's exact angle pictures.

    `library_character` stays the editable head. A row here is added (never changed) whenever
    the profile, the voice or the current look changes (`services/character_versions`), so a
    project can later pin one version and still read exactly what it was. `version` numbers a
    character's versions from 1. Follows the provenance convention of DATABASE_STRUCTURE.md
    Section 2.1 where it applies: `source`, `version` and `created_at`; there is no job, and no
    upstream artifact, because every change in this phase is made by hand in the lab.

    `profile` is the twelve profile fields by name. `look_references` freezes the look's
    pictures: `[{"angle", "lab_image_id", "cutout_path"}, ...]` sorted by angle name, empty when
    the character had no ready look. Redoing an angle later updates the look's own
    `character_reference` row in place, never this snapshot.
    """

    __tablename__ = "library_character_version"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("character_id", "version"),
        Index("idx_library_character_version_character", "character_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("library_character.id", ondelete="CASCADE")
    )
    version: Mapped[int]
    source: Mapped[str] = mapped_column(default="manual", server_default=text("'manual'"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    profile: Mapped[Any] = mapped_column(JSON)
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice.id", ondelete="SET NULL"), default=None
    )
    voice_description: Mapped[str | None] = mapped_column(default=None)
    look_id: Mapped[int | None] = mapped_column(
        ForeignKey("character_look.id", ondelete="SET NULL"), default=None
    )
    look_references: Mapped[Any] = mapped_column(JSON)
    # The structured definition at this version (PHASE-009), as the head held it. NULL when
    # the character had none.
    definition: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # Provenance of a version the pipeline made (D-3): the job that wrote the definition, and
    # what it was built from (`{"project_id", "discovery_id", "story_sha256", "artifacts",
    # "entry_sha256"}`). Both are NULL for a version made by hand in the lab.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # The pictures of the character's finished named looks (PHASE-017) as this version froze
    # them: `[{"slug", "named_look_id", "look_id", "references": [{"angle", "lab_image_id",
    # "cutout_path"}]}]`, sorted by slug. Empty when there are none.
    named_looks: Mapped[Any] = mapped_column(JSON, default=list, server_default=text("'[]'"))


class ProjectCharacterLink(Base):
    """Links one of a story project's discovered characters to a library character and pins one
    of that character's versions (PHASE-008).

    `discovery_id` is the slug `id` of the discovered character inside the project's
    `character_discovery` content. Only that id ties the link to the list, so a re-run of
    discovery that keeps the id keeps the link. A link whose id is no longer in the newest list
    is kept and shown as such. `pinned_version` is the number of a `library_character_version`
    of `character_id`, found by `(character_id, pinned_version)` and not by a foreign key (the
    way `CharacterTake.character_version` is). The pin never moves because of a lab edit: "a
    newer version is available" is worked out on read by comparing it with the character's
    newest version. `how` is `created` (the pipeline made the library character from the
    discovery entry) or `mapped` (the user chose an existing one). `discovery_version` is the
    version of the discovered list the link was made from.

    A project links each discovered character once, and uses each library character for at
    most one discovered character.
    """

    __tablename__ = "project_character_link"
    __table_args__ = (
        CheckConstraint("how IN ('created', 'mapped')", name="how_valid"),
        UniqueConstraint("project_id", "discovery_id", name="uq_project_character_link_discovery"),
        UniqueConstraint("project_id", "character_id", name="uq_project_character_link_character"),
        Index("idx_project_character_link_character", "character_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    discovery_id: Mapped[str]
    character_id: Mapped[int] = mapped_column(
        ForeignKey("library_character.id", ondelete="CASCADE")
    )
    pinned_version: Mapped[int]
    how: Mapped[str]
    discovery_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class LibraryEnvironment(Base):
    """An environment of the Character lab's library (PHASE-012): a reusable, project-independent
    place an author builds once (profile, canonical reference picture) and a story project can
    link to and pin a version of (`ProjectEnvironmentLink`, PHASE-013).

    This is the editable head, like `library_character`. Every change to the profile adds one
    immutable `library_environment_version` row (`services/environment_versions`). Never
    deleted, only archived.

    `era_kind`, `era_years` and `era_setting` follow the same rules as a character's. A place
    has no mouth, species or voice, so the profile is only a description, the era, an optional
    atmosphere and optional notes.

    An environment the pipeline made for a project carries that project and the discovered
    environment's id in `origin_project_id` and `origin_discovery_id` (PHASE-013); one made in
    the lab has neither. `definition` is the newest structured definition the Environment
    Definition stage wrote (`Path_ahead.md` Section 13, plus the era), NULL until one exists.
    """

    __tablename__ = "library_environment"
    __table_args__ = (
        CheckConstraint("era_kind IN ('present', 'past', 'future')", name="era_kind_valid"),
        Index("idx_library_environment_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    name: Mapped[str]
    # What the place looks like: the architecture or landscape, materials, colours, details.
    description: Mapped[str] = mapped_column(default="", server_default=text("''"))
    era_kind: Mapped[str] = mapped_column(default="present", server_default=text("'present'"))
    # past or future only: how many years from the present. NULL for "present".
    era_years: Mapped[int | None] = mapped_column(default=None)
    # past or future only: what that time looks like here (optional free text).
    era_setting: Mapped[str | None] = mapped_column(default=None)
    # The place's usual mood and light, in words (optional).
    atmosphere: Mapped[str | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(default=None)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # Only for an environment the pipeline created from a project's discovered environment
    # (PHASE-013): that project, and the discovered environment's slug id in it. NULL for an
    # environment made in the lab, and for one whose project was deleted.
    origin_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), default=None
    )
    origin_discovery_id: Mapped[str | None] = mapped_column(default=None)
    # The newest structured definition the Environment Definition stage wrote (PHASE-013). NULL
    # until a definition is written. A lab edit of the profile never changes it.
    definition: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)


class ProjectEnvironmentLink(Base):
    """Links one of a story project's discovered environments to a library environment and pins
    one of that environment's versions (PHASE-013). The same shape as `ProjectCharacterLink`.

    `discovery_id` is the slug `id` of the discovered environment inside the project's
    `environment_discovery` content. Only that id ties the link to the list, so a re-run of
    discovery that keeps the id keeps the link; a link whose id is no longer in the newest list
    is kept and shown as orphaned. `pinned_version` is the number of a
    `library_environment_version` of `environment_id`, found by `(environment_id,
    pinned_version)` and not by a foreign key. A lab edit never moves it: "a newer version is
    available" is worked out on read. `how` is `created` (the pipeline made the library
    environment from the discovery entry) or `mapped` (the user chose an existing one).
    `discovery_version` is the version of the discovered list the link was made from.

    A project links each discovered environment once, and uses each library environment for at
    most one discovered environment.
    """

    __tablename__ = "project_environment_link"
    __table_args__ = (
        CheckConstraint("how IN ('created', 'mapped')", name="how_valid"),
        UniqueConstraint(
            "project_id", "discovery_id", name="uq_project_environment_link_discovery"
        ),
        UniqueConstraint(
            "project_id", "environment_id", name="uq_project_environment_link_environment"
        ),
        Index("idx_project_environment_link_environment", "environment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    discovery_id: Mapped[str]
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("library_environment.id", ondelete="CASCADE")
    )
    pinned_version: Mapped[int]
    how: Mapped[str]
    discovery_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class LibraryEnvironmentVersion(Base):
    """One immutable snapshot of a library environment's profile (PHASE-012), plus its canonical
    reference picture.

    `profile` is the seven profile fields by name and never changes after the row is written.
    `reference_image_id` is the one exception: the canonical picture the author chose for this
    version. It is set (and may be replaced) only while the version is the environment's
    newest; once an edit adds a newer version, this one is frozen and keeps its own picture.
    An edit never carries the picture forward, because it was made for the old text.
    Provenance (D-3): `source`, `version` and `created_at`; a version the Environment Definition
    stage wrote (PHASE-013) also records `job_id` and `inputs` (what it was built from) and the
    `definition` as the head held it. All three are NULL for a version made by hand in the lab
    (the definition is carried forward from the head when there is one).
    """

    __tablename__ = "library_environment_version"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("environment_id", "version"),
        Index("idx_library_environment_version_environment", "environment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("library_environment.id", ondelete="CASCADE")
    )
    version: Mapped[int]
    source: Mapped[str] = mapped_column(default="manual", server_default=text("'manual'"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    profile: Mapped[Any] = mapped_column(JSON)
    reference_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_image.id", ondelete="SET NULL"), default=None
    )
    # The structured definition at this version (PHASE-013), as the head held it. NULL when the
    # environment had none.
    definition: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # Provenance of a version the pipeline made (D-3): the job that wrote the definition, and
    # what it was built from (`{"project_id", "discovery_id", "story_sha256", "entry_sha256",
    # "artifacts"}`). Both are NULL for a version made by hand in the lab.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # The pictures of the environment's states (PHASE-017) as this version froze them:
    # `[{"slug", "state_id", "reference_image_id"}]`, sorted by slug. Empty when there are none.
    states: Mapped[Any] = mapped_column(JSON, default=list, server_default=text("'[]'"))


class EnvironmentReference(Base):
    """One attempt to make the canonical picture of an environment version (PHASE-012): a
    `write_environment_prompt` job writes the prompt, then four `lab_image` runs make the
    candidates the author chooses from.

    `status` is `writing_prompt` (the job is writing the prompt), `ready` (the candidates were
    started; each one's own state is read live from its `lab_run`) or `failed` (`error` says
    why). The attempt is made for one version (`version_id`), the environment's newest when it
    started.

    An attempt the story pipeline made for a project (PHASE-013) carries that project and the
    discovered environment in `project_id` and `discovery_id`. It makes one candidate, and the
    candidate becomes the version's canonical picture by itself; a lab attempt makes four and
    waits for the author to choose.
    """

    __tablename__ = "environment_reference"
    __table_args__ = (
        CheckConstraint("status IN ('writing_prompt', 'ready', 'failed')", name="status_valid"),
        Index("idx_environment_reference_environment", "environment_id"),
        Index("idx_environment_reference_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("library_environment.id", ondelete="CASCADE")
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("library_environment_version.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(
        default="writing_prompt", server_default=text("'writing_prompt'")
    )
    prompt: Mapped[str | None] = mapped_column(default=None)
    prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    error: Mapped[str | None] = mapped_column(default=None)
    # Only for an attempt the story pipeline made (PHASE-013): the project and the discovered
    # environment it was made for. NULL for an attempt made in the lab.
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), default=None
    )
    discovery_id: Mapped[str | None] = mapped_column(default=None)


class EnvironmentReferenceCandidate(Base):
    """One of the (four) pictures made for an `environment_reference` to choose from
    (PHASE-012). A pure link to the `lab_run`/`lab_image` that made it: its own status is read
    from that run, never duplicated here.
    """

    __tablename__ = "environment_reference_candidate"
    __table_args__ = (Index("idx_environment_reference_candidate_reference", "reference_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    reference_id: Mapped[int] = mapped_column(
        ForeignKey("environment_reference.id", ondelete="CASCADE")
    )
    lab_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_run.id", ondelete="SET NULL"), default=None
    )


class CharacterNamedLook(Base):
    """A named look of a library character (PHASE-016), for example "night clothes": a short
    `slug`, a `name` and a text `description`. The character's canonical look is the implicit
    "default" and has no row here (`slug` can never be `default`).

    This is a record that points at a look, not a look: a `character_look` is one attempt at
    making pictures. `look_id` stays NULL until PHASE-017 makes the pictures of this named look.

    Named looks belong to the library character, not to one of its versions, so any project that
    uses the character can reuse them. Creating one adds no version and moves no pin.
    `origin_project_id` and `job_id` say which project's resolution run created it (NULL for one
    made by hand, or when the project or job is gone).
    """

    __tablename__ = "character_named_look"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        CheckConstraint("slug <> 'default'", name="slug_not_default"),
        UniqueConstraint("character_id", "slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("library_character.id", ondelete="CASCADE")
    )
    slug: Mapped[str]
    name: Mapped[str]
    description: Mapped[str]
    source: Mapped[str]
    origin_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), default=None
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    look_id: Mapped[int | None] = mapped_column(
        ForeignKey("character_look.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class EnvironmentState(Base):
    """A named state of a library environment (PHASE-016), for example "night": a short `slug`,
    a `name` and a text `description`. The environment's canonical reference is the implicit
    "default" and has no row here (`slug` can never be `default`).

    `reference_image_id` stays NULL until PHASE-017 makes the state's picture. Like a named
    look, a state belongs to the library environment and not to one version, and creating one
    adds no version and moves no pin.
    """

    __tablename__ = "environment_state"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        CheckConstraint("slug <> 'default'", name="slug_not_default"),
        UniqueConstraint("environment_id", "slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("library_environment.id", ondelete="CASCADE")
    )
    slug: Mapped[str]
    name: Mapped[str]
    description: Mapped[str]
    source: Mapped[str]
    origin_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), default=None
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    reference_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_image.id", ondelete="SET NULL"), default=None
    )
    # The edit run that makes the state's picture (PHASE-017), and what it was made from
    # (`{"project_id", "discovery_id", "environment_version", "source_image_id",
    # "resolution_version"}`). NULL until a picture is started.
    lab_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_run.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
