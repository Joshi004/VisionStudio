"""generate frame

Phase 17: a new job type (`generate_frame`, one paid image from the image model for one
scene) and a new job provider (`image`). Nothing else changes: the frame is an `asset` and the
scene already points at it (`first_frame_asset_id`).

`job` is rebuilt (SQLite cannot change a CHECK in place), once, with both CHECKs. `scene`
points at `job` twice (`description_job_id`, `image_prompt_job_id`). The migration connection
runs with foreign keys off (see `env.py`), so rebuilding a table cannot fire an ON DELETE
CASCADE or an ON DELETE SET NULL.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_clip', 'render_final')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final')"
)
_OLD_PROVIDERS = "provider IN ('gpu', 'llm', 'local')"
_NEW_PROVIDERS = "provider IN ('gpu', 'llm', 'image', 'local')"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.drop_constraint(op.f("ck_job_provider_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)
        batch_op.create_check_constraint(op.f("ck_job_provider_valid"), _NEW_PROVIDERS)


def downgrade() -> None:
    """Downgrade schema. Frame jobs are deleted, because the old CHECKs would refuse them."""
    op.execute("DELETE FROM job WHERE type = 'generate_frame' OR provider = 'image'")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.drop_constraint(op.f("ck_job_provider_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
        batch_op.create_check_constraint(op.f("ck_job_provider_valid"), _OLD_PROVIDERS)
