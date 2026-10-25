"""render with music

MUSIC-012. The final render takes the music placement, and a preview of the mix can be made.

- `project.ambience_enabled`: a render-time switch for the beds and the sounds Stable Audio makes
  for points in the music (MD-21). On for every project, existing ones included. It only matters
  while `project.music_enabled` is on, and it changes the render, not the placement.
- `job`: its `type` CHECK gains `preview_music_mix`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0070 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0071
Revises: 0070
Create Date: 2026-10-26 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0071"
down_revision: str | Sequence[str] | None = "0070"
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
    "rewrite_music_prompt",
    "place_music",
)
_NEW_JOB_TYPES = ("preview_music_mix",)


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
            sa.Column("ambience_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1"))
        )


def downgrade() -> None:
    """Downgrade schema. Every job of the new type is deleted (the old `job.type` CHECK would
    refuse them).
    """
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("ambience_enabled")
    op.execute("DELETE FROM job WHERE type = 'preview_music_mix'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
