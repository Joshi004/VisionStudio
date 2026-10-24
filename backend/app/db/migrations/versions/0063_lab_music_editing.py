"""lab music editing

MUSIC-004. The Music lab can repair, extend, join and restyle audio with the GPU server's editing
endpoints.

- `lab_music_source`: one row per audio file made for editing (an uploaded recording, or two lab
  runs joined end to end, with the recipe of the join). An edit may also use a finished lab run
  directly, which needs no row here.
- `lab_music_run` gains `operation` (NULL for text-to-audio; repaint, cover, inpaint or
  transform for an edit), `source_run_id` and `source_id` (what the edit started from: exactly
  one of them for an edit, none otherwise). The window or the strength is in `fields`, the seed
  in `params`, as for every run.

The job type is unchanged: an edit is a `lab_music` job. No existing row is changed, so nothing
is backfilled.

Revision ID: 0063
Revises: 0062
Create Date: 2026-10-24 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0063"
down_revision: str | Sequence[str] | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE = "lab_music_source"
_RUN = "lab_music_run"
_OPERATION_CHECK = "operation IS NULL OR operation IN ('repaint', 'cover', 'inpaint', 'transform')"
_SOURCE_CHECK = (
    "(operation IS NULL AND source_run_id IS NULL AND source_id IS NULL) "
    "OR (operation IS NOT NULL AND (source_run_id IS NULL) + (source_id IS NULL) = 1)"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        _SOURCE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("duration_s", sa.REAL(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("recipe", sa.JSON(), nullable=True),
        sa.CheckConstraint("kind IN ('upload', 'join')", name=op.f(f"ck_{_SOURCE}_kind_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_SOURCE}")),
    )
    with op.batch_alter_table(_SOURCE, schema=None) as batch_op:
        batch_op.create_index("idx_lab_music_source_created", ["created_at"], unique=False)

    with op.batch_alter_table(_RUN, schema=None) as batch_op:
        batch_op.add_column(sa.Column("operation", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(f"fk_{_RUN}_source_run_id_{_RUN}"),
            _RUN,
            ["source_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            batch_op.f(f"fk_{_RUN}_source_id_{_SOURCE}"),
            _SOURCE,
            ["source_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(op.f(f"ck_{_RUN}_operation_valid"), _OPERATION_CHECK)
        batch_op.create_check_constraint(op.f(f"ck_{_RUN}_source_matches_operation"), _SOURCE_CHECK)


def downgrade() -> None:
    """Downgrade schema. The edit runs and the saved sources are lost."""
    op.execute(f"DELETE FROM {_RUN} WHERE operation IS NOT NULL")
    with op.batch_alter_table(_RUN, schema=None) as batch_op:
        batch_op.drop_constraint(op.f(f"ck_{_RUN}_source_matches_operation"), type_="check")
        batch_op.drop_constraint(op.f(f"ck_{_RUN}_operation_valid"), type_="check")
        batch_op.drop_constraint(op.f(f"fk_{_RUN}_source_id_{_SOURCE}"), type_="foreignkey")
        batch_op.drop_constraint(op.f(f"fk_{_RUN}_source_run_id_{_RUN}"), type_="foreignkey")
        batch_op.drop_column("source_id")
        batch_op.drop_column("source_run_id")
        batch_op.drop_column("operation")
    with op.batch_alter_table(_SOURCE, schema=None) as batch_op:
        batch_op.drop_index("idx_lab_music_source_created")
    op.drop_table(_SOURCE)
