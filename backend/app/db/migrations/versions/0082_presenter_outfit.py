"""presenter outfit

An explainer may carry the owner's text for what the presenter wears (for example "a navy suit
and a white shirt").

- `project.presenter_outfit`: at most 300 characters, only for an explainer. NULL means the
  presenter wears their default outfit from the Character Lab. It can be changed at any time.

No data needs preserving, so nothing is backfilled.

Revision ID: 0082
Revises: 0081
Create Date: 2026-11-04 12:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0082"
down_revision: str | Sequence[str] | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("presenter_outfit", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("presenter_outfit")
