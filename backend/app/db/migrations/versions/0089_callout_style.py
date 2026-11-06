"""callout style

CMO-002. The foundation of the motion callouts of an explainer
(`Callouts_motion_implementation_phases.md`). This one migration creates every column, table and
job type the whole plan needs, so the later phases add no migration.

- `project.callout_style`: `boxes` (callouts are drawn as text boxes, as always) or `motion`
  (each callout is a small animated graphic). NOT NULL, default `boxes`, so every project that
  exists reads `boxes`.
- `callout_look`: one version of a project's callout look. A stored row is never changed.
- `callout_graphic`: one attempt of one engine (`generated_component` or `remotion_blocks`) for
  one callout: its input, its jobs, its preview and whether the component failed outright.
- `callout_graphic_choice`: the owner's choice of the version a callout uses.
- `job`: its `type` CHECK gains `write_callout_look`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0086 did. No row is changed.

No data needs preserving, so nothing is backfilled. The downgrade drops the tables and the column
and deletes the `write_callout_look` jobs.

Revision ID: 0089
Revises: 0088
Create Date: 2026-11-06 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0089"
down_revision: str | Sequence[str] | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOOK = "callout_look"
_GRAPHIC = "callout_graphic"
_CHOICE = "callout_graphic_choice"

_STYLE_CHECK = "ck_project_callout_style_valid"
_ENGINES = "'generated_component', 'remotion_blocks'"

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
    "write_lab_graphic_brief",
    "write_lab_graphic_template_spec",
    "write_lab_graphic_block_scene",
    "write_lab_graphic_component",
    "render_lab_graphic",
    "time_lab_graphic_words",
    "write_graphic_theme",
    "write_shot_graphic_brief",
    "write_shot_graphic_component",
    "write_shot_graphic_scene",
    "render_shot_graphic",
    "describe_photo",
    "render_scene",
    "write_thumbnail_concepts",
)
_NEW_JOB_TYPES = ("write_callout_look",)


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


def _project_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["project_id"],
        ["project.id"],
        name=op.f(f"fk_{table}_project_id_project"),
        ondelete="CASCADE",
    )


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

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("callout_style", sa.Text(), server_default=sa.text("'boxes'"), nullable=False)
        )
        batch_op.create_check_constraint(op.f(_STYLE_CHECK), "callout_style IN ('boxes', 'motion')")

    op.create_table(
        _LOOK,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint("source IN ('ai')", name=op.f(f"ck_{_LOOK}_source_valid")),
        _project_fk(_LOOK),
        _job_fk(_LOOK, "job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_LOOK}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_LOOK}_project_id")),
    )
    with op.batch_alter_table(_LOOK, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_LOOK}_project", ["project_id"], unique=False)

    op.create_table(
        _GRAPHIC,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("callout_id", sa.Text(), nullable=False),
        sa.Column("match_key", sa.Text(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("repair_of", sa.Integer(), nullable=True),
        sa.Column("input", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("input_job_id", sa.Integer(), nullable=True),
        sa.Column("preview_job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("preview_path", sa.Text(), nullable=True),
        sa.Column("metrics", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("warnings", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failed_outright", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        _created_at(),
        sa.CheckConstraint(f"engine IN ({_ENGINES})", name=op.f(f"ck_{_GRAPHIC}_engine_valid")),
        _project_fk(_GRAPHIC),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["callout_plan.id"],
            name=op.f(f"fk_{_GRAPHIC}_plan_id_callout_plan"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["repair_of"],
            [f"{_GRAPHIC}.id"],
            name=op.f(f"fk_{_GRAPHIC}_repair_of_{_GRAPHIC}"),
            ondelete="SET NULL",
        ),
        _job_fk(_GRAPHIC, "input_job_id"),
        _job_fk(_GRAPHIC, "preview_job_id"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_GRAPHIC}")),
        sa.UniqueConstraint(
            "project_id", "match_key", "engine", "attempt", name=op.f(f"uq_{_GRAPHIC}_project_id")
        ),
    )
    with op.batch_alter_table(_GRAPHIC, schema=None) as batch_op:
        batch_op.create_index(
            f"idx_{_GRAPHIC}_project_key_engine", ["project_id", "match_key", "engine"]
        )

    op.create_table(
        _CHOICE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("match_key", sa.Text(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        _created_at(),
        sa.CheckConstraint(f"engine IN ({_ENGINES})", name=op.f(f"ck_{_CHOICE}_engine_valid")),
        _project_fk(_CHOICE),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_CHOICE}")),
        sa.UniqueConstraint("project_id", "match_key", name=op.f(f"uq_{_CHOICE}_project_id")),
    )


def downgrade() -> None:
    """Downgrade schema. Every callout look and graphic row, and every `write_callout_look` job
    row, is deleted (the old `job.type` CHECK would refuse the jobs).
    """
    op.drop_table(_CHOICE)

    with op.batch_alter_table(_GRAPHIC, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_GRAPHIC}_project_key_engine")
    op.drop_table(_GRAPHIC)

    with op.batch_alter_table(_LOOK, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_LOOK}_project")
    op.drop_table(_LOOK)

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_STYLE_CHECK), type_="check")
        batch_op.drop_column("callout_style")

    new_types = ", ".join(f"'{name}'" for name in _NEW_JOB_TYPES)
    op.execute(f"DELETE FROM job WHERE type IN ({new_types})")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
