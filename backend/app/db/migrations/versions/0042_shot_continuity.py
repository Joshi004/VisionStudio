"""shot continuity checks

PHASE-023. The continuity check of a scene's shots stores its verdict in a new table and runs as
a new job type.

- `shot_continuity_check`: one row per check of one scene, that is, one version of that scene's
  continuity verdict. It follows the artifact provenance convention (DATABASE_STRUCTURE.md
  Section 2.1): `source`, `job_id`, `version`, `inputs` and `created_at`, plus `project_id`, the
  scene's slug `scene_id`, the id of the `shot_plan` row the shots belong to, the `round` (how
  many re-definitions for continuity came before this check) and the verdict itself
  (`content`). A scene's checks are numbered from 1 (`UNIQUE (project_id, scene_id, version)`),
  and a stored row is never changed. `inputs` records the story hash, the artifacts the check
  was made from (the scene's definition, the shot plan and every shot definition it read).
- `job`: its `type` CHECK gains `check_shot_continuity`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revisions 0028 to 0041 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-21 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0042"
down_revision: str | Sequence[str] | None = "0041"
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
    "discover_scenes",
    "define_character",
    "discover_relations",
    "design_voice",
    "write_environment_prompt",
    "define_environment",
    "define_scene",
    "extract_events",
    "resolve_looks_states",
    "synthesize_speech_unit",
    "plan_shots",
    "define_shot",
)
_CHECK_JOB_TYPE = "check_shot_continuity"
_TABLE = "shot_continuity_check"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_CHECK_JOB_TYPE,))
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("shot_plan_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
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
            ["shot_plan_id"],
            ["shot_plan.id"],
            name=op.f(f"fk_{_TABLE}_shot_plan_id_shot_plan"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TABLE}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint(
            "project_id",
            "scene_id",
            "version",
            name=op.f(f"uq_{_TABLE}_project_id"),
        ),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            f"idx_{_TABLE}_project_scene", ["project_id", "scene_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema. Every continuity check and every `check_shot_continuity` job row is
    deleted (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TABLE}_project_scene")
    op.drop_table(_TABLE)

    op.execute("DELETE FROM job WHERE type = 'check_shot_continuity'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
