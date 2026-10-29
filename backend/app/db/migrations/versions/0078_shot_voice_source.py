"""shot voice source

FLOW-008. The owner can switch one presenter shot of a continuous explainer to its clip's own
voice (F-9). The setting is kept on the shot, not on its clip.

- `shot_voice_source`: one row per switched shot (unique per project, scene and shot). A row
  means `clip`; no row means `take`. The row names the shot plan it was set on and counts only
  while that plan is the scene's newest, so planning the scene again puts every shot back on
  `take`.

Nothing existing is changed and nothing is backfilled.

Revision ID: 0078
Revises: 0077
Create Date: 2026-10-29 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0078"
down_revision: str | Sequence[str] | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "shot_voice_source"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("shot_id", sa.Text(), nullable=False),
        sa.Column("shot_plan_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shot_plan_id"],
            ["shot_plan.id"],
            name=op.f(f"fk_{_TABLE}_shot_plan_id_shot_plan"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint(
            "project_id", "scene_id", "shot_id", name=op.f(f"uq_{_TABLE}_project_id")
        ),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_TABLE}_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every switched shot goes back to its take's voice."""
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TABLE}_project")
    op.drop_table(_TABLE)
