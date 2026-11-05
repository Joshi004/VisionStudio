"""presenter staging

An explainer may carry the owner's text for how the presenter is placed and moves on camera
(for example "seated at a desk, still").

- `project.presenter_staging`: at most 500 characters, only for an explainer. NULL means the
  presenter stands. It can be changed at any time.

No data needs preserving, so nothing is backfilled.

Revision ID: 0081
Revises: 0080
Create Date: 2026-11-04 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0081"
down_revision: str | Sequence[str] | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("presenter_staging", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("presenter_staging")
