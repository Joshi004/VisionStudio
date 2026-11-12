"""youtube publishing tables

Publishing a finished render to the owner's YouTube channels (YouTube_publish_phases.md, YT-002).
Three tables and two job types, so the later phases add no migration.

- `youtube_channel`: one connected channel. The refresh token is stored encrypted
  (`token_encrypted`, a Fernet token); `status` is `connected` or `needs_reconnect`.
- `youtube_draft`: one version of a project's publish draft (the provenance convention).
- `youtube_upload`: one press of Upload, with a snapshot of exactly what was sent (`sent`) and the
  results the upload job fills in. `channel_row_id` is `ON DELETE SET NULL`, so an upload stays
  readable after its channel is disconnected.
- `job.type` gains `write_youtube_draft` and `publish_youtube`. `job` is rebuilt for the new CHECK
  (SQLite cannot change a CHECK in place), the same way revision 0095 did. No job row is changed.

The downgrade deletes the jobs of the new types, drops the three tables and restores the old CHECK.

Revision ID: 0096
Revises: 0095
Create Date: 2026-11-12 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0096"
down_revision: str | Sequence[str] | None = "0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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
)
_NEW_JOB_TYPES = ("write_youtube_draft", "publish_youtube")


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


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _NEW_JOB_TYPES)

    op.create_table(
        "youtube_channel",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'connected'"), nullable=False),
        sa.Column(
            "connected_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_used_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('connected', 'needs_reconnect')",
            name=op.f("ck_youtube_channel_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_youtube_channel")),
        sa.UniqueConstraint("channel_id", name=op.f("uq_youtube_channel_channel_id")),
    )

    op.create_table(
        "youtube_draft",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("render_id", sa.Integer(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name=op.f("ck_youtube_draft_source_valid")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_youtube_draft_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f("fk_youtube_draft_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["render_id"],
            ["story_render.id"],
            name=op.f("fk_youtube_draft_render_id_story_render"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_youtube_draft")),
        sa.UniqueConstraint("project_id", "version", name=op.f("uq_youtube_draft_project_id")),
    )
    with op.batch_alter_table("youtube_draft", schema=None) as batch_op:
        batch_op.create_index("idx_youtube_draft_project", ["project_id"], unique=False)

    op.create_table(
        "youtube_upload",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("render_id", sa.Integer(), nullable=False),
        sa.Column("channel_row_id", sa.Integer(), nullable=True),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("sent", sa.JSON(), nullable=False),
        sa.Column("video_id", sa.Text(), nullable=True),
        sa.Column("privacy_applied", sa.Text(), nullable=True),
        sa.Column("processing", sa.Text(), nullable=True),
        sa.Column("thumbnail_result", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("captions_result", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _created_at(),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "privacy_applied IS NULL OR privacy_applied IN ('private', 'unlisted', 'public')",
            name=op.f("ck_youtube_upload_privacy_applied_valid"),
        ),
        sa.CheckConstraint(
            "processing IS NULL OR processing IN ('waiting', 'processed', 'failed', 'gave_up')",
            name=op.f("ck_youtube_upload_processing_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_youtube_upload_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["render_id"],
            ["story_render.id"],
            name=op.f("fk_youtube_upload_render_id_story_render"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["channel_row_id"],
            ["youtube_channel.id"],
            name=op.f("fk_youtube_upload_channel_row_id_youtube_channel"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f("fk_youtube_upload_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_youtube_upload")),
    )
    with op.batch_alter_table("youtube_upload", schema=None) as batch_op:
        batch_op.create_index("idx_youtube_upload_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. The jobs of the new types are deleted (the old CHECK would refuse them)."""
    with op.batch_alter_table("youtube_upload", schema=None) as batch_op:
        batch_op.drop_index("idx_youtube_upload_project")
    op.drop_table("youtube_upload")
    with op.batch_alter_table("youtube_draft", schema=None) as batch_op:
        batch_op.drop_index("idx_youtube_draft_project")
    op.drop_table("youtube_draft")
    op.drop_table("youtube_channel")

    new_types = ", ".join(f"'{name}'" for name in _NEW_JOB_TYPES)
    op.execute(f"DELETE FROM job WHERE type IN ({new_types})")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
