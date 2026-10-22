"""shot prompts

PHASE-026. The final H3 prompt of a shot is written by a language model (pieces) and put
together by code (headings, labels, retention lines, audio lines, music disabled). It gets a new
job type and a table.

- `job`: its `type` CHECK gains `compile_shot_prompt`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revisions 0028 to 0045 did. No row is changed.
- `shot_prompt`: one row per compilation of one shot, that is, one version of that shot's
  prompt. It follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1):
  `source`, `job_id`, `version`, `inputs` and `created_at`, plus `project_id`, the scene's slug
  `scene_id`, the shot's id `shot_id`, the id of the `generation_request` row the prompt was
  compiled for, and the prompt itself (`content`). A shot's prompts are numbered from 1
  (`UNIQUE (project_id, scene_id, shot_id, version)`), and a stored row is never changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-22 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0046"
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "shot_prompt"

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
    "check_shot_continuity",
    "repair_shot_cut",
)
_COMPILE_JOB_TYPE = "compile_shot_prompt"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_COMPILE_JOB_TYPE,))
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("shot_id", sa.Text(), nullable=False),
        sa.Column("generation_request_id", sa.Integer(), nullable=True),
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
            ["generation_request_id"],
            ["generation_request.id"],
            name=op.f(f"fk_{_TABLE}_generation_request_id_generation_request"),
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
            "shot_id",
            "version",
            name=op.f(f"uq_{_TABLE}_project_id"),
        ),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            f"idx_{_TABLE}_project_scene", ["project_id", "scene_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema. Every shot prompt and every `compile_shot_prompt` job row is deleted
    (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TABLE}_project_scene")
    op.drop_table(_TABLE)
    op.execute("DELETE FROM job WHERE type = 'compile_shot_prompt'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
