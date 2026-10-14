"""MiniMax H3 in the Video lab

Two things change, both on `lab_video_run`:

- its `video_model` CHECK also accepts `minimax-h3`. `lab_video_run` is rebuilt (SQLite cannot
  change a CHECK in place), the same way revision 0008 rebuilt `job`. The migration connection
  runs with foreign keys off (see `env.py`), so rebuilding it cannot fire an ON DELETE rule.
  The CHECKs on `project`, `scene` and `character_take` are not touched: MiniMax H3 can only be
  chosen in the Video lab.
- `references`: the pictures a MiniMax H3 reference clip was made from, in the order the prompt
  names them (`<Picture 1>`, `<Picture 2>`, ...), as a list of `{source: "lab" | "asset", id}`.
  NULL for every other clip.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-14 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_NAME = "ck_lab_video_run_video_model_valid"
_OLD_CHECK = "video_model IN ('ltx-2.3', 'ltx-2.5')"
_NEW_CHECK = "video_model IN ('ltx-2.3', 'ltx-2.5', 'minimax-h3')"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_CHECK_NAME), type_="check")
        batch_op.create_check_constraint(op.f(_CHECK_NAME), _NEW_CHECK)
        batch_op.add_column(sa.Column("references", sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema. The MiniMax H3 runs are deleted, because the old CHECK would refuse
    them. Their jobs stay (a job holds no foreign key to its run) and their clips stay in
    `media/lab/`: only the rows that listed them are lost.
    """
    op.execute("DELETE FROM lab_video_run WHERE video_model = 'minimax-h3'")
    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.drop_column("references")
        batch_op.drop_constraint(op.f(_CHECK_NAME), type_="check")
        batch_op.create_check_constraint(op.f(_CHECK_NAME), _OLD_CHECK)
