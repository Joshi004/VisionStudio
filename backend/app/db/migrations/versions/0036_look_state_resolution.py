"""look and environment-state resolution

PHASE-016. Named looks of a library character and named states of a library environment get
their own tables, and the resolution of what a project's scenes asked for is stored as a project
artifact. A new job type runs the resolution.

- `character_named_look`: one named look of a library character ("night clothes"): `slug`,
  `name`, `description`, `source`, the project and job that created it, and `look_id`, which
  points at the `character_look` that holds its pictures and stays NULL until PHASE-017 makes
  them. `UNIQUE (character_id, slug)`; `slug` can never be `default`, which is the canonical
  look and has no row. The character's canonical look needs no row.
- `environment_state`: the same for a library environment, with `reference_image_id` (the
  state's picture, NULL until PHASE-017) instead of `look_id`.
- `look_state_resolution`: one row per run for one project, that is, one version of the
  resolution. It follows the artifact provenance convention (DATABASE_STRUCTURE.md Section 2.1):
  `source`, `job_id`, `version`, `inputs` and `created_at`, plus `project_id` and the resolved
  requests of every scene (`content`). `UNIQUE (project_id, version)`.
- `job`: its `type` CHECK gains `resolve_looks_states`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revisions 0028 to 0035 did. The migration connection runs with
  foreign keys off (see `env.py`), so rebuilding it cannot fire an ON DELETE rule. No row is
  changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-21 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
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
)
_RESOLVE_JOB_TYPE = "resolve_looks_states"
_LOOK_TABLE = "character_named_look"
_STATE_TABLE = "environment_state"
_RESOLUTION_TABLE = "look_state_resolution"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def _created_at() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "created_at",
        UTCDateTime(),
        server_default=sa.text("(CURRENT_TIMESTAMP)"),
        nullable=False,
    )


def _named_table(table: str, owner_column: str, owner_table: str, picture_column: str) -> None:
    """The shape the two named tables share. `owner_column` is the library character or
    environment, `picture_column` the column PHASE-017 fills (`look_id` or `reference_image_id`).
    """
    picture_table = "character_look" if picture_column == "look_id" else "lab_image"
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(owner_column, sa.Integer(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("origin_project_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column(picture_column, sa.Integer(), nullable=True),
        _created_at(),
        sa.CheckConstraint("source IN ('ai', 'manual')", name=op.f(f"ck_{table}_source_valid")),
        sa.CheckConstraint("slug <> 'default'", name=op.f(f"ck_{table}_slug_not_default")),
        sa.ForeignKeyConstraint(
            [owner_column],
            [f"{owner_table}.id"],
            name=op.f(f"fk_{table}_{owner_column}_{owner_table}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["origin_project_id"],
            ["project.id"],
            name=op.f(f"fk_{table}_origin_project_id_project"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{table}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            [picture_column],
            [f"{picture_table}.id"],
            name=op.f(f"fk_{table}_{picture_column}_{picture_table}"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(owner_column, "slug", name=op.f(f"uq_{table}_{owner_column}")),
    )


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_RESOLVE_JOB_TYPE,))
    _named_table(_LOOK_TABLE, "character_id", "library_character", "look_id")
    _named_table(_STATE_TABLE, "environment_id", "library_environment", "reference_image_id")
    op.create_table(
        _RESOLUTION_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name=op.f(f"ck_{_RESOLUTION_TABLE}_source_valid")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_RESOLUTION_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_RESOLUTION_TABLE}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_RESOLUTION_TABLE}")),
        sa.UniqueConstraint(
            "project_id", "version", name=op.f(f"uq_{_RESOLUTION_TABLE}_project_id")
        ),
    )
    with op.batch_alter_table(_RESOLUTION_TABLE, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_RESOLUTION_TABLE}_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every named look and state, every resolution and every
    `resolve_looks_states` job row is deleted (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table(_RESOLUTION_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_RESOLUTION_TABLE}_project")
    op.drop_table(_RESOLUTION_TABLE)
    op.drop_table(_STATE_TABLE)
    op.drop_table(_LOOK_TABLE)

    op.execute("DELETE FROM job WHERE type = 'resolve_looks_states'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
