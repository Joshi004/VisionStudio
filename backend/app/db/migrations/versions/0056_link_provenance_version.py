"""link provenance version

When a project adopts a version of a library character or environment that a person made in the
lab (PHASE-042), that version has no provenance (`inputs`). The link keeps the number of the
version whose `inputs` still stand for the project's own definition, so the definition stage
keeps reading the definition as built from the project's story. NULL means the pinned version's
own `inputs` are used. Existing links get NULL, so nothing about them changes.

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-23 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0056"
down_revision: str | Sequence[str] | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project_character_link", schema=None) as batch_op:
        batch_op.add_column(sa.Column("provenance_version", sa.Integer(), nullable=True))
    with op.batch_alter_table("project_environment_link", schema=None) as batch_op:
        batch_op.add_column(sa.Column("provenance_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project_environment_link", schema=None) as batch_op:
        batch_op.drop_column("provenance_version")
    with op.batch_alter_table("project_character_link", schema=None) as batch_op:
        batch_op.drop_column("provenance_version")
