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
        CheckConstraint(
            "speech_mode IN ('both', 'no_dialogue', 'no_narration')", name="speech_mode_valid"
        ),
        CheckConstraint("kind IN ('story', 'explainer')", name="kind_valid"),
        CheckConstraint("voice_track IN ('lines', 'continuous')", name="voice_track_valid"),
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
    # Chosen when the project is created and never changed: `both`, `no_dialogue` (only a
    # narrator speaks) or `no_narration` (nobody narrates).
    speech_mode: Mapped[str] = mapped_column(default="both", server_default=text("'both'"))
    # Chosen when the project is created and never changed: `story` or `explainer` (a presenter
    # from the Character Lab speaks the script on camera or as a voice-over over B-roll).
    kind: Mapped[str] = mapped_column(default="story", server_default=text("'story'"))
    # The keys of the review points the project has enabled (`services/review_points.py`), in
    # the order of the pipeline. A run of the story pipeline waits for the user at each one.
    review_points: Mapped[Any] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    # Whether the story gets planned music (MUSIC-006, MD-21). When off, the music steps are
    # skipped as complete. Can be changed at any time.
    music_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    # Whether a render includes the beds and the point sounds Stable Audio makes (MUSIC-012). Only
    # matters while `music_enabled` is on; changing it makes the render out of date, not the
    # placement.
    ambience_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    # Whether an explainer's render draws word-synced captions, and whether it draws callouts
    # (EXPLAINER-007). Only read for an explainer, at render time, so they can be changed at
    # any time.
    captions: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    callouts: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    # FLOW-002. Chosen when the project is created and never changed: `lines` (each line is its
    # own speech) or `continuous` (one voice take per scene, the picture cut on top of it). Only
    # an explainer can be `continuous`; a story is always `lines`.
    voice_track: Mapped[str] = mapped_column(default="lines", server_default=text("'lines'"))
    # FLOW-002. The owner's text that steers the voice of every take of a `continuous`
    # explainer (at most 500 characters). NULL means the Story Bible's narration style, or the
    # default. Can be changed at any time.
    presenter_delivery: Mapped[str | None] = mapped_column(default=None)


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
        # revision 0047, and the render of the story's video, since revision 0048, and the
        # check of the shots' takes, since revision 0049, and the run of the whole story
        # pipeline, since revision 0050, and the speech-recognition check of a take's
        # dialogue, since revision 0051, and the choice of a shot's reference pictures by the
        # language model, since revision 0052, and the two Music lab jobs, since revision 0057, and
        # the staging of a scene, since revision 0058, and the planning of an environment's views
        # and the writing of a view's prompt, since revision 0059, and the Music Bible, since
        # revision 0065, and the writing of a theme's prompt, since revision 0066, and the music
        # plan, since revision 0067, and the cue detail and its audit, since revision 0068, and
        # the rewrite of a rejected take's prompt, since revision 0069, and the placement of the
        # music on the timeline, since revision 0070, and the preview of a music mix, since revision
        # 0071, and the timing of a speech's words, since revision 0073, and the callout plan,
        # since revision 0074.
        CheckConstraint(
            "type IN ('lab_image', 'lab_video', 'write_lab_video_prompt', 'lab_voice', "
            "'write_character_look_prompt', 'write_character_take_prompt', 'write_story_bible', "
            "'discover_characters', 'discover_environments', 'discover_scenes', "
            "'define_character', 'discover_relations', 'design_voice', "
            "'write_environment_prompt', 'define_environment', 'define_scene', "
            "'extract_events', 'resolve_looks_states', 'synthesize_speech_unit', "
            "'plan_shots', 'define_shot', 'check_shot_continuity', 'repair_shot_cut', "
            "'compile_shot_prompt', 'generate_shot', 'render_story', 'check_shot_takes', "
            "'story_pipeline', 'check_take_dialogue', 'select_shot_references', "
            "'lab_music', 'write_lab_music_prompt', 'stage_scene', "
            "'plan_environment_views', 'write_environment_view_prompt', 'write_music_bible', "
            "'write_music_theme_prompt', 'write_music_plan', 'write_music_cue', "
            "'audit_music_cues', 'rewrite_music_prompt', 'place_music', "
            "'preview_music_mix', 'time_speech_words', 'write_callout_plan', "
            "'time_lab_speech_words', 'render_av_test')",
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


class MusicBible(Base):
    """One version of a story project's Music Bible (MUSIC-006).

    The same provenance shape as `StoryBible`: every run, choice of another direction or edit is
    a new row with the next `version`, and a stored row is never changed. `directions` are the
    four directions written at level 0a (`[{id, name, summary, instruments, feel, differs_by}]`),
    `choice` is `{direction_id, by, reasons}` (`by` is `ai` or `owner`), and `content` is the
    Bible itself (concept, sound world, musical feel, themes, arc, restraint, ambience).
    `inputs` holds the story hash and the exact upstream versions the version was built from.
    """

    __tablename__ = "music_bible"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_music_bible_project", "project_id"),
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
    directions: Mapped[Any] = mapped_column(JSON)
    choice: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class MusicPlan(Base):
    """One version of a story project's music plan (MUSIC-008, revision 0067).

    The same provenance shape as `MusicBible`: every run or edit is a new row with the next
    `version`, and a stored row is never changed. `timeline` is the condensed story timeline the
    plan was written against (`services/music_timeline`), `draft` the plan as first written,
    `rounds` the critics' notes and the revisions (`[{round, critiques, revised, failure}]`),
    `content` the final plan (`{cues, boundaries, sound_requests}`) and `facts` measured facts
    about it. `inputs` holds the Music Bible, every scene's upstream rows and the timeline hash.
    """

    __tablename__ = "music_plan"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_music_plan_project", "project_id"),
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
    timeline: Mapped[Any] = mapped_column(JSON)
    draft: Mapped[Any] = mapped_column(JSON)
    rounds: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    facts: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class CalloutPlan(Base):
    """One version of an explainer's callout plan (EXPLAINER-009, revision 0074).

    Every run or edit is a new row with the next `version`, and a stored row is never changed.
    `content` is `{accent, callouts}` (`services/callout_plan_writer`). `inputs` holds the Story
    Bible and every scene's speech units it was built from, and the rules it was checked against,
    so staleness is worked out on read.
    """

    __tablename__ = "callout_plan"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "version"),
        Index("idx_callout_plan_project", "project_id"),
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


