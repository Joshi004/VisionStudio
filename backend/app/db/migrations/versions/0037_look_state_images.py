"""pictures of named looks and environment states

PHASE-017. The pictures of the named looks and environment states that PHASE-016 resolved are
made by the Character lab's own look and picture machinery, so no table and no job type is
added. Four existing tables gain columns:

- `character_look`: `named_look_id` (FK to `character_named_look`, set null). A look with it set
  holds the pictures of that named look, not the character's canonical look: it never becomes
  the character's current look. The two tables point at each other (`character_named_look.look_id`
  is the finished look), the intended cycle, as `library_character.current_look_id` is.
- `library_character_version`: `named_looks` (JSON, a list), the pictures of the character's
  finished named looks as the version froze them.
- `environment_state`: `lab_run_id` (FK to `lab_run`, set null), the edit run that makes the
  state's picture, and `inputs` (JSON), what it was made from. `reference_image_id` already
  exists and is filled once the picture is stored.
- `library_environment_version`: `states` (JSON, a list), the pictures of the environment's
  states as the version froze them.

No data needs preserving, so nothing is backfilled: the two new JSON lists default to empty.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-21 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOOK_TABLE = "character_look"
_LOOK_INDEX = "idx_character_look_named_look"
_LOOK_FK = "fk_character_look_named_look_id_character_named_look"
_STATE_TABLE = "environment_state"
_STATE_RUN_FK = "fk_environment_state_lab_run_id_lab_run"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table(_LOOK_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("named_look_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_LOOK_FK),
            "character_named_look",
            ["named_look_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(_LOOK_INDEX, ["named_look_id"], unique=False)
    with op.batch_alter_table("library_character_version", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("named_looks", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
    with op.batch_alter_table(_STATE_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("lab_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("inputs", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_STATE_RUN_FK),
            "lab_run",
            ["lab_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("library_environment_version", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("states", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    """Downgrade schema. The pictures of named looks and states stay in the lab's pictures and
    only lose the link to the record they were made for.
    """
    with op.batch_alter_table("library_environment_version", schema=None) as batch_op:
        batch_op.drop_column("states")
    with op.batch_alter_table(_STATE_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_STATE_RUN_FK), type_="foreignkey")
        batch_op.drop_column("inputs")
        batch_op.drop_column("lab_run_id")
    with op.batch_alter_table("library_character_version", schema=None) as batch_op:
        batch_op.drop_column("named_looks")
    with op.batch_alter_table(_LOOK_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_LOOK_INDEX)
        batch_op.drop_constraint(batch_op.f(_LOOK_FK), type_="foreignkey")
        batch_op.drop_column("named_look_id")
