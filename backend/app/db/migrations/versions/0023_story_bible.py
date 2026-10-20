"""the Story Bible stage

PHASE-004. The first story stage stores its result in a new table and runs as a new job type.

- `story_bible`: one row per version of a story project's StoryBible. It follows the artifact
  provenance convention (DATABASE_STRUCTURE.md Section 2.1): `source`, `job_id`, `version`,
  `inputs` and `created_at`, plus `project_id` and the bible itself (`content`). A project's
  versions are numbered from 1 (`UNIQUE (project_id, version)`), and a stored row is never
  changed.
- `job`: its `type` CHECK gains `write_story_bible`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revisions 0016 and 0022 did. The migration connection runs
  with foreign keys off (see `env.py`), so rebuilding it cannot fire an ON DELETE rule. No row
  is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-20 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LAB_JOB_TYPES = (
    "lab_image",
    "lab_video",
    "write_lab_video_prompt",
    "lab_voice",
    "write_character_look_prompt",
    "write_character_take_prompt",
)
_STORY_JOB_TYPES = ("write_story_bible",)


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_LAB_JOB_TYPES + _STORY_JOB_TYPES)

    op.create_table(
        "story_bible",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('ai', 'manual')", name=op.f("ck_story_bible_source_valid")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_story_bible_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f("fk_story_bible_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_story_bible")),
        sa.UniqueConstraint("project_id", "version", name=op.f("uq_story_bible_project_id")),
    )
    with op.batch_alter_table("story_bible", schema=None) as batch_op:
        batch_op.create_index("idx_story_bible_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every Story Bible and every `write_story_bible` job row is deleted
    (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table("story_bible", schema=None) as batch_op:
        batch_op.drop_index("idx_story_bible_project")
    op.drop_table("story_bible")

    op.execute("DELETE FROM job WHERE type = 'write_story_bible'")
    _rebuild_job_check(_LAB_JOB_TYPES)
