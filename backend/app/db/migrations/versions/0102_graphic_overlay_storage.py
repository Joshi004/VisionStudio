"""storage for overlay graphics

OVL-001 (`Graphic_overlays_implementation_phases.md`). This one migration creates everything the
graphics of overlays need to be stored, so the later phases add no migration.

- `shot_graphic_brief`, `shot_graphic` and `shot_graphic_choice` each gain `target`: `shot` for a
  graphic shot (every row that exists) or `overlay` for an overlay graphic. NOT NULL, default
  `shot`, with a CHECK. For an overlay, `scene_id` is the scene, `shot_id` holds the overlay's
  `{first}-{last}` words and `shot_plan_id` is NULL.
- The UNIQUE of the brief and of the choice now includes `target`, so a shot's rows and an
  overlay's rows can never be mixed up. The UNIQUE of `shot_graphic` is on `brief_id`, which
  already fixes the target, so it is not changed.

No overlay row is written by this migration, and no existing row is changed: every row reads
`shot`. Foreign keys are off on the migration connection, so a rebuilt table cascades nothing.

Revision ID: 0102
Revises: 0101
Create Date: 2026-11-26 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0102"
down_revision: str | Sequence[str] | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BRIEF = "shot_graphic_brief"
_GRAPHIC = "shot_graphic"
_CHOICE = "shot_graphic_choice"

_TARGET_CHECK = "target IN ('shot', 'overlay')"


def _target_check_name(table: str) -> str:
    return op.f(f"ck_{table}_target_valid")


def _add_target(table: str) -> None:
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("target", sa.Text(), server_default=sa.text("'shot'"), nullable=False)
        )
        batch_op.create_check_constraint(_target_check_name(table), _TARGET_CHECK)


def _drop_target(table: str) -> None:
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_constraint(_target_check_name(table), type_="check")
        batch_op.drop_column("target")


def _replace_unique(table: str, columns: list[str]) -> None:
    """The table's UNIQUE (`uq_<table>_project_id`) on these columns."""
    name = op.f(f"uq_{table}_project_id")
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_constraint(name, type_="unique")
        batch_op.create_unique_constraint(name, columns)


def upgrade() -> None:
    """Upgrade schema."""
    for table in (_BRIEF, _GRAPHIC, _CHOICE):
        _add_target(table)
    _replace_unique(_BRIEF, ["project_id", "target", "scene_id", "shot_id", "version"])
    _replace_unique(_CHOICE, ["project_id", "target", "scene_id", "shot_id"])


def downgrade() -> None:
    """Downgrade schema. Every overlay row is deleted first (choices, then graphics, then
    briefs), because the old UNIQUE could not tell an overlay from a shot.
    """
    op.execute(f"DELETE FROM {_CHOICE} WHERE target = 'overlay'")
    op.execute(f"DELETE FROM {_GRAPHIC} WHERE target = 'overlay'")
    op.execute(f"DELETE FROM {_BRIEF} WHERE target = 'overlay'")
    _replace_unique(_BRIEF, ["project_id", "scene_id", "shot_id", "version"])
    _replace_unique(_CHOICE, ["project_id", "scene_id", "shot_id"])
    for table in (_CHOICE, _GRAPHIC, _BRIEF):
        _drop_target(table)
