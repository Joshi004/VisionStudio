"""ai scene descriptions

Phase 12: a new job type (`draft_descriptions`), the project's instructions for the AI that
writes scene descriptions, and, per scene, the first and last frame descriptions, where they
came from, and the job that wrote them.

`job` is rebuilt first (SQLite cannot change a CHECK in place), while nothing references it.
Only then does `scene` get its foreign key to `job`. The migration connection runs with
foreign keys off (see `env.py`), so rebuilding a table cannot fire an ON DELETE CASCADE.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08 11:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = "type IN ('transcribe', 'plan_scenes', 'generate_clip', 'render_final')"
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'generate_clip', 'render_final')"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("description_instructions", sa.Text(), nullable=True))

    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.add_column(sa.Column("first_frame_description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_frame_description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("frame_descriptions_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("description_job_id", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            op.f("ck_scene_frame_descriptions_source_valid"),
            "frame_descriptions_source IN ('manual', 'ai')",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_scene_description_job_id_job"),
            "job",
            ["description_job_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema. Draft jobs are deleted, because the old CHECK would refuse them."""
    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_scene_description_job_id_job"), type_="foreignkey")
        batch_op.drop_constraint(op.f("ck_scene_frame_descriptions_source_valid"), type_="check")
        batch_op.drop_column("description_job_id")
        batch_op.drop_column("frame_descriptions_source")
        batch_op.drop_column("last_frame_description")
        batch_op.drop_column("first_frame_description")

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("description_instructions")

    op.execute("DELETE FROM job WHERE type = 'draft_descriptions'")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
