"""transcript source

Records which voiceover and which script a transcript was made from, so the app can tell
when either has changed since (Phase 5). `transcript` is empty when this runs on the first
database that has it, so the NOT NULL column needs no default.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 18:10:18.271387

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("transcript", schema=None) as batch_op:
        batch_op.add_column(sa.Column("voiceover_asset_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("script_sha256", sa.Text(), nullable=False))
        batch_op.create_foreign_key(
            batch_op.f("fk_transcript_voiceover_asset_id_asset"),
            "asset",
            ["voiceover_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("transcript", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_transcript_voiceover_asset_id_asset"), type_="foreignkey"
        )
        batch_op.drop_column("script_sha256")
        batch_op.drop_column("voiceover_asset_id")
