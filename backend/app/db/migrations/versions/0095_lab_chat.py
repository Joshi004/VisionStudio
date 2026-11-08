"""lab chat

The Text lab: a chat with a language model chosen for every message. Two tables and one job type.

- `lab_chat`: one conversation (a title, the model last used, when it was last used).
- `lab_chat_message`: one message of a conversation. A user message holds what was typed. An
  assistant message is filled by the `write_chat_reply` job (`job_id`): the answer so far while it
  streams, then the final text, the finish reason and the token counts.
- `job.type` gains `write_chat_reply`. `job` is rebuilt for the new CHECK (SQLite cannot change a
  CHECK in place), the same way revision 0094 did. No job row is changed.

The downgrade deletes the jobs of the new type, drops the two tables and restores the old CHECK.

Revision ID: 0095
Revises: 0094
Create Date: 2026-11-08 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0095"
down_revision: str | Sequence[str] | None = "0094"
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
)
_NEW_JOB_TYPES = ("write_chat_reply",)


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _NEW_JOB_TYPES)

    op.create_table(
        "lab_chat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_chat")),
    )
    with op.batch_alter_table("lab_chat", schema=None) as batch_op:
        batch_op.create_index("idx_lab_chat_updated", ["updated_at"], unique=False)

    op.create_table(
        "lab_chat_message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("reasoning", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("finish_reason", sa.Text(), nullable=True),
        sa.Column("usage", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("history_dropped", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name=op.f("ck_lab_chat_message_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["lab_chat.id"],
            name=op.f("fk_lab_chat_message_chat_id_lab_chat"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f("fk_lab_chat_message_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_chat_message")),
    )
    with op.batch_alter_table("lab_chat_message", schema=None) as batch_op:
        batch_op.create_index("idx_lab_chat_message_chat", ["chat_id", "id"], unique=False)
        batch_op.create_index("idx_lab_chat_message_job", ["job_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. The jobs of the new type are deleted (the old CHECK would refuse them)."""
    with op.batch_alter_table("lab_chat_message", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_chat_message_job")
        batch_op.drop_index("idx_lab_chat_message_chat")
    op.drop_table("lab_chat_message")
    with op.batch_alter_table("lab_chat", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_chat_updated")
    op.drop_table("lab_chat")

    new_types = ", ".join(f"'{name}'" for name in _NEW_JOB_TYPES)
    op.execute(f"DELETE FROM job WHERE type IN ({new_types})")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
