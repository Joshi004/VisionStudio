"""a character look can start from the author's own picture

`character_look.reference_image_id`: the lab image (an upload) a look was started from. Its
candidates are then edits of that picture instead of text-to-image pictures. NULL for every
look made from the profile alone, which is every look that exists before this revision.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-14 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REFERENCE_FK = "fk_character_look_reference_image_id_lab_image"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("character_look", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reference_image_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_REFERENCE_FK),
            "lab_image",
            ["reference_image_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema. Looks keep their pictures; only the link to the picture they were
    started from is lost.
    """
    with op.batch_alter_table("character_look", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_REFERENCE_FK), type_="foreignkey")
        batch_op.drop_column("reference_image_id")
