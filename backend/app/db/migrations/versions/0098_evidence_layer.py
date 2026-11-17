"""evidence layer

EVD-001 (`Evidence_layer_implementation_phases.md`). This one migration creates every column,
table and job type the evidence layer needs, so the later phases add no migration.

- `project.evidence`: whether a continuous explainer has an evidence layer (EV-2). NOT NULL,
  default 0, so every project that exists reads off.
- `evidence_claim_list`: one version of a project's claims (the owner's marks and GLM's
  proposals, with the owner's keep or drop choices).
- `evidence_round`: one brief written for one claim list version, with its round folder.
- `evidence_import`: one import of one round's results.
- `evidence_item`: one piece of evidence of one import, with the stored files and the checks.
- `evidence_review`: one version of the owner's decisions on one round's items.
- `evidence_clip`: one rendered evidence video (a preview, or the clip of an evidence shot).
- `job`: its `type` CHECK gains `suggest_evidence_claims`, `write_evidence_brief`,
  `import_evidence` and `render_evidence_clip`. `job` is rebuilt (SQLite cannot change a CHECK
  in place), the same way revision 0096 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0098
Revises: 0097
Create Date: 2026-11-16 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0098"
down_revision: str | Sequence[str] | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLAIM_LIST = "evidence_claim_list"
_ROUND = "evidence_round"
_IMPORT = "evidence_import"
_ITEM = "evidence_item"
_REVIEW = "evidence_review"
_CLIP = "evidence_clip"

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
)
_NEW_JOB_TYPES = (
    "suggest_evidence_claims",
    "write_evidence_brief",
    "import_evidence",
    "render_evidence_clip",
)

# The values of §4.5 of the phases document. A column holds NULL when the agent wrote another
# value, so such an item can still be stored and shown with the reason.
_KINDS = "'web', 'pdf'"
_RELATIONS = "'supports', 'partly_supports', 'contradicts', 'context'"
_TIERS = "'primary', 'secondary', 'other'"


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
            sa.Column("evidence", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )

    op.create_table(
        _CLAIM_LIST,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name=op.f(f"ck_{_CLAIM_LIST}_source_valid")
        ),
        _project_fk(_CLAIM_LIST),
        _job_fk(_CLAIM_LIST, "job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_CLAIM_LIST}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_CLAIM_LIST}_project_id")),
    )
    with op.batch_alter_table(_CLAIM_LIST, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_CLAIM_LIST}_project", ["project_id"], unique=False)

    op.create_table(
        _ROUND,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("claim_list_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("folder", sa.Text(), nullable=False),
        sa.Column("brief", sa.JSON(), nullable=False),
        sa.Column("brief_sha256", sa.Text(), nullable=False),
        _created_at(),
        _project_fk(_ROUND),
        _cascade_fk(_ROUND, "claim_list_id", _CLAIM_LIST),
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
        sa.Column("import_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=True),
        sa.Column("relation", sa.Text(), nullable=True),
        sa.Column("source_tier", sa.Text(), nullable=True),
        sa.Column("source", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("what_it_says", sa.Text(), nullable=True),
        sa.Column("agent_notes", sa.Text(), nullable=True),
        sa.Column("capture", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("image_sha256", sa.Text(), nullable=True),
        sa.Column("context_path", sa.Text(), nullable=True),
        sa.Column("context_sha256", sa.Text(), nullable=True),
        sa.Column("text_path", sa.Text(), nullable=True),
        sa.Column("text_sha256", sa.Text(), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.Column("pdf_sha256", sa.Text(), nullable=True),
        sa.Column("usable", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("checks", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("warnings", sa.JSON(none_as_null=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            f"kind IS NULL OR kind IN ({_KINDS})", name=op.f(f"ck_{_ITEM}_kind_valid")
        ),
        sa.CheckConstraint(
            f"relation IS NULL OR relation IN ({_RELATIONS})",
            name=op.f(f"ck_{_ITEM}_relation_valid"),
        ),
        sa.CheckConstraint(
            f"source_tier IS NULL OR source_tier IN ({_TIERS})",
            name=op.f(f"ck_{_ITEM}_source_tier_valid"),
        ),
        _project_fk(_ITEM),
        _cascade_fk(_ITEM, "import_id", _IMPORT),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_ITEM}")),
        sa.UniqueConstraint(
            "import_id", "claim_id", "evidence_id", name=op.f(f"uq_{_ITEM}_import_id")
        ),
    )
    with op.batch_alter_table(_ITEM, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_ITEM}_import", ["import_id"], unique=False)
        batch_op.create_index(f"idx_{_ITEM}_project_key", ["project_id", "item_key"], unique=False)

    op.create_table(
        _REVIEW,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("done", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        _created_at(),
        _project_fk(_REVIEW),
        _cascade_fk(_REVIEW, "round_id", _ROUND),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_REVIEW}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_REVIEW}_project_id")),
    )
    with op.batch_alter_table(_REVIEW, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_REVIEW}_round", ["round_id"], unique=False)

    op.create_table(
        _CLIP,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("scene_id", sa.Text(), nullable=True),
        sa.Column("shot_id", sa.Text(), nullable=True),
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
            "purpose IN ('preview', 'shot')", name=op.f(f"ck_{_CLIP}_purpose_valid")
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
    """Downgrade schema. Every evidence row, and every job row of the four evidence types
    (the old `job.type` CHECK would refuse them), is deleted. Files stored in `media/` and the
    round folders are left where they are.
    """
    with op.batch_alter_table(_CLIP, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_CLIP}_item")
        batch_op.drop_index(f"idx_{_CLIP}_project_scene")
    op.drop_table(_CLIP)

    with op.batch_alter_table(_REVIEW, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_REVIEW}_round")
    op.drop_table(_REVIEW)

    with op.batch_alter_table(_ITEM, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_ITEM}_project_key")
        batch_op.drop_index(f"idx_{_ITEM}_import")
    op.drop_table(_ITEM)

    with op.batch_alter_table(_IMPORT, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_IMPORT}_project")
    op.drop_table(_IMPORT)

    with op.batch_alter_table(_ROUND, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_ROUND}_project")
    op.drop_table(_ROUND)

    with op.batch_alter_table(_CLAIM_LIST, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_CLAIM_LIST}_project")
    op.drop_table(_CLAIM_LIST)

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("evidence")

    new_types = ", ".join(f"'{name}'" for name in _NEW_JOB_TYPES)
    op.execute(f"DELETE FROM job WHERE type IN ({new_types})")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
