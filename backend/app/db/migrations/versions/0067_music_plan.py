"""music plan

MUSIC-008. The story's music plan: where score, ambience, hits and silence go, written by the
model, refined by critics and a reviser, and checked by code.

- `music_plan`: one immutable row per version of a project's plan, with the provenance of the
  artifact convention (`inputs`: the Music Bible and every scene's shot plan, speech units,
  events and definition it was built from, and the hash of the timeline). `timeline` is the
  condensed story timeline the plan was written against, `draft` the plan as first written,
  `rounds` the critics' notes and the revisions, `content` the final plan and `facts` measured
  facts about it. `UNIQUE (project_id, version)`.
- `job`: its `type` CHECK gains `write_music_plan`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0066 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-25 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0067"
down_revision: str | Sequence[str] | None = "0066"
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
    "check_shot_continuity",
    "repair_shot_cut",
    "compile_shot_prompt",
    "generate_shot",
    "render_story",
    "check_shot_takes",
    "story_pipeline",
    "check_take_dialogue",
    "select_shot_references",
    "lab_music",
    "write_lab_music_prompt",
    "stage_scene",
    "plan_environment_views",
    "write_environment_view_prompt",
    "write_music_bible",
    "write_music_theme_prompt",
)
_NEW_JOB_TYPES = ("write_music_plan",)

_TABLE = "music_plan"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _NEW_JOB_TYPES)

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("timeline", sa.JSON(), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("rounds", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
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
        batch_op.create_index("idx_music_plan_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every plan is deleted, and so is every job of the new type (the old
    `job.type` CHECK would refuse them).
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index("idx_music_plan_project")
    op.drop_table(_TABLE)

    op.execute("DELETE FROM job WHERE type = 'write_music_plan'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
