"""retire the transcription of sound bite clips

The words of a sound bite clip now come from the captions of its source, worked out while the
import makes its rows (`soundbite_clips.analyse_now`), so the `transcribe_evidence_clip` job has
no handler any more. A job of that type that is still `queued` or `running` would wait for a
handler that never comes, so it is marked `cancelled`. Finished jobs and the clips' stored words
are not changed, and the job type stays in the `job.type` CHECK so old jobs still read.

Only data changes; no table is rebuilt. The downgrade has nothing to restore: a cancelled job is
not queued again.

Revision ID: 0101
Revises: 0100
Create Date: 2026-11-24 01:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0101"
down_revision: str | Sequence[str] | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "UPDATE job SET status = 'cancelled', phase = 'cancelled', "
        "error = 'Sound bite clips are no longer transcribed; their words come from the "
        "source captions.', finished_at = CURRENT_TIMESTAMP "
        "WHERE type = 'transcribe_evidence_clip' AND status IN ('queued', 'running')"
    )


def downgrade() -> None:
    """Downgrade schema. Nothing to undo."""
