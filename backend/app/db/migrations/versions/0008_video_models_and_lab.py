"""video models and the video lab

Phase 19 (LTX-2.5). Three things change:

- `project.video_model` and `scene.video_model`: which video model makes a clip, `ltx-2.3` or
  `ltx-2.5`. NULL means "inherit" (the scene takes the project's, the project takes the app's
  default setting).
- `job` is rebuilt (SQLite cannot change a CHECK or drop a NOT NULL in place), once: its
  `project_id` may now be NULL (the Video lab belongs to no project) and its `type` CHECK
  gains `lab_video` and `write_lab_video_prompt`. `scene` points at `job` twice
  (`description_job_id`, `image_prompt_job_id`). The migration connection runs with foreign
  keys off (see `env.py`), so rebuilding a table cannot fire an ON DELETE CASCADE or an
  ON DELETE SET NULL.
- `lab_video_run`: one video the Video lab made (the request's parameters, and the file the
  finished job stored). The job holds the status and the exact request.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09 20:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt')"
)
_MODEL_CHECK = "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5')"
_LAB_MODEL_CHECK = "video_model IN ('ltx-2.3', 'ltx-2.5')"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("video_model", sa.Text(), nullable=True))
        batch_op.create_check_constraint(op.f("ck_project_video_model_valid"), _MODEL_CHECK)

    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.add_column(sa.Column("video_model", sa.Text(), nullable=True))
        batch_op.create_check_constraint(op.f("ck_scene_video_model_valid"), _MODEL_CHECK)

    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.alter_column("project_id", existing_type=sa.Integer(), nullable=True)
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)

    op.create_table(
        "lab_video_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("group_key", sa.Text(), nullable=True),
        sa.Column("video_model", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("first_frame", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=True),
        sa.Column("duration_s", sa.REAL(), nullable=True),
        sa.Column("audio", sa.JSON(none_as_null=True), nullable=True),
        sa.CheckConstraint(_LAB_MODEL_CHECK, name=op.f("ck_lab_video_run_video_model_valid")),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f("fk_lab_video_run_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_video_run")),
    )
    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.create_index("idx_lab_video_run_created", ["created_at"], unique=False)
        batch_op.create_index("idx_lab_video_run_group", ["group_key"], unique=False)
        batch_op.create_index("idx_lab_video_run_job", ["job_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Video lab jobs are deleted, because the old `job` would refuse them
    (no project, and a type its CHECK does not know). Their clips and prompts are lost; the
    files stay in `media/lab/`.
    """
    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_video_run_job")
        batch_op.drop_index("idx_lab_video_run_group")
        batch_op.drop_index("idx_lab_video_run_created")
    op.drop_table("lab_video_run")

    op.execute(
        "DELETE FROM job WHERE project_id IS NULL "
        "OR type IN ('lab_video', 'write_lab_video_prompt')"
    )
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
        batch_op.alter_column("project_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_scene_video_model_valid"), type_="check")
        batch_op.drop_column("video_model")

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_project_video_model_valid"), type_="check")
        batch_op.drop_column("video_model")
