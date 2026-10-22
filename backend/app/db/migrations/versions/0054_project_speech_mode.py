"""project speech mode

A project now has a `speech_mode`, chosen when it is created and never changed after:

- `both`: the story has narration and dialogue (what every project did until now).
- `no_dialogue`: only a narrator speaks; a character's lines are read by the narrator.
- `no_narration`: nobody narrates; the story is told by what the characters do and say.

Existing projects get `both`, so nothing about them changes.

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-22 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0054"
down_revision: str | Sequence[str] | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("speech_mode", sa.Text(), server_default=sa.text("'both'"), nullable=False)
        )
        batch_op.create_check_constraint(
            op.f("ck_project_speech_mode_valid"),
            "speech_mode IN ('both', 'no_dialogue', 'no_narration')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_project_speech_mode_valid"), type_="check")
        batch_op.drop_column("speech_mode")
