"""environment library

PHASE-012. The Character lab gets a library of environments (places): a head row, immutable
profile versions, and the attempts that make each version's canonical reference picture.

- `library_environment`: the editable head (name, description, era, atmosphere, notes).
- `library_environment_version`: one immutable snapshot of the profile per version, plus the
  canonical picture (`reference_image_id`, a `lab_image`) the author chose for it.
- `environment_reference`: one attempt to make a version's picture (a prompt job, then
  candidates). `environment_reference_candidate` links it to the four `lab_run`s.
- `job`: its `type` CHECK gains `write_environment_prompt`. `job` is rebuilt (SQLite cannot
  change a CHECK in place), the same way revisions 0028, 0030 and 0031 did. The migration
  connection runs with foreign keys off (see `env.py`), so rebuilding it cannot fire an ON
  DELETE rule. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-20 23:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
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
)
_PROMPT_JOB_TYPE = "write_environment_prompt"

_CURRENT_TIMESTAMP = sa.text("(CURRENT_TIMESTAMP)")


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_PROMPT_JOB_TYPE,))

    op.create_table(
        "library_environment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), server_default=_CURRENT_TIMESTAMP, nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=_CURRENT_TIMESTAMP, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("era_kind", sa.Text(), server_default=sa.text("'present'"), nullable=False),
        sa.Column("era_years", sa.Integer(), nullable=True),
        sa.Column("era_setting", sa.Text(), nullable=True),
        sa.Column("atmosphere", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "era_kind IN ('present', 'past', 'future')",
            name=op.f("ck_library_environment_era_kind_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_environment")),
    )
    with op.batch_alter_table("library_environment", schema=None) as batch_op:
        batch_op.create_index("idx_library_environment_created", ["created_at"], unique=False)

    op.create_table(
        "library_environment_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("created_at", UTCDateTime(), server_default=_CURRENT_TIMESTAMP, nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("reference_image_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')",
            name=op.f("ck_library_environment_version_source_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["library_environment.id"],
            name=op.f("fk_library_environment_version_environment_id_library_environment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reference_image_id"],
            ["lab_image.id"],
            name=op.f("fk_library_environment_version_reference_image_id_lab_image"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_environment_version")),
        sa.UniqueConstraint(
            "environment_id",
            "version",
            name=op.f("uq_library_environment_version_environment_id"),
        ),
    )
    with op.batch_alter_table("library_environment_version", schema=None) as batch_op:
        batch_op.create_index(
            "idx_library_environment_version_environment", ["environment_id"], unique=False
        )

    op.create_table(
        "environment_reference",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), server_default=_CURRENT_TIMESTAMP, nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'writing_prompt'"), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('writing_prompt', 'ready', 'failed')",
            name=op.f("ck_environment_reference_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["library_environment.id"],
            name=op.f("fk_environment_reference_environment_id_library_environment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["library_environment_version.id"],
            name=op.f("fk_environment_reference_version_id_library_environment_version"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f("fk_environment_reference_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_environment_reference")),
    )
    with op.batch_alter_table("environment_reference", schema=None) as batch_op:
        batch_op.create_index(
            "idx_environment_reference_environment", ["environment_id"], unique=False
        )

    op.create_table(
        "environment_reference_candidate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), server_default=_CURRENT_TIMESTAMP, nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["environment_reference.id"],
            name=op.f("fk_environment_reference_candidate_reference_id_environment_reference"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lab_run_id"],
            ["lab_run.id"],
            name=op.f("fk_environment_reference_candidate_lab_run_id_lab_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_environment_reference_candidate")),
    )
    with op.batch_alter_table("environment_reference_candidate", schema=None) as batch_op:
        batch_op.create_index(
            "idx_environment_reference_candidate_reference", ["reference_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema. Every environment, version, attempt and candidate row is dropped (the
    pictures stay in the lab's image history), and every `write_environment_prompt` job row is
    deleted (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table("environment_reference_candidate", schema=None) as batch_op:
        batch_op.drop_index("idx_environment_reference_candidate_reference")
    op.drop_table("environment_reference_candidate")

    with op.batch_alter_table("environment_reference", schema=None) as batch_op:
        batch_op.drop_index("idx_environment_reference_environment")
    op.drop_table("environment_reference")

    with op.batch_alter_table("library_environment_version", schema=None) as batch_op:
        batch_op.drop_index("idx_library_environment_version_environment")
    op.drop_table("library_environment_version")

    with op.batch_alter_table("library_environment", schema=None) as batch_op:
        batch_op.drop_index("idx_library_environment_created")
    op.drop_table("library_environment")

    op.execute("DELETE FROM job WHERE type = 'write_environment_prompt'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
