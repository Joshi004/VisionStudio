"""story voices

PHASE-011. A story project can have the pipeline make a saved voice for each defined character
and for the narrator, by itself: a language model writes the voice's description, one
design-mode sample is made, and the sample is saved as a voice.

- `job`: its `type` CHECK gains `design_voice`. `job` is rebuilt (SQLite cannot change a CHECK
  in place), the same way revisions 0028 and 0030 did. The migration connection runs with
  foreign keys off (see `env.py`), so rebuilding it cannot fire an ON DELETE rule. No row is
  changed.
- `lab_voice_run`: gains the nullable `project_id` (FK to `project`, set null when the project
  is deleted, indexed), `subject` (`character` or `narrator`), `discovery_id` (the slug of the
  discovered character, for a character), `design_job_id` (the `design_voice` job that wrote
  the description, FK to `job`, set null) and `inputs` (JSON, the D-3 provenance of the voice).
  A run made by hand in the Voice lab or the Character Lab has none of the five.
- `narrator_voice`: a new table of the shape of `story_bible` (D-3): every derivation or choice
  is a new row with the next `version`, and a stored row is never changed. `voice_id` is the
  saved voice and `inputs` records the StoryBible version and a hash of the narration style and
  tone it was derived from.

No data needs preserving, so nothing is backfilled.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-20 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
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
)
_VOICE_JOB_TYPE = "design_voice"
_RUN_TABLE = "lab_voice_run"
_RUN_INDEX = "idx_lab_voice_run_project"
_RUN_PROJECT_FK = "fk_lab_voice_run_project_id_project"
_RUN_JOB_FK = "fk_lab_voice_run_design_job_id_job"
_RUN_SUBJECT_CHECK = "ck_lab_voice_run_subject_valid"
_NARRATOR_TABLE = "narrator_voice"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_VOICE_JOB_TYPE,))

    with op.batch_alter_table(_RUN_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("subject", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("discovery_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("design_job_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("inputs", sa.JSON(), nullable=True))
        batch_op.create_check_constraint(
            op.f(_RUN_SUBJECT_CHECK), "subject IS NULL OR subject IN ('character', 'narrator')"
        )
        batch_op.create_foreign_key(
            batch_op.f(_RUN_PROJECT_FK), "project", ["project_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            batch_op.f(_RUN_JOB_FK), "job", ["design_job_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index(_RUN_INDEX, ["project_id"], unique=False)

    op.create_table(
        _NARRATOR_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name=op.f(f"ck_{_NARRATOR_TABLE}_source_valid")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_NARRATOR_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f(f"fk_{_NARRATOR_TABLE}_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_NARRATOR_TABLE}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_NARRATOR_TABLE}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_NARRATOR_TABLE}_project_id")),
    )
    with op.batch_alter_table(_NARRATOR_TABLE, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_NARRATOR_TABLE}_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every narrator voice row is dropped, the runs the pipeline made stay
    (they only lose the mark of what they were made for), and every `design_voice` job row is
    deleted (the old `job.type` CHECK would refuse the jobs). The saved voices stay.
    """
    with op.batch_alter_table(_NARRATOR_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_NARRATOR_TABLE}_project")
    op.drop_table(_NARRATOR_TABLE)

    with op.batch_alter_table(_RUN_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_RUN_INDEX)
        batch_op.drop_constraint(batch_op.f(_RUN_JOB_FK), type_="foreignkey")
        batch_op.drop_constraint(batch_op.f(_RUN_PROJECT_FK), type_="foreignkey")
        batch_op.drop_constraint(batch_op.f(_RUN_SUBJECT_CHECK), type_="check")
        batch_op.drop_column("inputs")
        batch_op.drop_column("design_job_id")
        batch_op.drop_column("discovery_id")
        batch_op.drop_column("subject")
        batch_op.drop_column("project_id")

    op.execute("DELETE FROM job WHERE type = 'design_voice'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
