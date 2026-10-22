"""the job that chooses a shot's reference pictures with a language model

PHASE-033. A shot's reference manifest can now be chosen by a language model, one job per shot.

- `job`: its `type` CHECK gains `select_shot_references`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revisions 0028 to 0051 did. No row is changed.

No table changes: `shot_reference_manifest.job_id` already exists (it was always NULL until now),
and how a manifest was chosen is written in its JSON `content` (`method`, a `reason` for each
picture, and `fallback_reason`). A manifest made before this revision reads as it did: chosen by
the fixed rule.

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-22 21:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
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
)
_SELECTION_JOB_TYPE = "select_shot_references"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_SELECTION_JOB_TYPE,))


def downgrade() -> None:
    """Downgrade schema. Every `select_shot_references` job row is deleted (the old `job.type`
    CHECK would refuse them), and the manifests that point at one lose that link
    (`shot_reference_manifest.job_id` is set to NULL by its foreign key). The manifests
    themselves stay.
    """
    op.execute("DELETE FROM job WHERE type = 'select_shot_references'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
