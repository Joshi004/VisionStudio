"""character definitions

PHASE-009. The Character Definition stage writes one structured definition per story character
(`Path_ahead.md` Section 11) and stores it on the library character, as a new version.

- `library_character`: gains the nullable `definition` (JSON), the newest structured definition
  the pipeline wrote for the character. It is the editable head's copy: a lab edit of the
  profile never changes it, so it stays as the record of what the model wrote.
- `library_character_version`: gains the nullable `definition` (JSON, the head's definition as
  it was at that version), and the provenance of a version the pipeline made: `job_id` (the job
  that wrote it, set null when the job is deleted) and `inputs` (JSON, what the definition was
  built from: the project, the discovered character, the story hash, the StoryBible version).
  A version made by hand in the lab has no `job_id` and no `inputs`.
- `job`: its `type` CHECK gains `define_character`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revisions 0016, 0022, 0023, 0024 and 0025 did. The migration
  connection runs with foreign keys off (see `env.py`), so rebuilding it cannot fire an
  ON DELETE rule. No row is changed.

No data needs preserving, so nothing is backfilled: a character or version made before this
revision has no definition.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-20 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
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
)
_DEFINE_JOB_TYPE = "define_character"
_VERSION_TABLE = "library_character_version"
_VERSION_JOB_FK = "fk_library_character_version_job_id_job"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_DEFINE_JOB_TYPE,))

    with op.batch_alter_table("library_character", schema=None) as batch_op:
        batch_op.add_column(sa.Column("definition", sa.JSON(), nullable=True))

    with op.batch_alter_table(_VERSION_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("definition", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("job_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("inputs", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_VERSION_JOB_FK),
            "job",
            ["job_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema. Every definition is dropped (the library characters keep the profile
    text the definitions were mapped into), and every `define_character` job row is deleted
    (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table(_VERSION_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_VERSION_JOB_FK), type_="foreignkey")
        batch_op.drop_column("inputs")
        batch_op.drop_column("job_id")
        batch_op.drop_column("definition")

    with op.batch_alter_table("library_character", schema=None) as batch_op:
        batch_op.drop_column("definition")

    op.execute("DELETE FROM job WHERE type = 'define_character'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
