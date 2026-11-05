"""thumbnails

The optional thumbnail flow: a vision model writes four thumbnail concepts, the owner reviews
them, and each approved concept becomes one picture with the headline drawn on it.

- `job`: its `type` CHECK gains `write_thumbnail_concepts` (a language-model job). `job` is
  rebuilt (SQLite cannot change a CHECK in place), the same way revision 0085 did. No row is
  changed.
- `thumbnail_concepts`: one row per version of the concepts, written by the model (`ai`) or saved
  by the owner (`manual`). A stored row is never changed. `inputs` holds what the version was
  written from (the Story Bible and the render), so whether it is out of date is worked out on
  read.
- `thumbnails`: one row per picture made from one concept of one version. `lab_run_id` is the
  Image lab run that makes the picture, `background_image_id` the picture it made, and `path`
  the finished PNG (picture plus headline) under the project's media folder.

No data needs preserving, so nothing is backfilled.

Revision ID: 0086
Revises: 0085
Create Date: 2026-11-05 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0086"
down_revision: str | Sequence[str] | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONCEPTS = "thumbnail_concepts"
_THUMBNAILS = "thumbnails"

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
)
_NEW_JOB_TYPES = ("write_thumbnail_concepts",)


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
        _CONCEPTS,
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
        sa.CheckConstraint("source IN ('ai', 'manual')", name=op.f(f"ck_{_CONCEPTS}_source_valid")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_CONCEPTS}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_CONCEPTS}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_CONCEPTS}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_CONCEPTS}_project_id")),
    )
    with op.batch_alter_table(_CONCEPTS, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_CONCEPTS}_project", ["project_id"])

    op.create_table(
        _THUMBNAILS,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("concept_version", sa.Integer(), nullable=False),
        sa.Column("concept_index", sa.Integer(), nullable=False),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.Column("background_image_id", sa.Integer(), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("text_area", sa.Text(), nullable=False),
        sa.Column("chosen", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_THUMBNAILS}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lab_run_id"],
            ["lab_run.id"],
            name=op.f(f"fk_{_THUMBNAILS}_lab_run_id_lab_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["background_image_id"],
            ["lab_image.id"],
            name=op.f(f"fk_{_THUMBNAILS}_background_image_id_lab_image"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_THUMBNAILS}")),
    )
    with op.batch_alter_table(_THUMBNAILS, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_THUMBNAILS}_project", ["project_id"])
        batch_op.create_index(f"idx_{_THUMBNAILS}_lab_run", ["lab_run_id"])


def downgrade() -> None:
    """Downgrade schema. Every thumbnail, every concept version and every
    `write_thumbnail_concepts` job row is deleted (the old `job.type` CHECK would refuse the
    jobs). Stored picture files are never deleted.
    """
    with op.batch_alter_table(_THUMBNAILS, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_THUMBNAILS}_lab_run")
        batch_op.drop_index(f"idx_{_THUMBNAILS}_project")
    op.drop_table(_THUMBNAILS)
    with op.batch_alter_table(_CONCEPTS, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_CONCEPTS}_project")
    op.drop_table(_CONCEPTS)
    op.execute("DELETE FROM job WHERE type = 'write_thumbnail_concepts'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
