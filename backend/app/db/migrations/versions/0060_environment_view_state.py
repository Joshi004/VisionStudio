"""environment view states

PHASE-053. Every view of an environment also gets a picture in each named state the scenes need
(the stove wall at night), made by editing the view's picture into the condition the state's
picture shows.

- `environment_view_state`: one row per (view, state): `reference_image_id` (the picture, NULL
  until it is made), `lab_run_id` (the edit run that makes it) and `inputs` (what it was made
  from). `UNIQUE (view_id, state_id)`; a row is removed with its view or its state.

No job type is added and no existing row is changed, so nothing is backfilled.

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-24 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0060"
down_revision: str | Sequence[str] | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "environment_view_state"


def _fk(column: str, target: str) -> sa.ForeignKeyConstraint:
    ondelete = "CASCADE" if column in ("view_id", "state_id") else "SET NULL"
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{_TABLE}_{column}_{target}"),
        ondelete=ondelete,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("view_id", sa.Integer(), nullable=False),
        sa.Column("state_id", sa.Integer(), nullable=False),
        sa.Column("reference_image_id", sa.Integer(), nullable=True),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        _fk("view_id", "environment_view"),
        _fk("state_id", "environment_state"),
        _fk("reference_image_id", "lab_image"),
        _fk("lab_run_id", "lab_run"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint("view_id", "state_id", name=op.f(f"uq_{_TABLE}_view_id")),
    )


def downgrade() -> None:
    """Downgrade schema. The pictures stay in the lab's pictures and only lose their link to the
    view and state they were made for.
    """
    op.drop_table(_TABLE)
