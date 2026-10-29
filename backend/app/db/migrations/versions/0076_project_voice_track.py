"""project voice track

FLOW-002. An explainer says how its speech is made, once, when it is created, and may carry a
presenter delivery text.

- `project.voice_track`: `lines` (each line is its own speech, what every project did until
  now) or `continuous` (one voice take per scene, the picture cut on top of it). NOT NULL,
  default `lines`, so every project that exists reads `lines`. It is never changed after
  creation, and a story is always `lines`.
- `project.presenter_delivery`: the owner's text that steers the voice of every take of a
  `continuous` explainer (at most 500 characters). NULL means "use the Story Bible's narration
  style, or the default".

No data needs preserving, so nothing is backfilled.

Revision ID: 0076
Revises: 0075
Create Date: 2026-10-29 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0076"
down_revision: str | Sequence[str] | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("voice_track", sa.Text(), server_default=sa.text("'lines'"), nullable=False)
        )
        batch_op.add_column(sa.Column("presenter_delivery", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            op.f("ck_project_voice_track_valid"),
            "voice_track IN ('lines', 'continuous')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_project_voice_track_valid"), type_="check")
        batch_op.drop_column("presenter_delivery")
        batch_op.drop_column("voice_track")
