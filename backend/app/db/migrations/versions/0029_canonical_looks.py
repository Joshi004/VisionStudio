"""canonical looks

PHASE-010. A story project can have the pipeline make a library character's look by itself
(one candidate, taken as the master, then the four other angles). Such a look carries the
project and the discovered character it was made for.

- `character_look`: gains the nullable `project_id` (FK to `project`, set null when the project
  is deleted, indexed), `discovery_id` (the slug of the discovered character in that project)
  and `inputs` (JSON, the D-3 provenance of the look: the project, the discovered character,
  the character version it was made from and a hash of the definition it read). A look made by
  hand in the Character Lab has none of the three.

No data needs preserving, so nothing is backfilled. There is no new `job.type`.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-20 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "character_look"
_INDEX = "idx_character_look_project"
_PROJECT_FK = "fk_character_look_project_id_project"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("discovery_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("inputs", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_PROJECT_FK),
            "project",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(_INDEX, ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. The looks the pipeline made stay, and only lose the mark of which
    project and discovered character they were made for.
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_INDEX)
        batch_op.drop_constraint(batch_op.f(_PROJECT_FK), type_="foreignkey")
        batch_op.drop_column("inputs")
        batch_op.drop_column("discovery_id")
        batch_op.drop_column("project_id")
