"""technical validation of shot takes

PHASE-029. Every generated take of a shot is checked in code (it decodes, it has sound, its size
and frame count are what was asked, it is long enough). The result is stored on the take.

- `job`: its `type` CHECK gains `check_shot_takes`, the local job that checks the takes made
  before this revision. `job` is rebuilt (SQLite cannot change a CHECK in place), the same way
  revisions 0028 to 0048 did. No row is changed.
- `shot_take`: one nullable JSON column, `validation`. NULL means the take has not been checked;
  a take that is not checked is never selected by itself and never rendered.

No data needs preserving, so nothing is backfilled: a take made before this revision stays
"not checked" until the owner presses **Check takes**.

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-22 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "shot_take"

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
)
_CHECK_JOB_TYPE = "check_shot_takes"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_CHECK_JOB_TYPE,))
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("validation", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema. Every `check_shot_takes` job row is deleted (the old `job.type` CHECK
    would refuse them), and the stored checks of the takes are dropped. No clip file is touched.
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_column("validation")
    op.execute("DELETE FROM job WHERE type = 'check_shot_takes'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
