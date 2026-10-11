"""last frames made by the image model

Phase 23: two new job types and, per scene, the edit prompt for its last frame.

- `job`: its `type` CHECK gains `write_last_frame_prompt` (a paid call to the language model that
  writes the instruction for editing the first frame into the last) and `generate_last_frame`
  (the GPU server's image edit that makes the frame). `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0011 did. The migration connection runs with foreign
  keys off (see `env.py`), so rebuilding a table cannot fire an ON DELETE CASCADE or an ON DELETE
  SET NULL.
- `scene`: `last_frame_prompt` (the edit instruction), `last_frame_prompt_source` (`manual` or
  `ai`) and `last_frame_prompt_job_id` (the job that wrote the AI text), the counterparts of
  `image_prompt`, `image_prompt_source` and `image_prompt_job_id`.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-11 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover', 'lab_image')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover', 'lab_image', "
    "'write_last_frame_prompt', 'generate_last_frame')"
)
_SOURCE_CHECK = "ck_scene_last_frame_prompt_source_valid"
_JOB_FK = "fk_scene_last_frame_prompt_job_id_job"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)

    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_frame_prompt", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_frame_prompt_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_frame_prompt_job_id", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            op.f(_SOURCE_CHECK), "last_frame_prompt_source IN ('manual', 'ai')"
        )
        batch_op.create_foreign_key(
            batch_op.f(_JOB_FK),
            "job",
            ["last_frame_prompt_job_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema. Last frame jobs are deleted, because the old CHECK would refuse them.
    A last frame they made stays on its scene as an ordinary frame, and its files stay in
    `media/`.
    """
    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_JOB_FK), type_="foreignkey")
        batch_op.drop_constraint(op.f(_SOURCE_CHECK), type_="check")
        batch_op.drop_column("last_frame_prompt_job_id")
        batch_op.drop_column("last_frame_prompt_source")
        batch_op.drop_column("last_frame_prompt")

    op.execute("DELETE FROM job WHERE type IN ('write_last_frame_prompt', 'generate_last_frame')")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
