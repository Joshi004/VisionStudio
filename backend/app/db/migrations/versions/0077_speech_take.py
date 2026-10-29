"""speech take

FLOW-003. A continuous explainer speaks each scene as one take, stored in `speech_unit_audio`
beside the speech of the units of the other projects.

- `speech_unit_audio.unit_id`: now nullable. A take belongs to a scene, not to one unit.
- `speech_unit_audio.kind`: the CHECK gains `take`.

No row is changed and nothing is backfilled. The table is rebuilt (SQLite cannot change a
CHECK or a NOT NULL in place); foreign keys are off on the migration connection, so nothing
cascades.

Revision ID: 0077
Revises: 0076
Create Date: 2026-10-29 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0077"
down_revision: str | Sequence[str] | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "speech_unit_audio"
_KIND_CHECK = op.f(f"ck_{_TABLE}_kind_valid")


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.alter_column("unit_id", existing_type=sa.Text(), nullable=True)
        batch_op.drop_constraint(_KIND_CHECK, type_="check")
        batch_op.create_check_constraint(_KIND_CHECK, "kind IN ('narration', 'dialogue', 'take')")


def downgrade() -> None:
    """Downgrade schema. Every take (a row with kind `take`) is deleted, with its word timing,
    because the old table cannot hold a row with no unit. Stored files are kept.
    """
    op.execute(
        "DELETE FROM speech_word_timing WHERE speech_unit_audio_id IN "
        f"(SELECT id FROM {_TABLE} WHERE kind = 'take')"
    )
    op.execute(f"DELETE FROM {_TABLE} WHERE kind = 'take'")
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_KIND_CHECK, type_="check")
        batch_op.create_check_constraint(_KIND_CHECK, "kind IN ('narration', 'dialogue')")
        batch_op.alter_column("unit_id", existing_type=sa.Text(), nullable=False)
