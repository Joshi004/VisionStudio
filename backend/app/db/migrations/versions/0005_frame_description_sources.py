"""one source for each frame description

Phase 15: the AI no longer writes a last-frame description, so the two frame descriptions
no longer share a source. `scene.frame_descriptions_source` (one value for the pair) is
replaced by `first_frame_description_source` and `last_frame_description_source`.

Each new source is copied from the old one where its own text is not blank, so no text
changes hands: an AI-written text stays the AI's, and the author's stays the author's.

The upgrade is two batches. The first adds the new columns, then the old values are copied,
and only then does the second batch drop the old column with its CHECK (SQLite cannot drop
either in place, so each batch rebuilds `scene`). The migration connection runs with foreign
keys off (see `env.py`), so rebuilding the table cannot fire an ON DELETE CASCADE.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CHECK = "ck_scene_frame_descriptions_source_valid"
_FIRST_CHECK = "ck_scene_first_frame_description_source_valid"
_LAST_CHECK = "ck_scene_last_frame_description_source_valid"
_SOURCES = "('manual', 'ai')"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.add_column(sa.Column("first_frame_description_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_frame_description_source", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            op.f(_FIRST_CHECK), f"first_frame_description_source IN {_SOURCES}"
        )
        batch_op.create_check_constraint(
            op.f(_LAST_CHECK), f"last_frame_description_source IN {_SOURCES}"
        )

    # Each text keeps the source it had, but only a text that exists has a source.
    op.execute(
        "UPDATE scene SET first_frame_description_source = frame_descriptions_source "
        "WHERE trim(coalesce(first_frame_description, '')) <> ''"
    )
    op.execute(
        "UPDATE scene SET last_frame_description_source = frame_descriptions_source "
        "WHERE trim(coalesce(last_frame_description, '')) <> ''"
    )

    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_OLD_CHECK), type_="check")
        batch_op.drop_column("frame_descriptions_source")


def downgrade() -> None:
    """Downgrade schema. The pair's source is the author's if either text is, else the AI's."""
    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.add_column(sa.Column("frame_descriptions_source", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            op.f(_OLD_CHECK), f"frame_descriptions_source IN {_SOURCES}"
        )

    op.execute(
        "UPDATE scene SET frame_descriptions_source = CASE "
        "WHEN first_frame_description_source = 'manual' "
        "OR last_frame_description_source = 'manual' THEN 'manual' "
        "WHEN first_frame_description_source = 'ai' "
        "OR last_frame_description_source = 'ai' THEN 'ai' "
        "ELSE NULL END"
    )

    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_LAST_CHECK), type_="check")
        batch_op.drop_constraint(op.f(_FIRST_CHECK), type_="check")
        batch_op.drop_column("last_frame_description_source")
        batch_op.drop_column("first_frame_description_source")
