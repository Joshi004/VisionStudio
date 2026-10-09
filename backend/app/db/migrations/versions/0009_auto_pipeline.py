"""the automatic video pipeline job type

The `auto_pipeline` job is one run of the automatic flow of a project: it creates the jobs of
the manual steps one step at a time, and moves on only when every scene has finished the
step. It keeps its state in `job.input` and `job.output`, so no table or column is added.
Only the `job.type` CHECK gains the new value.

`job` is rebuilt (SQLite cannot change a CHECK in place), the same way revision 0008 did. The
migration connection runs with foreign keys off (see `env.py`), so rebuilding a table cannot
fire an ON DELETE CASCADE or an ON DELETE SET NULL.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09 22:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline')"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)


def downgrade() -> None:
    """Downgrade schema. Automatic runs are deleted, because the old `job` would refuse them.
    The jobs they created stay: they are ordinary jobs of the manual steps.
    """
    op.execute("DELETE FROM job WHERE type = 'auto_pipeline'")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
