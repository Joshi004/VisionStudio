"""youtube draft may be written before its render exists

A draft started when Render is pressed (YouTube_publish_followups_phases.md, YTF-004) is
written while the video renders, so there is no `story_render` row to point at yet.
`youtube_draft.render_id` becomes nullable: such a draft stores NULL there and the render job's
id in `inputs.render_job_id` (JSON, so no other column changes). A draft is for render R when
`render_id` is R's id or `inputs.render_job_id` is R's `job_id`.

The downgrade refuses to run while a row has a NULL `render_id`, so no draft is deleted silently.

Revision ID: 0097
Revises: 0096
Create Date: 2026-11-12 20:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0097"
down_revision: str | Sequence[str] | None = "0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("youtube_draft", schema=None) as batch_op:
        batch_op.alter_column("render_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    connection = op.get_bind()
    pending = connection.execute(
        sa.text("SELECT COUNT(*) FROM youtube_draft WHERE render_id IS NULL")
    ).scalar_one()
    if pending:
        raise RuntimeError(
            f"{pending} YouTube draft(s) were written before their render existed "
            "(render_id is NULL). Delete them yourself first, then downgrade again."
        )
    with op.batch_alter_table("youtube_draft", schema=None) as batch_op:
        batch_op.alter_column("render_id", existing_type=sa.Integer(), nullable=False)
