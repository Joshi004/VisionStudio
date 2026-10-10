"""saved voices, the voice lab, and a last frame in the video lab

Phase 21 (Breeze TTS and LTX-2.5 interpolate). Four things change:

- `job`: its `type` CHECK gains `lab_voice` and `generate_voiceover`. `job` is rebuilt
  (SQLite cannot change a CHECK in place), the same way revision 0009 did. The migration
  connection runs with foreign keys off (see `env.py`), so rebuilding a table cannot fire an
  ON DELETE CASCADE or an ON DELETE SET NULL.
- `voice`: a saved voice (a recording and its exact transcript).
- `lab_voice_run`: one speech the Voice lab made.
- `project.voice_id`: the saved voice that speaks the script of a project whose voiceover the
  app makes. `lab_video_run.last_frame`: the image a Video lab clip ends on.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-10 01:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover')"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)

    op.create_table(
        "voice",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("duration_s", sa.REAL(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("lab_voice_run_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("origin IN ('upload', 'lab_run')", name=op.f("ck_voice_origin_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice")),
    )
    with op.batch_alter_table("voice", schema=None) as batch_op:
        batch_op.create_index("idx_voice_created", ["created_at"], unique=False)

    op.create_table(
        "lab_voice_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=True),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("duration_s", sa.REAL(), nullable=True),
        sa.CheckConstraint(
            "mode IN ('design', 'clone', 'direction')", name=op.f("ck_lab_voice_run_mode_valid")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f("fk_lab_voice_run_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f("fk_lab_voice_run_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_voice_run")),
    )
    with op.batch_alter_table("lab_voice_run", schema=None) as batch_op:
        batch_op.create_index("idx_lab_voice_run_created", ["created_at"], unique=False)
        batch_op.create_index("idx_lab_voice_run_job", ["job_id"], unique=False)

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("voice_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_project_voice_id_voice"), "voice", ["voice_id"], ["id"], ondelete="SET NULL"
        )

    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_frame", sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema. Voice lab and voiceover jobs are deleted, because the old `job` would
    refuse them. Voiceovers the app made stay as ordinary voiceover assets of their projects.
    Files stay in `media/`.
    """
    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.drop_column("last_frame")

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("fk_project_voice_id_voice"), type_="foreignkey")
        batch_op.drop_column("voice_id")

    with op.batch_alter_table("lab_voice_run", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_voice_run_job")
        batch_op.drop_index("idx_lab_voice_run_created")
    op.drop_table("lab_voice_run")

    with op.batch_alter_table("voice", schema=None) as batch_op:
        batch_op.drop_index("idx_voice_created")
    op.drop_table("voice")

    op.execute("DELETE FROM job WHERE type IN ('lab_voice', 'generate_voiceover')")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
