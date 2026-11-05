"""caption mode

CAP-001. An explainer chooses how its captions are delivered: `burned` (drawn on the picture, as
every explainer did until now) or `ytt` (nothing drawn in the picture; the captions come as a
file).

- `project.caption_mode`: `burned` or `ytt`. NOT NULL, default `burned`. It replaces
  `project.captions`: a project that had captions on becomes `burned`, and one that had them off
  becomes `ytt` (it keeps a clean picture).
- `project.captions` is dropped.

The downgrade brings `captions` back from `caption_mode` (`ytt` becomes off, `burned` on).

Revision ID: 0087
Revises: 0086
Create Date: 2026-11-05 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0087"
down_revision: str | Sequence[str] | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_project_caption_mode_valid"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("caption_mode", sa.Text(), server_default=sa.text("'burned'"), nullable=False)
        )
        batch_op.create_check_constraint(op.f(_CHECK), "caption_mode IN ('burned', 'ytt')")
    op.execute("UPDATE project SET caption_mode = 'ytt' WHERE captions = 0")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("captions")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("captions", sa.Boolean(), server_default=sa.text("1"), nullable=False)
        )
    op.execute("UPDATE project SET captions = 0 WHERE caption_mode = 'ytt'")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_CHECK), type_="check")
        batch_op.drop_column("caption_mode")
