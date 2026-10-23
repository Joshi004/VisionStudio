"""project review points

A project keeps the review points it has enabled (PHASE-041): a JSON list of keys such as
`["shot_plans"]`. A run of the story pipeline stops at each of them and waits for the user.
Existing projects get an empty list, so nothing about them changes.

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-22 23:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0055"
down_revision: str | Sequence[str] | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("review_points", sa.JSON(), server_default=sa.text("'[]'"), nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("review_points")
