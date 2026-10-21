"""repair of a cut between two shots

PHASE-023 (revision). The continuity check no longer defines one shot again for a mismatch. It
repairs the **cut** with one call that sees both shots, and that call is a new job type.

- `job`: its `type` CHECK gains `repair_shot_cut`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revisions 0028 to 0042 did. No row is changed.

No table is added: the repair stores new versions of `shot_definition`, whose `inputs` record
the check, the round and the cut (`inputs.continuity`). No data needs preserving, so nothing is
backfilled.

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-22 00:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0045"
down_revision: str | Sequence[str] | None = "0044"
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
)
_REPAIR_JOB_TYPE = "repair_shot_cut"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_REPAIR_JOB_TYPE,))


def downgrade() -> None:
    """Downgrade schema. Every `repair_shot_cut` job row is deleted (the old `job.type` CHECK
    would refuse the jobs). The shot definitions the repairs made stay.
    """
    op.execute("DELETE FROM job WHERE type = 'repair_shot_cut'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
