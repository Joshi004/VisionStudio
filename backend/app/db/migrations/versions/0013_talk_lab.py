"""the Talking character lab: lip-synced clips, a cast of characters and takes

Phase 24. Four things change:

- `job`: its `type` CHECK gains `write_talk_prompts` (a paid call to the language model that
  writes the voice instruction and the video prompt of a take). `job` is rebuilt (SQLite cannot
  change a CHECK in place), the same way revision 0012 did. The migration connection runs with
  foreign keys off (see `env.py`), so rebuilding a table cannot fire an ON DELETE CASCADE or an
  ON DELETE SET NULL.
- `lab_video_run.audio_input`: the speech a lip-synced clip (audio-to-video) was made to
  match, as `{source: "voice_run" | "voice", id}`. NULL for every other clip.
- `lab_character`: a character of the cast (name, picture, description, default voice).
- `lab_talk_run`: one take (dialogue, picture, prompts, and the three steps it is made in).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-11 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover', 'lab_image', "
    "'write_last_frame_prompt', 'generate_last_frame')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover', 'lab_image', "
    "'write_last_frame_prompt', 'generate_last_frame', 'write_talk_prompts')"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)

    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("audio_input", sa.JSON(none_as_null=True), nullable=True))

    op.create_table(
        "lab_character",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("image", sa.JSON(), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("voice_instruction", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f("fk_lab_character_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_character")),
    )
    with op.batch_alter_table("lab_character", schema=None) as batch_op:
        batch_op.create_index("idx_lab_character_created", ["created_at"], unique=False)

    op.create_table(
        "lab_talk_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("dialogue", sa.Text(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=True),
        sa.Column("image", sa.JSON(), nullable=False),
        sa.Column("character_note", sa.Text(), nullable=True),
        sa.Column("delivery_note", sa.Text(), nullable=True),
        sa.Column("voice_mode", sa.Text(), nullable=True),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("voice_instruction", sa.Text(), nullable=True),
        sa.Column("video_prompt", sa.Text(), nullable=True),
        sa.Column("orientation", sa.Text(), nullable=False),
        sa.Column("video_seed", sa.Integer(), nullable=True),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("auto_continue", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("voice_run_id", sa.Integer(), nullable=True),
        sa.Column("video_run_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "voice_mode IS NULL OR voice_mode IN ('design', 'clone', 'direction')",
            name=op.f("ck_lab_talk_run_voice_mode_valid"),
        ),
        sa.CheckConstraint(
            "orientation IN ('portrait', 'landscape')",
            name=op.f("ck_lab_talk_run_orientation_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["lab_character.id"],
            name=op.f("fk_lab_talk_run_character_id_lab_character"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f("fk_lab_talk_run_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f("fk_lab_talk_run_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["voice_run_id"],
            ["lab_voice_run.id"],
            name=op.f("fk_lab_talk_run_voice_run_id_lab_voice_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["video_run_id"],
            ["lab_video_run.id"],
            name=op.f("fk_lab_talk_run_video_run_id_lab_video_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_talk_run")),
    )
    with op.batch_alter_table("lab_talk_run", schema=None) as batch_op:
        batch_op.create_index("idx_lab_talk_run_created", ["created_at"], unique=False)
        batch_op.create_index("idx_lab_talk_run_voice_run", ["voice_run_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Takes and the cast are dropped. Talking character prompt jobs are
    deleted, because the old CHECK would refuse them. The speeches and clips they made stay as
    ordinary Voice lab and Video lab runs, and files stay in `media/`.
    """
    with op.batch_alter_table("lab_talk_run", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_talk_run_voice_run")
        batch_op.drop_index("idx_lab_talk_run_created")
    op.drop_table("lab_talk_run")

    with op.batch_alter_table("lab_character", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_character_created")
    op.drop_table("lab_character")

    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.drop_column("audio_input")

    op.execute("DELETE FROM job WHERE type = 'write_talk_prompts'")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
