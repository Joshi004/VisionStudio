"""the story pipeline job

PHASE-030. One click runs the whole story pipeline. The run is one local job, `story_pipeline`,
that keeps its progress in its own `output` and makes the jobs of every stage as they become
possible.

- `job`: its `type` CHECK gains `story_pipeline`. `job` is rebuilt (SQLite cannot change a CHECK
  in place), the same way revisions 0028 to 0049 did. No row is changed.

No table and no column is added: the run's state is the job's `input` and `output`.

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-22 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0050"
down_revision: str | Sequence[str] | None = "0049"
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
)
_PIPELINE_JOB_TYPE = "story_pipeline"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_PIPELINE_JOB_TYPE,))


def downgrade() -> None:
    """Downgrade schema. Every `story_pipeline` job row is deleted (the old `job.type` CHECK
    would refuse them). The jobs those runs made are not touched.
    """
    op.execute("DELETE FROM job WHERE type = 'story_pipeline'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
