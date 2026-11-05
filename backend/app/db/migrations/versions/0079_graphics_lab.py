"""graphics lab

GFX-002. The foundation of the Graphics lab (`Graphics_lab_implementation_phases.md`): a line of
an explainer script is turned into one graphic by four engines, and the four videos are compared.
This one migration creates every table, column and job type the whole lab needs, so the later
phases add no migration.

- `lab_graphic_run`: one row per line the owner typed (the line, the orientation, the optional
  voice and its speech, the timing of the words, the brief and its resolved form). Belongs to no
  project.
- `lab_graphic_render`: one row per attempt of one engine for a run (its input, the jobs that
  wrote and rendered it, the stored video, the metrics, the warnings and the owner's verdict).
  Deleted with its run.
- `job`: its `type` CHECK gains `write_lab_graphic_brief`, `write_lab_graphic_template_spec`,
  `write_lab_graphic_block_scene`, `write_lab_graphic_component`, `render_lab_graphic` and
  `time_lab_graphic_words`. `job` is rebuilt (SQLite cannot change a CHECK in place), the same
  way revision 0075 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0079
Revises: 0078
Create Date: 2026-11-02 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0079"
down_revision: str | Sequence[str] | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN = "lab_graphic_run"
_RENDER = "lab_graphic_render"

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
    "rewrite_music_prompt",
    "place_music",
    "preview_music_mix",
    "time_speech_words",
    "write_callout_plan",
    "time_lab_speech_words",
    "render_av_test",
)
_NEW_JOB_TYPES = (
    "write_lab_graphic_brief",
    "write_lab_graphic_template_spec",
    "write_lab_graphic_block_scene",
    "write_lab_graphic_component",
    "render_lab_graphic",
    "time_lab_graphic_words",
)


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def _job_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        ["job.id"],
        name=op.f(f"fk_{table}_{column}_job"),
        ondelete="SET NULL",
    )


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _NEW_JOB_TYPES)

    op.create_table(
        _RUN,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("line_text", sa.Text(), nullable=False),
        sa.Column("orientation", sa.Text(), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("speech_run_id", sa.Integer(), nullable=True),
        sa.Column("timing_job_id", sa.Integer(), nullable=True),
        sa.Column("timing", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("brief_job_id", sa.Integer(), nullable=True),
        sa.Column("brief", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("resolved", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("trial_case_key", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "orientation IN ('landscape', 'portrait')",
            name=op.f(f"ck_{_RUN}_orientation_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f(f"fk_{_RUN}_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["speech_run_id"],
            ["lab_voice_run.id"],
            name=op.f(f"fk_{_RUN}_speech_run_id_lab_voice_run"),
            ondelete="SET NULL",
        ),
        _job_fk(_RUN, "timing_job_id"),
        _job_fk(_RUN, "brief_job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_RUN}")),
    )
    with op.batch_alter_table(_RUN, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_RUN}_created", ["created_at"], unique=False)
        batch_op.create_index(f"idx_{_RUN}_trial_case", ["trial_case_key"], unique=False)

    op.create_table(
        _RENDER,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_job_id", sa.Integer(), nullable=True),
        sa.Column("input", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("repeat_of", sa.Integer(), nullable=True),
        sa.Column("render_job_id", sa.Integer(), nullable=True),
        sa.Column("media_path", sa.Text(), nullable=True),
        sa.Column("metrics", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("warnings", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "engine IN ('remotion_templates', 'python_templates', 'remotion_blocks', "
            "'generated_component')",
            name=op.f(f"ck_{_RENDER}_engine_valid"),
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('good', 'usable', 'bad')",
            name=op.f(f"ck_{_RENDER}_verdict_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            [f"{_RUN}.id"],
            name=op.f(f"fk_{_RENDER}_run_id_{_RUN}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repeat_of"],
            [f"{_RENDER}.id"],
            name=op.f(f"fk_{_RENDER}_repeat_of_{_RENDER}"),
            ondelete="SET NULL",
        ),
        _job_fk(_RENDER, "input_job_id"),
        _job_fk(_RENDER, "render_job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_RENDER}")),
        sa.UniqueConstraint("run_id", "engine", "attempt", name=op.f(f"uq_{_RENDER}_run_id")),
    )
    with op.batch_alter_table(_RENDER, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_RENDER}_run_engine", ["run_id", "engine"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every run and render row, and every job row of the six Graphics lab
    types, is deleted (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table(_RENDER, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_RENDER}_run_engine")
    op.drop_table(_RENDER)
    with op.batch_alter_table(_RUN, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_RUN}_trial_case")
        batch_op.drop_index(f"idx_{_RUN}_created")
    op.drop_table(_RUN)
    new_types = ", ".join(f"'{name}'" for name in _NEW_JOB_TYPES)
    op.execute(f"DELETE FROM job WHERE type IN ({new_types})")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
