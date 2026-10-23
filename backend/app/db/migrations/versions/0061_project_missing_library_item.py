"""project missing library items

PHASE-055. A library character or environment can now be deleted. A project that used it keeps
a record of what was deleted, so the project can show the entry as "deleted from the library"
and the user can create it again or pick another, and the pipeline does not quietly make a new
one.

- `project_missing_library_item`: one row per (project, kind, deleted item): `library_id` (the
  deleted id, a plain number), `discovery_id` (the linked discovered entry, NULL when the item
  was only in the cast or has been linked again), `name`, `in_cast` and `deleted_at`. A row is
  removed with its project.

No existing row is changed, so nothing is backfilled.

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-24 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0061"
down_revision: str | Sequence[str] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "project_missing_library_item"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("discovery_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("in_cast", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "deleted_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('character', 'environment')", name=op.f(f"ck_{_TABLE}_kind_valid")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint(
            "project_id", "kind", "library_id", name="uq_project_missing_library_item_library"
        ),
        sa.UniqueConstraint(
            "project_id", "kind", "discovery_id", name="uq_project_missing_library_item_discovery"
        ),
    )


def downgrade() -> None:
    """Downgrade schema. The records of deleted library items are lost; the entries they
    flagged simply read as unlinked again.
    """
    op.drop_table(_TABLE)
