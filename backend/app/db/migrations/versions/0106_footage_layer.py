"""footage layer

FTG-001 (`Footage_broll_implementation_phases.md`). This one migration creates every column,
table and job type footage needs, so the later footage phases add no migration.

- `project.footage`: whether a continuous explainer has footage (FT-3). NOT NULL, default 0, so
  every project that exists reads off.
- `footage_mark_list`: one version of a project's footage marks (the owner's marks and GLM's
  proposals, with the owner's keep or drop choices).
- `footage_round`: one brief written for one mark list version, with its round folder.
- `footage_import`: one import of one round's results.
- `footage_item`: one piece of footage, from an import (`origin` `agent`) or added by the owner
  (`origin` `owner`, no import), with the stored files and the checks.
- `footage_decision`: one version of the owner's decisions for the whole project.
- `footage_clip`: one rendered footage video (a preview, or a placed piece at its exact length).
- `job`: its `type` CHECK gains `suggest_footage_marks`, `write_footage_brief`, `import_footage`,
  `prepare_footage_file` and `render_footage_clip`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0104 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0106
Revises: 0105
Create Date: 2026-11-28 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0106"
down_revision: str | Sequence[str] | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MARK_LIST = "footage_mark_list"
_ROUND = "footage_round"
_IMPORT = "footage_import"
_ITEM = "footage_item"
_DECISION = "footage_decision"
_CLIP = "footage_clip"

_EARLIER_JOB_TYPES = (
    "lab_image",
    "lab_video",
    "write_lab_video_prompt",
    "lab_voice",
    "write_character_look_prompt",
    "write_character_take_prompt",
    "write_story_bible",
    "discover_characters",
    "discover_environments",
    "discover_scenes",
    "define_character",
    "discover_relations",
    "design_voice",
    "write_environment_prompt",
    "define_environment",
    "define_scene",
    "extract_events",
    "resolve_looks_states",
    "synthesize_speech_unit",
    "plan_shots",
    "define_shot",
    "check_shot_continuity",
    "repair_shot_cut",
    "compile_shot_prompt",
    "generate_shot",
    "render_story",
    "check_shot_takes",
    "story_pipeline",
    "check_take_dialogue",
    "select_shot_references",
    "lab_music",
    "write_lab_music_prompt",
    "stage_scene",
    "plan_environment_views",
    "write_environment_view_prompt",
    "write_music_bible",
    "write_music_theme_prompt",
    "write_music_plan",
    "write_music_cue",
    "audit_music_cues",
    "rewrite_music_prompt",
    "place_music",
    "preview_music_mix",
    "time_speech_words",
    "write_callout_plan",
    "time_lab_speech_words",
    "render_av_test",
    "write_lab_graphic_brief",
    "write_lab_graphic_template_spec",
    "write_lab_graphic_block_scene",
    "write_lab_graphic_component",
    "render_lab_graphic",
    "time_lab_graphic_words",
    "write_graphic_theme",
    "write_shot_graphic_brief",
    "write_shot_graphic_component",
    "write_shot_graphic_scene",
    "render_shot_graphic",
    "describe_photo",
    "render_scene",
    "write_thumbnail_concepts",
    "write_callout_look",
    "write_callout_component",
    "render_callout_preview",
    "write_callout_scene",
    "time_voice_recording",
    "split_voice_recording",
    "splice_voice_recording",
    "write_chat_reply",
    "write_youtube_draft",
    "publish_youtube",
    "suggest_evidence_claims",
    "write_evidence_brief",
    "import_evidence",
    "render_evidence_clip",
    "transcribe_evidence_clip",
    "write_sound_effect",
)
_NEW_JOB_TYPES = (
    "suggest_footage_marks",
    "write_footage_brief",
    "import_footage",
    "prepare_footage_file",
    "render_footage_clip",
)

# The values of §4.6 of the phases document. A column holds NULL when the agent wrote another
# value, so such an item can still be stored and shown with the reason.
_KINDS = "'video', 'image', 'page', 'pdf'"
_TIERS = "'official', 'press', 'commons', 'news', 'creator', 'other'"
_SAME_EVENTS = "'yes', 'no', 'unknown'"
_ON_SCREEN_TEXTS = "'none', 'small', 'large'"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        UTCDateTime(),
        server_default=sa.text("(CURRENT_TIMESTAMP)"),
        nullable=False,
    )


def _project_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["project_id"],
        ["project.id"],
        name=op.f(f"fk_{table}_project_id_project"),
        ondelete="CASCADE",
    )


def _job_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        ["job.id"],
        name=op.f(f"fk_{table}_{column}_job"),
        ondelete="SET NULL",
    )


def _cascade_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete="CASCADE",
    )


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _NEW_JOB_TYPES)

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("footage", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )

    op.create_table(
        _MARK_LIST,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name=op.f(f"ck_{_MARK_LIST}_source_valid")
        ),
        _project_fk(_MARK_LIST),
        _job_fk(_MARK_LIST, "job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_MARK_LIST}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_MARK_LIST}_project_id")),
    )
    with op.batch_alter_table(_MARK_LIST, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_MARK_LIST}_project", ["project_id"], unique=False)

    op.create_table(
        _ROUND,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("mark_list_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("folder", sa.Text(), nullable=False),
        sa.Column("brief", sa.JSON(), nullable=False),
        sa.Column("brief_sha256", sa.Text(), nullable=False),
        _created_at(),
        _project_fk(_ROUND),
        _cascade_fk(_ROUND, "mark_list_id", _MARK_LIST),
        _job_fk(_ROUND, "job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_ROUND}")),
        sa.UniqueConstraint("project_id", "round_no", name=op.f(f"uq_{_ROUND}_project_id")),
    )
    with op.batch_alter_table(_ROUND, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_ROUND}_project", ["project_id"], unique=False)

    op.create_table(
        _IMPORT,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        _created_at(),
        _project_fk(_IMPORT),
        _cascade_fk(_IMPORT, "round_id", _ROUND),
        _job_fk(_IMPORT, "job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_IMPORT}")),
        sa.UniqueConstraint("round_id", "version", name=op.f(f"uq_{_IMPORT}_round_id")),
    )
    with op.batch_alter_table(_IMPORT, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_IMPORT}_project", ["project_id"], unique=False)

    op.create_table(
        _ITEM,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=True),
        sa.Column("mark_id", sa.Text(), nullable=False),
        sa.Column("piece_id", sa.Text(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=True),
        sa.Column("tier", sa.Text(), nullable=True),
        sa.Column("source", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("what_it_shows", sa.Text(), nullable=True),
        sa.Column("same_event", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Text(), nullable=True),
        sa.Column("on_screen_text", sa.Text(), nullable=True),
        sa.Column("credit", sa.Text(), nullable=True),
        sa.Column("agent_notes", sa.Text(), nullable=True),
        sa.Column("capture", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("video_path", sa.Text(), nullable=True),
        sa.Column("video_sha256", sa.Text(), nullable=True),
        sa.Column("strip_path", sa.Text(), nullable=True),
        sa.Column("strip_sha256", sa.Text(), nullable=True),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("image_sha256", sa.Text(), nullable=True),
        sa.Column("text_path", sa.Text(), nullable=True),
        sa.Column("text_sha256", sa.Text(), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column("pdf_sha256", sa.Text(), nullable=True),
        sa.Column("upload_path", sa.Text(), nullable=True),
        sa.Column("upload_sha256", sa.Text(), nullable=True),
        sa.Column("cuts", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("prepare_job_id", sa.Integer(), nullable=True),
        sa.Column("usable", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("checks", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("warnings", sa.JSON(none_as_null=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("origin IN ('agent', 'owner')", name=op.f(f"ck_{_ITEM}_origin_valid")),
        sa.CheckConstraint(
            "(origin = 'agent' AND import_id IS NOT NULL) "
            "OR (origin = 'owner' AND import_id IS NULL)",
            name=op.f(f"ck_{_ITEM}_import_matches_origin"),
        ),
        sa.CheckConstraint(
            f"kind IS NULL OR kind IN ({_KINDS})", name=op.f(f"ck_{_ITEM}_kind_valid")
        ),
        sa.CheckConstraint(
            f"tier IS NULL OR tier IN ({_TIERS})", name=op.f(f"ck_{_ITEM}_tier_valid")
        ),
        sa.CheckConstraint(
            f"same_event IS NULL OR same_event IN ({_SAME_EVENTS})",
            name=op.f(f"ck_{_ITEM}_same_event_valid"),
        ),
        sa.CheckConstraint(
            f"on_screen_text IS NULL OR on_screen_text IN ({_ON_SCREEN_TEXTS})",
            name=op.f(f"ck_{_ITEM}_on_screen_text_valid"),
        ),
        _project_fk(_ITEM),
        _cascade_fk(_ITEM, "import_id", _IMPORT),
        _job_fk(_ITEM, "prepare_job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_ITEM}")),
        sa.UniqueConstraint("import_id", "mark_id", "piece_id", name=op.f(f"uq_{_ITEM}_import_id")),
    )
    with op.batch_alter_table(_ITEM, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_ITEM}_import", ["import_id"], unique=False)
        batch_op.create_index(f"idx_{_ITEM}_project_key", ["project_id", "item_key"], unique=False)
        batch_op.create_index(f"idx_{_ITEM}_project_mark", ["project_id", "mark_id"], unique=False)

    op.create_table(
        _DECISION,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        _created_at(),
        _project_fk(_DECISION),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_DECISION}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_DECISION}_project_id")),
    )

    op.create_table(
        _CLIP,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=True),
        sa.Column("placed_key", sa.Text(), nullable=True),
        sa.Column("shot_plan_id", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("render_job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("media_path", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=True),
        sa.Column("metrics", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("warnings", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "purpose IN ('preview', 'piece')", name=op.f(f"ck_{_CLIP}_purpose_valid")
        ),
        _project_fk(_CLIP),
        _cascade_fk(_CLIP, "item_id", _ITEM),
        sa.ForeignKeyConstraint(
            ["shot_plan_id"],
            ["shot_plan.id"],
            name=op.f(f"fk_{_CLIP}_shot_plan_id_shot_plan"),
            ondelete="SET NULL",
        ),
        _job_fk(_CLIP, "render_job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_CLIP}")),
    )
    with op.batch_alter_table(_CLIP, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_CLIP}_project_scene", ["project_id", "scene_id"])
        batch_op.create_index(f"idx_{_CLIP}_item", ["item_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every footage row, and every job row of the five footage types (the old
    `job.type` CHECK would refuse them), is deleted. Files stored in `media/` and the round
    folders are left where they are.
    """
    with op.batch_alter_table(_CLIP, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_CLIP}_item")
        batch_op.drop_index(f"idx_{_CLIP}_project_scene")
    op.drop_table(_CLIP)

    op.drop_table(_DECISION)

    with op.batch_alter_table(_ITEM, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_ITEM}_project_mark")
        batch_op.drop_index(f"idx_{_ITEM}_project_key")
        batch_op.drop_index(f"idx_{_ITEM}_import")
    op.drop_table(_ITEM)

    with op.batch_alter_table(_IMPORT, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_IMPORT}_project")
    op.drop_table(_IMPORT)

    with op.batch_alter_table(_ROUND, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_ROUND}_project")
    op.drop_table(_ROUND)

    with op.batch_alter_table(_MARK_LIST, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_MARK_LIST}_project")
    op.drop_table(_MARK_LIST)

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("footage")

    new_types = ", ".join(f"'{name}'" for name in _NEW_JOB_TYPES)
    op.execute(f"DELETE FROM job WHERE type IN ({new_types})")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
