"""character and environment discovery

PHASE-005. Two story stages store their result in new tables and run as new job types.

- `character_discovery` and `environment_discovery`: one row per run of the stage, that is, one
  version of the project's list of characters (or environments). Both follow the artifact
  provenance convention (DATABASE_STRUCTURE.md Section 2.1) exactly as `story_bible` does:
  `source`, `job_id`, `version`, `inputs` and `created_at`, plus `project_id` and the list
  itself (`content`). A project's versions are numbered from 1 (`UNIQUE (project_id, version)`)
  in each table, and a stored row is never changed. `inputs` records the story hash and the
  StoryBible version the list was made from.
- `job`: its `type` CHECK gains `discover_characters` and `discover_environments`. `job` is
  rebuilt (SQLite cannot change a CHECK in place), the same way revisions 0016, 0022 and 0023
  did. The migration connection runs with foreign keys off (see `env.py`), so rebuilding it
  cannot fire an ON DELETE rule. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-20 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
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
)
_DISCOVERY_JOB_TYPES = ("discover_characters", "discover_environments")
_DISCOVERY_TABLES = ("character_discovery", "environment_discovery")


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def _create_discovery_table(table: str) -> None:
    """One table of the shape of `story_bible`. `table` is a fixed name from this file."""
    op.create_table(
        table,
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
        sa.CheckConstraint("source IN ('ai', 'manual')", name=op.f(f"ck_{table}_source_valid")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{table}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{table}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{table}_project_id")),
    )
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.create_index(f"idx_{table}_project", ["project_id"], unique=False)


def _drop_discovery_table(table: str) -> None:
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{table}_project")
    op.drop_table(table)


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _DISCOVERY_JOB_TYPES)
    for table in _DISCOVERY_TABLES:
        _create_discovery_table(table)


def downgrade() -> None:
    """Downgrade schema. Every discovered list and every discovery job row is deleted (the old
    `job.type` CHECK would refuse the jobs).
    """
    for table in _DISCOVERY_TABLES:
        _drop_discovery_table(table)

    op.execute("DELETE FROM job WHERE type IN ('discover_characters', 'discover_environments')")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
