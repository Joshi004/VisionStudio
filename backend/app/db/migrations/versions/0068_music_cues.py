"""music cues

MUSIC-009. The detail and the prompts of every cue of the music plan.

- `music_cue`: one immutable row per version of one cue of one plan version. `detail` is what
  level 2 wrote (exact anchors, the broad order of moods, hit requests, mix notes, fades),
  `items` are the things to generate with their prompt wordings (level 3), and `pushback` is the
  cue's objection to the plan, if it made one. `inputs` records what the row was built from.
  `UNIQUE (plan_id, cue_id, version)`.
- `music_cue_audit`: one row per audit call over all cue prompts: what it found, and the ids of
  the cue rows that were current once its fixes were applied.
- `job`: its `type` CHECK gains `write_music_cue` and `audit_music_cues`. `job` is rebuilt
  (SQLite cannot change a CHECK in place), the same way revision 0067 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-25 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0068"
down_revision: str | Sequence[str] | None = "0067"
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
    "write_music_plan",
)
_NEW_JOB_TYPES = ("write_music_cue", "audit_music_cues")

_CUE = "music_cue"
_AUDIT = "music_cue_audit"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        UTCDateTime(),
        server_default=sa.text("(CURRENT_TIMESTAMP)"),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _NEW_JOB_TYPES)

    op.create_table(
        _CUE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("cue_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("pushback", sa.JSON(), nullable=True),
        _created_at(),
        sa.CheckConstraint("source IN ('ai', 'audit')", name=op.f(f"ck_{_CUE}_source_valid")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_CUE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["music_plan.id"],
            name=op.f(f"fk_{_CUE}_plan_id_music_plan"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_CUE}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_CUE}")),
        sa.UniqueConstraint("plan_id", "cue_id", "version", name=op.f(f"uq_{_CUE}_plan_id")),
    )
    with op.batch_alter_table(_CUE, schema=None) as batch_op:
        batch_op.create_index("idx_music_cue_plan", ["plan_id", "cue_id"], unique=False)

    op.create_table(
        _AUDIT,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("result_row_ids", sa.JSON(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_AUDIT}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["music_plan.id"],
            name=op.f(f"fk_{_AUDIT}_plan_id_music_plan"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_AUDIT}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_AUDIT}")),
    )
    with op.batch_alter_table(_AUDIT, schema=None) as batch_op:
        batch_op.create_index("idx_music_cue_audit_plan", ["plan_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every cue row and audit is deleted, and so is every job of the new
    types (the old `job.type` CHECK would refuse them).
    """
    with op.batch_alter_table(_AUDIT, schema=None) as batch_op:
        batch_op.drop_index("idx_music_cue_audit_plan")
    op.drop_table(_AUDIT)
    with op.batch_alter_table(_CUE, schema=None) as batch_op:
        batch_op.drop_index("idx_music_cue_plan")
    op.drop_table(_CUE)

    op.execute("DELETE FROM job WHERE type IN ('write_music_cue', 'audit_music_cues')")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