class MusicPlacement(Base):
    """One placement run of a story project's music (MUSIC-011, revision 0070).

    Versioned like `MusicPlan` and never changed. `plan_id` is the plan version it was made for,
    `inputs` what it was made from (so staleness is worked out on read), and `content` every
    placement in samples at 48 kHz with its fades, joins, the fallbacks used, the sounds H3
    makes and the language model's choices (`services/music_placer`).
    """

    __tablename__ = "music_placement"
    __table_args__ = (
        UniqueConstraint("project_id", "version"),
        Index("idx_music_placement_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    version: Mapped[int]
    plan_id: Mapped[int] = mapped_column(ForeignKey("music_plan.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class MusicCue(Base):
    """One version of one cue of one music plan version (MUSIC-009, revision 0068).

    A stored row is never changed: the model's run is `source` `ai`, and the audit's fixes are a
    new row with `source` `audit`. `detail` is what level 2 wrote (anchors with their resolved
    seconds, the broad order of moods, hit requests, mix notes and fades), `items` are the
    things to generate, each with its model, requested length and prompt wordings (level 3), and
    `pushback` is the cue's objection to the plan (`{problem, suggestion, sent}`), or NULL.
    `inputs` records the plan, the Music Bible, the theme and the shot definitions it used.
    """

    __tablename__ = "music_cue"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'audit')", name="source_valid"),
        UniqueConstraint("plan_id", "cue_id", "version"),
        Index("idx_music_cue_plan", "plan_id", "cue_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("music_plan.id", ondelete="CASCADE"))
    cue_id: Mapped[str]
    version: Mapped[int]
    source: Mapped[str]
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    detail: Mapped[Any] = mapped_column(JSON)
    items: Mapped[Any] = mapped_column(JSON)
    pushback: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class MusicCueAudit(Base):
    """One audit of all the cue prompts of a music plan version (MUSIC-009, revision 0068).

    `findings` is what the audit call answered (`{verdict, fixes}`), `inputs` the ids of the cue
    rows it read, and `result_row_ids` the ids of the newest cue rows once its fixes were
    applied. The audit is current while those are still the newest rows.
    """

    __tablename__ = "music_cue_audit"
    __table_args__ = (Index("idx_music_cue_audit_plan", "plan_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("music_plan.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    findings: Mapped[Any] = mapped_column(JSON)
    result_row_ids: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class MusicTake(Base):
    """One take of one thing a music plan's cue needs generated (MUSIC-010, revision 0069).

    `item_id` is the id of an item of the cue's detail (`music_cue.items`): the cue itself
    (`cue_3`) or one of its hits (`cue_3/hit_1`). The audio is the Music lab run `lab_run_id`.
    `fields` are the prompt fields as sent, `check_result` the technical check with the measured
    facts, and `cue_snapshot` what lock matching reads. `detail_sha256` is the version of the
    cue's detail the take was made for. `round` is 1 for the first takes, and one more for the
    takes made after a rejection with a note (`feedback`) or after a fresh start. `retry_of_id`
    is the failed take a retry replaces. The selected take of an item is its take that is not
    rejected and has the newest `selected_at`; `locked_at` can only be set on a selected take.
    Nothing else about a stored take changes.
    """

    __tablename__ = "music_take"
    __table_args__ = (
        CheckConstraint(
            "selected_by IS NULL OR selected_by IN ('auto', 'owner')", name="selected_by_valid"
        ),
        CheckConstraint(
            "locked_at IS NULL OR selected_at IS NOT NULL", name="lock_needs_selection"
        ),
        Index("idx_music_take_item", "plan_id", "cue_id", "item_id"),
        Index("idx_music_take_run", "lab_run_id"),
        Index("idx_music_take_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("music_plan.id", ondelete="CASCADE"))
    cue_id: Mapped[str]
    item_id: Mapped[str]
    cue_row_id: Mapped[int | None] = mapped_column(
        ForeignKey("music_cue.id", ondelete="SET NULL"), default=None
    )
    detail_sha256: Mapped[str]
    round: Mapped[int]
    # The wording (1-based) of the cue row's item this take was made from; NULL for a take made
    # from a rewritten prompt.
    wording: Mapped[int | None] = mapped_column(default=None)
    retry_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("music_take.id", ondelete="SET NULL"), default=None
    )
    lab_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_music_run.id", ondelete="SET NULL"), default=None
    )
    seed: Mapped[int]
    fields: Mapped[Any] = mapped_column(JSON)
    requested_s: Mapped[float]
    cue_snapshot: Mapped[Any] = mapped_column(JSON)
    # `{of_take_id, note, job_id, rejected_at, claim}` for a take made after a rejection.
    feedback: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    check_result: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    selected_at: Mapped[datetime | None] = mapped_column(default=None)
    selected_by: Mapped[str | None] = mapped_column(default=None)
    rejected_at: Mapped[datetime | None] = mapped_column(default=None)
    reject_note: Mapped[str | None] = mapped_column(default=None)
    locked_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class MusicTheme(Base):
    """One generation of one theme of a project's Music Bible (MUSIC-007, revision 0066).

    `theme_id` is the Bible's id (`theme_1`, ...). `fields` are the ACE-Step fields the model
    wrote for the theme's canonical recording, `inputs` is what the row was made from (the Bible
    row and a hash of the theme's own entry), and the chosen candidate (`chosen_candidate_id`)
    is the canonical recording: `chosen_by` is `auto` (the first one that passed the check) or
    `owner`. A stored row is never changed except for the choice; making the theme again adds
    a row with the next `version`.
    """

    __tablename__ = "music_theme"
    __table_args__ = (
        CheckConstraint(
            "chosen_by IS NULL OR chosen_by IN ('auto', 'owner')", name="chosen_by_valid"
        ),
        UniqueConstraint("project_id", "theme_id", "version"),
        Index("idx_music_theme_project", "project_id", "theme_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    bible_id: Mapped[int] = mapped_column(ForeignKey("music_bible.id", ondelete="CASCADE"))
    theme_id: Mapped[str]
    version: Mapped[int]
    # The `write_music_theme_prompt` job that wrote the fields.
    prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    fields: Mapped[Any] = mapped_column(JSON)
    inputs: Mapped[Any] = mapped_column(JSON)
    # `use_alter`: `music_theme_candidate.theme_row_id` points back at this table, the intended
    # cycle.
    chosen_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("music_theme_candidate.id", ondelete="SET NULL", use_alter=True), default=None
    )
    chosen_by: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class MusicThemeCandidate(Base):
    """One candidate recording of a theme (MUSIC-007). A link to the `lab_music_run` that made
    it: the audio, its status and its measurements are read from that run. `check_result` is the
    technical check (`services/music_themes.check_recording`), NULL until the audio exists.
    """

    __tablename__ = "music_theme_candidate"
    __table_args__ = (
        UniqueConstraint("theme_row_id", "position"),
        Index("idx_music_theme_candidate_run", "lab_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_row_id: Mapped[int] = mapped_column(ForeignKey("music_theme.id", ondelete="CASCADE"))
    # 1, 2, 3, ... in the order they were made.
    position: Mapped[int]
    lab_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_music_run.id", ondelete="SET NULL"), default=None
    )
    seed: Mapped[int]
    check_result: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class MusicThemeVersion(Base):
    """One emotional version of a theme (MUSIC-007), made from the candidate that was the
    canonical recording then (`candidate_id`). `method` is `text` (fresh text-to-music with the
    theme described in the prompt, MD-6); a later method adds a value. The newest row per
    (theme row, candidate, emotion) is the current one. `lab_run_id` is the recording.
    """

    __tablename__ = "music_theme_version"
    __table_args__ = (
        CheckConstraint("method IN ('text')", name="method_valid"),
        Index("idx_music_theme_version_theme", "theme_row_id"),
        Index("idx_music_theme_version_run", "lab_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_row_id: Mapped[int] = mapped_column(ForeignKey("music_theme.id", ondelete="CASCADE"))
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("music_theme_candidate.id", ondelete="CASCADE")
    )
    emotion: Mapped[str]
    method: Mapped[str]
    # The `write_music_theme_prompt` job that wrote the caption. NULL for a regeneration, which
    # reuses the fields of the version it replaces.
    prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    fields: Mapped[Any] = mapped_column(JSON)
    lab_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_music_run.id", ondelete="SET NULL"), default=None
    )
    seed: Mapped[int]
    check_result: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
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


class SceneStaging(Base):
    """One version of one scene's staging (PHASE-051, `Path_ahead.md` Section 46): where each
    character of the scene stands, which way they face, which side of the screen they appear on
    and which side of the place is behind them, plus the axis of the main conversation, the
    background of the group and the moves that change a placement after an event.

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every run is
    a new row with the next `version` of that scene, and a stored row is never changed.
    `scene_id` is the slug `id` of the scene inside the project's `scene_discovery` content.
    `inputs` records what the version was built from (the story hash and the artifacts: the
    StoryBible, the scene's definition, the scene's events and the environment's definition).
    """

    __tablename__ = "scene_staging"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "scene_id", "version"),
        Index("idx_scene_staging_project_scene", "project_id", "scene_id"),
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
    the catalog they were chosen from. The fixed rule makes it with no job (`job_id` NULL); the
    language model's choice (PHASE-033) is made by a `select_shot_references` job, whose id is in
    `job_id`.
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
    # The `select_shot_references` job that made it, or NULL when the fixed rule made it.
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
    when its job finishes, and when the user selects it (which also stamps `accepted_at` on a
    failed check). The selected take of a shot is its ready take with the newest `selected_at`.
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
    # The technical check of the clip (PHASE-029, `services/take_validation.py`). NULL: not
    # checked. Only a take that passed is selected by itself; the user may select a failed one,
    # which adds `accepted_at` to the failed check.
    validation: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    # The speech-recognition check of the shot's dialogue (PHASE-031,
    # `services/dialogue_check.py`). NULL: not checked, and always NULL for a take whose shot
    # carries no dialogue. A take with dialogue is selected by itself only when this passed too.
    dialogue_check: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
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


class SpeechWordTiming(Base):
    """The start and end time of every script word of one speech (EXPLAINER-007, E-12).

    One row per `speech_unit_audio` row, so a new speech (a new audio row) gets new timings and
    an unchanged unit keeps its old ones. `words` is the script's words in order, each
    `{"text", "start", "end"}` in seconds from the start of the file. `source` says how the
    times were made: `parakeet` (the heard words were matched to the script words) or
    `estimated` (too few words matched, so each word got its share of the speech's length by
    character count). `match_percent` is the share of script words that matched exactly, and
    `threshold` is the setting it was judged against. Written once with its finished job.
    """

    __tablename__ = "speech_word_timing"
    __table_args__ = (
        CheckConstraint("source IN ('parakeet', 'estimated')", name="source_valid"),
        Index("idx_speech_word_timing_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    speech_unit_audio_id: Mapped[int] = mapped_column(
        ForeignKey("speech_unit_audio.id", ondelete="CASCADE"), unique=True
    )
    source: Mapped[str]
    match_percent: Mapped[float]
    threshold: Mapped[int]
    words: Mapped[Any] = mapped_column(JSON)
    heard_text: Mapped[str] = mapped_column(default="", server_default=text("''"))
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
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
    the raw response (image data replaced by sizes), so results can be compared later. Deleted
    only with the character or environment it was made for (PHASE-055).
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
    that run's file. A voice is never deleted by the labs, nor with a project (PHASE-055).
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


class LabMusicRun(Base):
    """One piece of audio the Music lab made, or is making (revision 0057).

    Like `lab_voice_run`, the job holds the status and the exact request, and this row holds
    what the page lists and compares: the kind of sound, the model, the brief, the prompt fields
    that were sent, the seed and, once the job has finished, the stored FLAC or WAV under
    `media/lab/`. The runs that one click starts (several models, several seeds) share a
    `group_key`, so the page shows them side by side. `verdict` and `note` are what a person
    decided after listening.
    """

    __tablename__ = "lab_music_run"
    __table_args__ = (
        CheckConstraint("kind IN ('score', 'song', 'stem', 'sfx', 'ambience')", name="kind_valid"),
        CheckConstraint(
            "model IN ('ace-step-1.5', 'yue2', 'stable-audio-3', 'stable-audio-open', 'ltx-audio')",
            name="model_valid",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('good', 'usable', 'bad')", name="verdict_valid"
        ),
        CheckConstraint(
            "operation IS NULL OR operation IN ('repaint', 'cover', 'inpaint', 'transform')",
            name="operation_valid",
        ),
        CheckConstraint(
            "(operation IS NULL AND source_run_id IS NULL AND source_id IS NULL) "
            "OR (operation IS NOT NULL AND (source_run_id IS NULL) + (source_id IS NULL) = 1)",
            name="source_matches_operation",
        ),
        Index("idx_lab_music_run_created", "created_at"),
        Index("idx_lab_music_run_group", "group_key"),
        Index("idx_lab_music_run_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    # The `lab_music` job that makes the audio.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    # The `write_lab_music_prompt` job that wrote the fields, or NULL when they were typed.
    prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    group_key: Mapped[str]
    kind: Mapped[str]
    model: Mapped[str]
    endpoint: Mapped[str]
    # The brief, and the prompt fields as they were sent to this model (both as the user left
    # them). `params` is `{seed}`.
    brief: Mapped[Any] = mapped_column(JSON)
    fields: Mapped[Any] = mapped_column(JSON)
    params: Mapped[Any] = mapped_column(JSON)
    # The result, NULL until the job has finished and the audio was stored.
    path: Mapped[str | None] = mapped_column(default=None)
    size_bytes: Mapped[int | None] = mapped_column(default=None)
    sha256: Mapped[str | None] = mapped_column(default=None)
    duration_s: Mapped[float | None] = mapped_column(default=None)
    sample_rate: Mapped[int | None] = mapped_column(default=None)
    channels: Mapped[int | None] = mapped_column(default=None)
    # What a person decided after listening: good, usable or bad. NULL until then.
    verdict: Mapped[str | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(default=None)
    # Editing (MUSIC-004, revision 0063). NULL `operation`: text-to-audio. Otherwise one of
    # repaint, cover, inpaint, transform, started from exactly one source: an earlier run
    # (`source_run_id`) or an uploaded or joined file (`source_id`). The window or strength is in
    # `fields`.
    operation: Mapped[str | None] = mapped_column(default=None)
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_music_run.id", ondelete="SET NULL"), default=None
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_music_source.id", ondelete="SET NULL"), default=None
    )


class LabMusicSource(Base):
    """An audio file made for editing in the Music lab (MUSIC-004, revision 0063): a recording a
    person uploaded (`kind` `upload`), or two lab runs put end to end (`kind` `join`). The file is
    under `media/lab/`. For a join, `recipe` is `{parts: [{run_id, start_s, end_s}], gap_s,
    tail_s}`, where the times are seconds in the joined file, so the seam is `parts[0].end_s`
    plus half the gap. Rows are never changed or deleted.
    """

    __tablename__ = "lab_music_source"
    __table_args__ = (
        CheckConstraint("kind IN ('upload', 'join')", name="kind_valid"),
        Index("idx_lab_music_source_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    kind: Mapped[str]
    label: Mapped[str]
    path: Mapped[str]
    size_bytes: Mapped[int]
    sha256: Mapped[str]
    duration_s: Mapped[float]
    sample_rate: Mapped[int | None] = mapped_column(default=None)
    channels: Mapped[int | None] = mapped_column(default=None)
    recipe: Mapped[Any | None] = mapped_column(JSON, default=None)


class LabMusicTrialCase(Base):
    """One case of a Music lab trial round, with the guide text the review screen shows
    (MUSIC-005, revision 0064).

    The case's content is written by the trial helper (`music_lab_trials/trigger.py`), which also
    starts the runs: `guide` is what to verify, what was done and the prompt in plain words (its
    shape is in `DATABASE_STRUCTURE.md`), `run_ids` are the lab runs the case started and
    `source_ids` the recordings it made locally (crossfades). `answer` and `answer_note` are the
    person's answer to the case's question. The runs keep their own verdicts and notes.
    """

    __tablename__ = "lab_music_trial_case"
    __table_args__ = (
        CheckConstraint("answer IS NULL OR answer IN ('yes', 'partly', 'no')", name="answer_valid"),
        Index("idx_lab_music_trial_case_order", "sort_order"),
    )

    # A short name such as `I2-fear`.
    id: Mapped[str] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    # The letter of the group of cases (I, J, K, L, M).
    trial_group: Mapped[str]
    sort_order: Mapped[int]
    title: Mapped[str]
    guide: Mapped[Any] = mapped_column(JSON)
    run_ids: Mapped[Any] = mapped_column(JSON)
    source_ids: Mapped[Any] = mapped_column(JSON)
    answer: Mapped[str | None] = mapped_column(default=None)
    answer_note: Mapped[str | None] = mapped_column(default=None)


class AudioMeasurement(Base):
    """What was measured in one audio file (MUSIC-003, `services/audio_measurements.py`).

    The row belongs to the file's content, not to a table that holds the file: it is keyed by the
    file's `sha256`, which every audio table already stores, so a lab run, a speech unit's
    audio, an H3 take and a later music take all share it, and the same bytes are measured once.
    `analysis_version` is `audio_analysis.ANALYSIS_VERSION` when the row was made: after the
    analysis changes, a file is measured again and the old row is simply not read. `content` is
    the result (its shape is in `DATABASE_STRUCTURE.md`). A stored row is never changed.
    """

    __tablename__ = "audio_measurement"
    __table_args__ = (UniqueConstraint("sha256", "analysis_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str]
    analysis_version: Mapped[int]
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


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

    Deleted only by the user, for good (`services/library_deletion`, PHASE-055); a project that
    used it is flagged, not changed.
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
    # The version whose `inputs` stand for this project's own definition, set when the project
    # adopted a version made by hand (PHASE-042). NULL: the pinned version's own `inputs` count.
    provenance_version: Mapped[int | None] = mapped_column(default=None)
    how: Mapped[str]
    discovery_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class LibraryEnvironment(Base):
    """An environment of the Character lab's library (PHASE-012): a reusable, project-independent
    place an author builds once (profile, canonical reference picture) and a story project can
    link to and pin a version of (`ProjectEnvironmentLink`, PHASE-013).

    This is the editable head, like `library_character`. Every change to the profile adds one
    immutable `library_environment_version` row (`services/environment_versions`). Archived, or
    deleted for good by the user (`services/library_deletion`, PHASE-055).

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
    # As on `ProjectCharacterLink` (PHASE-042).
    provenance_version: Mapped[int | None] = mapped_column(default=None)
    how: Mapped[str]
    discovery_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ProjectCastCharacter(Base):
    """A library character the user put in a story project's cast (PHASE-048).

    The cast is sent to the model when the project's characters are discovered, so the model can
    say which discovered character is one of these. `mode` says what the pipeline does with a
    cast character that a discovered one was linked to: `as_is` keeps its definition, look and
    voice, `rewrite_text` keeps its look and voice but writes the text definition again for this
    story. A project lists each library character at most once.
    """

    __tablename__ = "project_cast_character"
    __table_args__ = (
        CheckConstraint("mode IN ('as_is', 'rewrite_text')", name="mode_valid"),
        UniqueConstraint("project_id", "character_id", name="uq_project_cast_character_character"),
        Index("idx_project_cast_character_character", "character_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    character_id: Mapped[int] = mapped_column(
        ForeignKey("library_character.id", ondelete="CASCADE")
    )
    mode: Mapped[str] = mapped_column(default="as_is", server_default=text("'as_is'"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ProjectCastEnvironment(Base):
    """A library environment the user put in a story project's cast (PHASE-048). The same shape
    and meaning as `ProjectCastCharacter`; `rewrite_text` keeps the canonical picture.
    """

    __tablename__ = "project_cast_environment"
    __table_args__ = (
        CheckConstraint("mode IN ('as_is', 'rewrite_text')", name="mode_valid"),
        UniqueConstraint(
            "project_id", "environment_id", name="uq_project_cast_environment_environment"
        ),
        Index("idx_project_cast_environment_environment", "environment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("library_environment.id", ondelete="CASCADE")
    )
    mode: Mapped[str] = mapped_column(default="as_is", server_default=text("'as_is'"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


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
    # The pictures of the environment's views (PHASE-052) as this version froze them:
    # `[{"slug", "view_id", "reference_image_id", "states": []}]`, sorted by slug. Empty when
    # there are none.
    views: Mapped[Any] = mapped_column(JSON, default=list, server_default=text("'[]'"))


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


class EnvironmentView(Base):
    """A named view of a library environment (PHASE-052, `Path_ahead.md` Section 46): the place
    seen from another direction than its master picture, for example "the wall behind the
    stove". `side` is relative to the master picture (`ahead`, `left`, `right` or `behind`) and
    `framing` how close the view is. The master picture is the implicit `establishing` view and
    has no row here (`slug` can never be `establishing`).

    Like a state, a view belongs to the library environment and not to one version: creating
    one adds no version and moves no pin. Its picture is an edit of the master picture
    (`reference_image_id`, made by `lab_run_id`); the written edit prompt is `prompt` (written
    by the job `prompt_job_id`). `inputs` records what the picture was made from
    (`{"project_id", "discovery_id", "master_version", "source_image_id", "plan_version"}`); a
    picture is out of date when `source_image_id` is no longer the pinned master. `inputs` is
    NULL for a view made by hand.
    """

    __tablename__ = "environment_view"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        CheckConstraint("slug <> 'establishing'", name="slug_not_establishing"),
        CheckConstraint("side IN ('ahead', 'left', 'right', 'behind')", name="side_valid"),
        CheckConstraint("framing IN ('wide', 'medium', 'close')", name="framing_valid"),
        UniqueConstraint("environment_id", "slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("library_environment.id", ondelete="CASCADE")
    )
    slug: Mapped[str]
    name: Mapped[str]
    side: Mapped[str]
    framing: Mapped[str]
    # The zone of the environment's spatial plan the view looks at, when it looks at one.
    zone: Mapped[str | None] = mapped_column(default=None)
    description: Mapped[str]
    source: Mapped[str]
    origin_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), default=None
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    prompt: Mapped[str | None] = mapped_column(default=None)
    prompt_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    reference_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_image.id", ondelete="SET NULL"), default=None
    )
    lab_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_run.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class EnvironmentViewPlan(Base):
    """One version of the plan of the views one environment needs in one project (PHASE-052,
    `Path_ahead.md` Section 46): which views the environment has for the project's scenes (new
    ones and reused library ones) and, for every scene, which views cover each side that is
    behind a character and the group.

    Follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1): every run is
    a new row with the next `version` of that discovered environment, and a stored row is never
    changed. `discovery_id` is the slug `id` of the environment inside the project's
    `environment_discovery` content. `inputs` records what the plan was built from (the
    stagings of the scenes that use the place, the environment's definition and its pinned
    master picture).
    """

    __tablename__ = "environment_view_plan"
    __table_args__ = (
        CheckConstraint("source IN ('ai', 'manual')", name="source_valid"),
        UniqueConstraint("project_id", "discovery_id", "version"),
        Index("idx_environment_view_plan_project_discovery", "project_id", "discovery_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    discovery_id: Mapped[str]
    version: Mapped[int]
    source: Mapped[str]
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any] = mapped_column(JSON)
    content: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class EnvironmentViewState(Base):
    """The picture of one view of an environment in one named state of it (PHASE-053,
    `Path_ahead.md` Section 46): for example the stove wall at night. It is an edit of the view's
    picture in the condition shown by the state's picture (`reference_image_id`, made by
    `lab_run_id`). `inputs` records what it was made from (`{"project_id", "discovery_id",
    "slug", "resolution_version", "view_image_id", "state_image_id", "environment_version"}`):
    a picture is out of date when either source picture was replaced since.

    Like a state or a view, it belongs to the library environment (through its view): creating
    one adds no version and moves no pin until its picture is stored.
    """

    __tablename__ = "environment_view_state"
    __table_args__ = (UniqueConstraint("view_id", "state_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    view_id: Mapped[int] = mapped_column(ForeignKey("environment_view.id", ondelete="CASCADE"))
    state_id: Mapped[int] = mapped_column(ForeignKey("environment_state.id", ondelete="CASCADE"))
    reference_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_image.id", ondelete="SET NULL"), default=None
    )
    lab_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_run.id", ondelete="SET NULL"), default=None
    )
    inputs: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class ProjectMissingLibraryItem(Base):
    """A library character or environment that a story project used and that was deleted from
    the library (PHASE-055).

    Deleting a library item removes its links and cast rows by cascade, so this record is
    written first, one per project that used the item. It lets the project say "this entry was
    deleted" instead of quietly making a new item for it, and it is what the user acts on
    ("create it again" or "pick another").

    `library_id` is the deleted item's id as a plain number, not a link: the row is gone.
    `discovery_id` is the slug id of the discovered entry that was linked to it; NULL when it
    was only in the project's cast, or once the entry has been linked again. `in_cast` is true
    when the item was in the project's cast: the id is then still counted in the cast hash
    (`services/discovery.current_cast_sha256`), so deleting it does not make the whole
    discovered list out of date. A project has at most one record per deleted item.
    """

    __tablename__ = "project_missing_library_item"
    __table_args__ = (
        CheckConstraint("kind IN ('character', 'environment')", name="kind_valid"),
        UniqueConstraint(
            "project_id", "kind", "library_id", name="uq_project_missing_library_item_library"
        ),
        UniqueConstraint(
            "project_id", "kind", "discovery_id", name="uq_project_missing_library_item_discovery"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    kind: Mapped[str]
    library_id: Mapped[int]
    discovery_id: Mapped[str | None] = mapped_column(default=None)
    name: Mapped[str]
    in_cast: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    deleted_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)


class AvLabTest(Base):
    """One test of the Audio video lab, inside a library character (AVLAB).

    The whole `text` is spoken as one Voice lab speech (`voice_run_id`, `direction` mode with
    `instruction`), Parakeet times its words (`timing_job_id`, `word_timing`), and each part the
    author marked (`parts`: `{"start_word", "end_word"}`, the words counted from 0 in
    `text.split()`, the end included) gets an H3 clip made from its slice of the speech
    (`av_lab_segment`). `audio_marker` says how every clip uses its slice. Two videos are then
    rendered: `mixed_path` (the speech in the gaps, the clip's own sound inside the parts) and
    `tts_path` (the speech only, the clips muted). `copied_from_id` is a note of the test whose
    speech and timings this one reuses; it is not a link.
    """

    __tablename__ = "av_lab_test"
    __table_args__ = (
        CheckConstraint("audio_marker IN ('fully_copy', 'partially_copy')", name="marker_valid"),
        CheckConstraint("orientation IN ('portrait', 'landscape')", name="orientation_valid"),
        Index("idx_av_lab_test_character", "character_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=_CURRENT_TIMESTAMP)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("library_character.id", ondelete="CASCADE")
    )
    text: Mapped[str]
    instruction: Mapped[str]
    audio_marker: Mapped[str]
    orientation: Mapped[str]
    # {source: "lab" | "asset", id}: the first frame of every clip, and the still shown in the gaps.
    first_frame: Mapped[Any] = mapped_column(JSON)
    parts: Mapped[Any] = mapped_column(JSON)
    voice_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_voice_run.id", ondelete="SET NULL"), default=None
    )
    timing_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    # {"source", "match_percent", "threshold", "heard_text", "words": [{text, start, end}]}.
    word_timing: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    render_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), default=None
    )
    mixed_path: Mapped[str | None] = mapped_column(default=None)
    tts_path: Mapped[str | None] = mapped_column(default=None)
    # What the render made: size, frames and lengths of the two files.
    render_info: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), default=None)
    last_error: Mapped[str | None] = mapped_column(default=None)
    copied_from_id: Mapped[int | None] = mapped_column(default=None)


class AvLabSegment(Base):
    """One marked part of an Audio video lab test: the words, where they sit in the speech, the
    slice of the speech made for them (a `lab_voice_run` with a file and no job) and the
    character take that makes the clip from it.

    `start_s` and `end_s` are seconds in the whole speech: the middle of the gap before the first
    word (0 for the first word of the text) and the middle of the gap after the last word (the
    end of the speech for the last word). `clip_frames` is the H3 length (`17n + 5`) of the
    slice, which is the part padded with silence at its end.
    """

    __tablename__ = "av_lab_segment"
    __table_args__ = (
        UniqueConstraint("test_id", "position"),
        Index("idx_av_lab_segment_take", "take_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("av_lab_test.id", ondelete="CASCADE"))
    position: Mapped[int]
    start_word: Mapped[int]
    end_word: Mapped[int]
    text: Mapped[str]
    start_s: Mapped[float]
    end_s: Mapped[float]
    clip_frames: Mapped[int]
    slice_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_voice_run.id", ondelete="SET NULL"), default=None
    )
    take_id: Mapped[int | None] = mapped_column(
        ForeignKey("character_take.id", ondelete="SET NULL"), default=None
    )
