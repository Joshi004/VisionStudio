"""scenes of a recorded project that use the generated voice

REC-007. A project whose voice is recorded (`take_source` `recorded`) can still have some scenes
spoken by the speech model, in the presenter's voice.

- `project.generated_take_scenes`: the ids of the scenes (in the scene discovery) that use the
  generated take instead of the recorded one. NOT NULL, default `[]`, so every project that
  exists reads "none". Only read while `take_source` is `recorded`. Both kinds of take are kept,
  so a scene can be switched back at any time.

Revision ID: 0105
Revises: 0104
Create Date: 2026-11-27 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0105"
down_revision: str | Sequence[str] | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "generated_take_scenes", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("generated_take_scenes")
