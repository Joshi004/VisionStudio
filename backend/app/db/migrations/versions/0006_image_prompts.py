"""image prompts

Phase 16: a new job type (`write_image_prompt`) and, per scene, the detailed image prompt for
its first frame, who wrote it, and the job that wrote it.

`job` is rebuilt first (SQLite cannot change a CHECK in place). `scene` already points at
`job` (`description_job_id`), so this is the first rebuild of `job` with a reference to it in
place. The migration connection runs with foreign keys off (see `env.py`), so rebuilding a
table cannot fire an ON DELETE CASCADE or an ON DELETE SET NULL. Then `scene` gets its three
columns, their CHECK and the foreign key to `job`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'generate_clip', 'render_final')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_clip', 'render_final')"
)
_SOURCE_CHECK = "ck_scene_image_prompt_source_valid"
_JOB_FK = "fk_scene_image_prompt_job_id_job"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)

    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_prompt", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("image_prompt_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("image_prompt_job_id", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            op.f(_SOURCE_CHECK), "image_prompt_source IN ('manual', 'ai')"
        )
        batch_op.create_foreign_key(
            batch_op.f(_JOB_FK),
            "job",
            ["image_prompt_job_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema. Image prompt jobs are deleted, because the old CHECK would refuse them."""
    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_JOB_FK), type_="foreignkey")
        batch_op.drop_constraint(op.f(_SOURCE_CHECK), type_="check")
        batch_op.drop_column("image_prompt_job_id")
        batch_op.drop_column("image_prompt_source")
        batch_op.drop_column("image_prompt")

    op.execute("DELETE FROM job WHERE type = 'write_image_prompt'")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
