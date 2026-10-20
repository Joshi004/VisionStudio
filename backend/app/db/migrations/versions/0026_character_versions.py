"""character versions

PHASE-007. Every production-relevant change of a library character is kept as an immutable
version, so a project can later pin one.

- `library_character_version`: one row per version of a character, never changed once written.
  It holds the character's `profile` (the twelve profile fields), its voice (`voice_id` and
  `voice_description`) and its current look: `look_id` plus `look_references`, the exact picture
  of every angle at that moment (so redoing an angle later cannot change an old version).
  `source` follows the provenance convention (DATABASE_STRUCTURE.md Section 2.1) and is
  `manual` for every change made in the lab. A character's versions are numbered from 1
  (`UNIQUE (character_id, version)`).
- `character_take`: gains a nullable `character_version`, the number of the character's newest
  version when the take was made.

No data needs preserving, so nothing is backfilled: a character made before this revision has
no version until its next change, which writes version 1.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-20 19:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "library_character_version"
_INDEX = "idx_library_character_version_character"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("voice_description", sa.Text(), nullable=True),
        sa.Column("look_id", sa.Integer(), nullable=True),
        sa.Column("look_references", sa.JSON(), nullable=False),
        sa.CheckConstraint("source IN ('ai', 'manual')", name=op.f(f"ck_{_TABLE}_source_valid")),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["library_character.id"],
            name=op.f(f"fk_{_TABLE}_character_id_library_character"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f(f"fk_{_TABLE}_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["look_id"],
            ["character_look.id"],
            name=op.f(f"fk_{_TABLE}_look_id_character_look"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint("character_id", "version", name=op.f(f"uq_{_TABLE}_character_id")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(_INDEX, ["character_id"], unique=False)

    with op.batch_alter_table("character_take", schema=None) as batch_op:
        batch_op.add_column(sa.Column("character_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema. Every character version is deleted; the takes keep their pictures,
    speeches and clips and only lose the version number they were made under.
    """
    with op.batch_alter_table("character_take", schema=None) as batch_op:
        batch_op.drop_column("character_version")

    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_INDEX)
    op.drop_table(_TABLE)
