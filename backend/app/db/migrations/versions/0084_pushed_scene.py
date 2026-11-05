"""pushed scene

SCN-002: the owner can push one scene of a story to the front of the GPU server's queue.

- `project.pushed_scene_id`: the id of the scene pushed to the front (the id the scene has in
  the scene discovery, for example `scene_3`). Its clips are sent to the server with the most
  urgent priority. NULL means no scene is pushed. At most one scene per project.

No data needs preserving, so nothing is backfilled.

Revision ID: 0084
Revises: 0083
Create Date: 2026-11-04 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0084"
down_revision: str | Sequence[str] | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pushed_scene_id", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("pushed_scene_id")
