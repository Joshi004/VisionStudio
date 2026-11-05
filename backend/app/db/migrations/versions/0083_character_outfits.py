"""character outfits

A character's named looks become the outfits an author manages in the Character Lab.

- `character_named_look.note`: a short text (at most 120 characters) that helps pick the outfit
  when a project is made. NULL when there is none.
- `character_named_look.deleted_at`: set when the author deletes the outfit. The row stays, so
  the old resolutions and the pinned character versions that point at it still read, and its
  slug is never given to a different outfit. NULL for an outfit that is in use.
- `character_named_look.updated_at`: when the author last edited the outfit. NULL until then.
- `project.presenter_named_look_id`: the saved outfit an explainer's presenter wears in every
  scene (FK to `character_named_look`, set null). NULL means the typed `presenter_outfit` text
  or the default outfit. Only an explainer has it.
- `job`: its `type` CHECK gains `describe_photo` (a paid call that reads a reference photo and
  returns text for a character's or an outfit's form). `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0080 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0083
Revises: 0082
Create Date: 2026-11-04 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0083"
down_revision: str | Sequence[str] | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECT_FK = "fk_project_presenter_named_look_id_character_named_look"

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
)
_NEW_JOB_TYPES = ("describe_photo",)


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
    with op.batch_alter_table("character_named_look", schema=None) as batch_op:
        batch_op.add_column(sa.Column("note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column("updated_at", UTCDateTime(), nullable=True))
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("presenter_named_look_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_PROJECT_FK),
            "character_named_look",
            ["presenter_named_look_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema. Every `describe_photo` job row is deleted (the old `job.type` CHECK
    would refuse it).
    """
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_PROJECT_FK), type_="foreignkey")
        batch_op.drop_column("presenter_named_look_id")
    with op.batch_alter_table("character_named_look", schema=None) as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("note")
    new_types = ", ".join(f"'{name}'" for name in _NEW_JOB_TYPES)
    op.execute(f"DELETE FROM job WHERE type IN ({new_types})")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
