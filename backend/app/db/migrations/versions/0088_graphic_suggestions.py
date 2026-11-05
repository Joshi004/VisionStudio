"""graphic suggestions

The owner can mark words of the story as a suggested graphic for a continuous explainer with
graphics on. The cut planner reads them as a soft hint and may decline them.

- `project.graphic_suggestions`: a list of `{id, start, end, text}`, where `start` and `end` are
  character positions in `script_text`. NULL means none.

The downgrade drops the column.

Revision ID: 0088
Revises: 0087
Create Date: 2026-11-05 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0088"
down_revision: str | Sequence[str] | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("graphic_suggestions", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("graphic_suggestions")
