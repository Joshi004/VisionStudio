"""environment definitions and project links

PHASE-013. A story project's discovered environments are backed by library environments, the
project pins one version of each, and the pipeline defines each one and makes its canonical
picture by itself.

- `project_environment_link`: one row per linked discovered environment, the same shape as
  `project_character_link` (revision 0027). It names the project, the discovered environment by
  its slug (`discovery_id`), the library environment and the **pinned version** (a plain number:
  a version row is found by `(environment_id, pinned_version)`). `how` is `created` or `mapped`.
  `UNIQUE (project_id, discovery_id)` and `UNIQUE (project_id, environment_id)`.
- `library_environment`: gains `origin_project_id` (FK to `project`, set null) and
  `origin_discovery_id`, which mark an environment the pipeline created for a project, and the
  nullable JSON `definition` (the newest structured definition, `Path_ahead.md` Section 13).
- `library_environment_version`: gains `definition`, `job_id` (FK to `job`, set null) and
  `inputs` (JSON), the D-3 provenance of a version the pipeline wrote.
- `environment_reference`: gains `project_id` (FK to `project`, set null, indexed) and
  `discovery_id`. A non-null `project_id` marks an attempt the pipeline made for a project: it
  makes one candidate and takes it as the picture by itself.
- `job`: its `type` CHECK gains `define_environment`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revisions 0028, 0030, 0031 and 0032 did. The migration
  connection runs with foreign keys off (see `env.py`), so rebuilding it cannot fire an ON
  DELETE rule. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-21 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
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
)
_DEFINE_JOB_TYPE = "define_environment"

_LINK_TABLE = "project_environment_link"
_LINK_INDEX = "idx_project_environment_link_environment"
_ENVIRONMENT_TABLE = "library_environment"
_ORIGIN_FK = "fk_library_environment_origin_project_id_project"
_VERSION_TABLE = "library_environment_version"
_VERSION_JOB_FK = "fk_library_environment_version_job_id_job"
_REFERENCE_TABLE = "environment_reference"
_REFERENCE_INDEX = "idx_environment_reference_project"
_REFERENCE_PROJECT_FK = "fk_environment_reference_project_id_project"


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

    op.create_table(
        _LINK_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("discovery_id", sa.Text(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("pinned_version", sa.Integer(), nullable=False),
        sa.Column("how", sa.Text(), nullable=False),
        sa.Column("discovery_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "how IN ('created', 'mapped')", name=op.f(f"ck_{_LINK_TABLE}_how_valid")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_LINK_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["library_environment.id"],
            name=op.f(f"fk_{_LINK_TABLE}_environment_id_library_environment"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_LINK_TABLE}")),
        sa.UniqueConstraint("project_id", "discovery_id", name=op.f(f"uq_{_LINK_TABLE}_discovery")),
        sa.UniqueConstraint(
            "project_id", "environment_id", name=op.f(f"uq_{_LINK_TABLE}_environment")
        ),
    )
    with op.batch_alter_table(_LINK_TABLE, schema=None) as batch_op:
        batch_op.create_index(_LINK_INDEX, ["environment_id"], unique=False)

    with op.batch_alter_table(_ENVIRONMENT_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("origin_project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("origin_discovery_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("definition", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_ORIGIN_FK),
            "project",
            ["origin_project_id"],
            ["id"],
            ondelete="SET NULL",
        )

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

    with op.batch_alter_table(_REFERENCE_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("discovery_id", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_REFERENCE_PROJECT_FK),
            "project",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(_REFERENCE_INDEX, ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every link is deleted; the library environments the pipeline created
    stay in the library and only lose the mark of where they came from, and every definition is
    dropped (the profile text the definitions were mapped into stays). Every `define_environment`
    job row is deleted (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table(_REFERENCE_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_REFERENCE_INDEX)
        batch_op.drop_constraint(batch_op.f(_REFERENCE_PROJECT_FK), type_="foreignkey")
        batch_op.drop_column("discovery_id")
        batch_op.drop_column("project_id")

    with op.batch_alter_table(_VERSION_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_VERSION_JOB_FK), type_="foreignkey")
        batch_op.drop_column("inputs")
        batch_op.drop_column("job_id")
        batch_op.drop_column("definition")

    with op.batch_alter_table(_ENVIRONMENT_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_ORIGIN_FK), type_="foreignkey")
        batch_op.drop_column("definition")
        batch_op.drop_column("origin_discovery_id")
        batch_op.drop_column("origin_project_id")

    with op.batch_alter_table(_LINK_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_LINK_INDEX)
    op.drop_table(_LINK_TABLE)

    op.execute("DELETE FROM job WHERE type = 'define_environment'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
