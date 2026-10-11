"""image lab runs on the GPU server

Qwen-Image-2.1 makes an image in minutes, on the GPU server, so an Image lab run on it cannot be
one synchronous call like the Seedream runs. It is a `lab_image` job, like the Video lab's
`lab_video`. Two things change:

- `job`: its `type` CHECK gains `lab_image`. `job` is rebuilt (SQLite cannot change a CHECK in
  place), the same way revision 0010 did. The migration connection runs with foreign keys off
  (see `env.py`), so rebuilding a table cannot fire an ON DELETE CASCADE or an ON DELETE SET
  NULL.
- `lab_run`: a nullable `job_id` (the job that makes the run, set for a run on the GPU server
  and NULL for a Seedream run), and its `status` CHECK gains `running`.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-11 00:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover', 'lab_image')"
)
_OLD_RUN_STATUS = "status IN ('succeeded', 'failed')"
_NEW_RUN_STATUS = "status IN ('running', 'succeeded', 'failed')"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)

    with op.batch_alter_table("lab_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("job_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_lab_run_job_id_job"), "job", ["job_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.drop_constraint(op.f("ck_lab_run_status_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_lab_run_status_valid"), _NEW_RUN_STATUS)
        batch_op.create_index("idx_lab_run_job", ["job_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. The runs and jobs of the GPU server's image model are deleted, because
    the old tables would refuse them. Their image files stay in `media/lab/`.
    """
    # A run that is still running has no result: it goes with the others. Foreign keys are off
    # here, so the images of those runs are detached by hand (what ON DELETE SET NULL would do)
    # and stay.
    gone = "SELECT id FROM lab_run WHERE job_id IS NOT NULL OR status = 'running'"
    op.execute(f"UPDATE lab_image SET run_id = NULL WHERE run_id IN ({gone})")
    op.execute("DELETE FROM lab_run WHERE job_id IS NOT NULL OR status = 'running'")
    with op.batch_alter_table("lab_run", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_run_job")
        batch_op.drop_constraint(op.f("ck_lab_run_status_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_lab_run_status_valid"), _OLD_RUN_STATUS)
        batch_op.drop_constraint(op.f("fk_lab_run_job_id_job"), type_="foreignkey")
        batch_op.drop_column("job_id")

    op.execute("DELETE FROM job WHERE type = 'lab_image'")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
