"""scene discovery

PHASE-006. The third discovery stage stores its result in a new table and runs as a new job
type.

- `scene_discovery`: one row per run of the stage, that is, one version of the project's list
  of scenes. It follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1)
  exactly as `story_bible`, `character_discovery` and `environment_discovery` do: `source`,
  `job_id`, `version`, `inputs` and `created_at`, plus `project_id` and the list itself
  (`content`). A project's versions are numbered from 1 (`UNIQUE (project_id, version)`), and a
  stored row is never changed. `inputs` records the story hash and the StoryBible version the
  list was made from. Each scene in `content` carries the slice of the author's story it owns,
  cut by code, so the slices joined in order are the whole story.
- `job`: its `type` CHECK gains `discover_scenes`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revisions 0016, 0022, 0023 and 0024 did. The migration
  connection runs with foreign keys off (see `env.py`), so rebuilding it cannot fire an
  ON DELETE rule. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-20 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EARLIER_JOB_TYPES = (
    "lab_image",
    "lab_video",
    "write_lab_video_prompt",
    "lab_voice",
    "write_character_look_prompt",
    "write_character_take_prompt",
    "write_story_bible",
    "discover_characters",
    "discover_environments",
)
_SCENE_JOB_TYPE = "discover_scenes"
_TABLE = "scene_discovery"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_SCENE_JOB_TYPE,))
    op.create_table(
        _TABLE,
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
        sa.CheckConstraint("source IN ('ai', 'manual')", name=op.f(f"ck_{_TABLE}_source_valid")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TABLE}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_TABLE}_project_id")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_TABLE}_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every discovered scene list and every scene discovery job row is
    deleted (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TABLE}_project")
    op.drop_table(_TABLE)

    op.execute("DELETE FROM job WHERE type = 'discover_scenes'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
