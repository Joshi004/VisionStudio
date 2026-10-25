"""music takes

MUSIC-010. The takes of every music cue and hit.

- `music_take`: one row per take of one thing to generate (an `item_id` of a cue's detail: the
  cue itself, or one of its hits). The audio is a Music lab run (`lab_run_id`), as for the
  theme recordings. `fields` are the prompt fields exactly as sent, `check_result` the technical
  check and the measured facts, and `cue_snapshot` what lock matching reads (the cue's kind,
  theme, emotion and span, or its moment). `detail_sha256` says which version of the cue's
  detail the take was made for. Selection, rejection with a note and the lock are columns of the
  take. A take is never deleted and its audio and prompt never change.
- `job`: its `type` CHECK gains `rewrite_music_prompt`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0068 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0069
Revises: 0068
Create Date: 2026-10-25 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0069"
down_revision: str | Sequence[str] | None = "0068"
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
    "write_music_cue",
    "audit_music_cues",
)
_NEW_JOB_TYPES = ("rewrite_music_prompt",)

_TAKE = "music_take"


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
        _TAKE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("cue_id", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("cue_row_id", sa.Integer(), nullable=True),
        sa.Column("detail_sha256", sa.Text(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("wording", sa.Integer(), nullable=True),
        sa.Column("retry_of_id", sa.Integer(), nullable=True),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("requested_s", sa.Float(), nullable=False),
        sa.Column("cue_snapshot", sa.JSON(), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=True),
        sa.Column("check_result", sa.JSON(), nullable=True),
        sa.Column("selected_at", UTCDateTime(), nullable=True),
        sa.Column("selected_by", sa.Text(), nullable=True),
        sa.Column("rejected_at", UTCDateTime(), nullable=True),
        sa.Column("reject_note", sa.Text(), nullable=True),
        sa.Column("locked_at", UTCDateTime(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "selected_by IS NULL OR selected_by IN ('auto', 'owner')",
            name=op.f(f"ck_{_TAKE}_selected_by_valid"),
        ),
        sa.CheckConstraint(
            "locked_at IS NULL OR selected_at IS NOT NULL",
            name=op.f(f"ck_{_TAKE}_lock_needs_selection"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TAKE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["music_plan.id"],
            name=op.f(f"fk_{_TAKE}_plan_id_music_plan"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cue_row_id"],
            ["music_cue.id"],
            name=op.f(f"fk_{_TAKE}_cue_row_id_music_cue"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_id"],
            [f"{_TAKE}.id"],
            name=op.f(f"fk_{_TAKE}_retry_of_id_{_TAKE}"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lab_run_id"],
            ["lab_music_run.id"],
            name=op.f(f"fk_{_TAKE}_lab_run_id_lab_music_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TAKE}")),
    )
    with op.batch_alter_table(_TAKE, schema=None) as batch_op:
        batch_op.create_index("idx_music_take_item", ["plan_id", "cue_id", "item_id"], unique=False)
        batch_op.create_index("idx_music_take_run", ["lab_run_id"], unique=False)
        batch_op.create_index("idx_music_take_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every take is deleted (the audio stays in the Music lab), and so is
    every job of the new type (the old `job.type` CHECK would refuse them).
    """
    with op.batch_alter_table(_TAKE, schema=None) as batch_op:
        batch_op.drop_index("idx_music_take_project")
        batch_op.drop_index("idx_music_take_run")
        batch_op.drop_index("idx_music_take_item")
    op.drop_table(_TAKE)

    op.execute("DELETE FROM job WHERE type = 'rewrite_music_prompt'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
