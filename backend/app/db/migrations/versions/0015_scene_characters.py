"""a scene shows any number of characters: scene_character replaces scene.character_id

Project cast, several characters in a scene. Two things change:

- `scene_character`: new table, one row for each character a scene shows, with the `position`
  of the character's reference picture (0 is the first picture sent to the image model).
  Both foreign keys are `ON DELETE CASCADE`.
- `scene`: `character_id` is dropped. Every scene that had a character gets one row in
  `scene_character` at position 0 first, so no choice is lost. `scene` is rebuilt (SQLite
  cannot drop a column that is a foreign key in place), the same way revision 0014 did. The
  migration connection runs with foreign keys off (see `env.py`), so rebuilding a table cannot
  fire an ON DELETE CASCADE or an ON DELETE SET NULL.

The downgrade puts the first character of each scene (the lowest position) back into
`scene.character_id`. A scene that shows several keeps only that one.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-13 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHARACTER_FK = "fk_scene_character_id_character"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "scene_character",
        sa.Column("scene_id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scene_id"],
            ["scene.id"],
            name=op.f("fk_scene_character_scene_id_scene"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["character.id"],
            name=op.f("fk_scene_character_character_id_character"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("scene_id", "character_id", name=op.f("pk_scene_character")),
    )
    with op.batch_alter_table("scene_character", schema=None) as batch_op:
        batch_op.create_index("idx_scene_character_character", ["character_id"], unique=False)

    op.execute(
        "INSERT INTO scene_character (scene_id, character_id, position) "
        "SELECT id, character_id, 0 FROM scene WHERE character_id IS NOT NULL"
    )

    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_CHARACTER_FK), type_="foreignkey")
        batch_op.drop_column("character_id")


def downgrade() -> None:
    """Downgrade schema. A scene that shows several characters keeps the first one."""
    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.add_column(sa.Column("character_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_CHARACTER_FK), "character", ["character_id"], ["id"], ondelete="SET NULL"
        )

    op.execute(
        "UPDATE scene SET character_id = ("
        "SELECT character_id FROM scene_character "
        "WHERE scene_character.scene_id = scene.id ORDER BY position LIMIT 1)"
    )

    with op.batch_alter_table("scene_character", schema=None) as batch_op:
        batch_op.drop_index("idx_scene_character_character")
    op.drop_table("scene_character")
