"""music bible

MUSIC-006. Every story gets a musical identity, chosen from four directions.

- `music_bible`: one row per version of a project's Music Bible. It follows the artifact
  provenance convention (DATABASE_STRUCTURE.md Section 2.1). `directions` holds the four
  directions, `choice` the chosen one with its reasons and who chose it, and `content` the
  Bible. `UNIQUE (project_id, version)`.
- `project.music_enabled`: whether the story gets planned music (MD-21). On for every project,
  existing ones included.
- `job`: its `type` CHECK gains `write_music_bible`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0059 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-25 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0065"
down_revision: str | Sequence[str] | None = "0064"
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
)
_NEW_JOB_TYPES = ("write_music_bible",)
_TABLE = "music_bible"


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
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("music_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1"))
        )
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("directions", sa.JSON(), nullable=False),
        sa.Column("choice", sa.JSON(), nullable=False),
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
            ["job_id"], ["job.id"], name=op.f(f"fk_{_TABLE}_job_id_job"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_TABLE}_project_id")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index("idx_music_bible_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every Music Bible and every job of the new type is deleted (the old
    `job.type` CHECK would refuse the jobs), and the project's music switch is lost.
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index("idx_music_bible_project")
    op.drop_table(_TABLE)
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("music_enabled")
    op.execute("DELETE FROM job WHERE type = 'write_music_bible'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
