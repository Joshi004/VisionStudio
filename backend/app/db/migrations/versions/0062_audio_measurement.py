"""audio measurements

MUSIC-003. What is measured in an audio file (length, silences, loudness, loudest moment, sudden
sounds, quiet points, change points, ending) is stored once per file content.

- `audio_measurement`: one row per (`sha256`, `analysis_version`): the file's SHA-256, the version
  of the analysis that made the result, and the result as JSON. The key is the file's content
  hash, which the lab runs, the speech units' audio and the shot takes already store, so no
  existing table changes.

Nothing is backfilled: a file is measured the first time something asks.

Revision ID: 0062
Revises: 0061
Create Date: 2026-10-24 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0062"
down_revision: str | Sequence[str] | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "audio_measurement"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint("sha256", "analysis_version", name=op.f(f"uq_{_TABLE}_sha256")),
    )


def downgrade() -> None:
    """Downgrade schema. The measurements are lost; they are measured again when asked for."""
    op.drop_table(_TABLE)
