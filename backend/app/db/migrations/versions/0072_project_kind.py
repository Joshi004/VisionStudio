"""project kind

A project now has a `kind`, chosen when it is created and never changed after:

- `story`: a written story turned into a film (what every project did until now).
- `explainer`: a script spoken by one presenter from the Character Lab, on camera in some
  passages and as a voice-over over B-roll in the others (EXPLAINER-002).

Existing projects get `story`, so nothing about them changes.

Revision ID: 0072
Revises: 0071
Create Date: 2026-10-27 13:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0072"
down_revision: str | Sequence[str] | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.Text(), server_default=sa.text("'story'"), nullable=False)
        )
        batch_op.create_check_constraint(
            op.f("ck_project_kind_valid"), "kind IN ('story', 'explainer')"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_project_kind_valid"), type_="check")
        batch_op.drop_column("kind")
