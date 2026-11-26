"""split evidence clips

OVL-007 (`Graphic_overlays_implementation_phases.md`). Where a graphic overlay and evidence share
the screen, the evidence side is a clip drawn in its half of the frame, made by the same
`render_evidence_clip` job as a shot clip, so `evidence_clip.purpose` may now also be `split`.

`evidence_clip` is rebuilt (SQLite cannot change a CHECK in place); foreign keys are off on the
migration connection, so nothing cascades. No row is changed.

Revision ID: 0103
Revises: 0102
Create Date: 2026-11-27 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0103"
down_revision: str | Sequence[str] | None = "0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLIP = "evidence_clip"
_PURPOSE_CHECK = op.f(f"ck_{_CLIP}_purpose_valid")


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table(_CLIP, schema=None) as batch_op:
        batch_op.drop_constraint(_PURPOSE_CHECK, type_="check")
        batch_op.create_check_constraint(
            _PURPOSE_CHECK, "purpose IN ('preview', 'shot', 'card', 'soundbite', 'split')"
        )


def downgrade() -> None:
    """Downgrade schema. The rows with purpose `split` (the old CHECK would refuse them) are
    deleted. Their video files stay where they are.
    """
    op.execute("DELETE FROM evidence_clip WHERE purpose = 'split'")
    with op.batch_alter_table(_CLIP, schema=None) as batch_op:
        batch_op.drop_constraint(_PURPOSE_CHECK, type_="check")
        batch_op.create_check_constraint(
            _PURPOSE_CHECK, "purpose IN ('preview', 'shot', 'card', 'soundbite')"
        )
