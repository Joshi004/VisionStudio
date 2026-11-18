"""evidence card purpose

EVD-011 (`Evidence_layer_implementation_phases.md`). An evidence card is a transparent clip laid
over a presenter or B-roll shot, made by the same `render_evidence_clip` job as a preview and a
shot clip, so `evidence_clip.purpose` may now also be `card`.

`evidence_clip` is rebuilt (SQLite cannot change a CHECK in place); foreign keys are off on the
migration connection, so nothing cascades. No row is changed.

Revision ID: 0099
Revises: 0098
Create Date: 2026-11-17 19:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0099"
down_revision: str | Sequence[str] | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLIP = "evidence_clip"
_PURPOSE_CHECK = op.f(f"ck_{_CLIP}_purpose_valid")


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table(_CLIP, schema=None) as batch_op:
        batch_op.drop_constraint(_PURPOSE_CHECK, type_="check")
        batch_op.create_check_constraint(_PURPOSE_CHECK, "purpose IN ('preview', 'shot', 'card')")


def downgrade() -> None:
    """Downgrade schema. The rows with purpose `card` (the old CHECK would refuse them) are
    deleted. Their video files stay where they are.
    """
    op.execute("DELETE FROM evidence_clip WHERE purpose = 'card'")
    with op.batch_alter_table(_CLIP, schema=None) as batch_op:
        batch_op.drop_constraint(_PURPOSE_CHECK, type_="check")
        batch_op.create_check_constraint(_PURPOSE_CHECK, "purpose IN ('preview', 'shot')")
