"""lab music trial case

MUSIC-005. The Music lab shows the cases of a trial round with what to verify, the source audio,
what was done and the outputs, and keeps the person's answer to each case.

- `lab_music_trial_case`: one row per case. `guide` is the text the review screen shows,
  `run_ids` and `source_ids` are what the case started or made, and `answer` and `answer_note` are
  the person's answer. The runs keep their own verdict and note.

No existing table is changed, so nothing is backfilled.

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-24 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "lab_music_trial_case"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("trial_group", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("guide", sa.JSON(), nullable=False),
        sa.Column("run_ids", sa.JSON(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answer_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "answer IS NULL OR answer IN ('yes', 'partly', 'no')",
            name=op.f(f"ck_{_TABLE}_answer_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index("idx_lab_music_trial_case_order", ["sort_order"], unique=False)


def downgrade() -> None:
    """Downgrade schema. The cases and the answers are lost; the runs are not."""
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index("idx_lab_music_trial_case_order")
    op.drop_table(_TABLE)
