"""shot reference manifests

PHASE-024. The reference manifest of a shot (the pictures it is generated from) gets a table. It
is made by deterministic code in the request that asks for it, so there is no new job type and
the `job.type` CHECK is not changed.

- `shot_reference_manifest`: one row per selection for one shot, that is, one version of that
  shot's manifest. It follows the artifact provenance convention (DATABASE_STRUCTURE.md
  Section 2.1): `source`, `job_id`, `version`, `inputs` and `created_at`, plus `project_id`, the
  scene's slug `scene_id`, the shot's id `shot_id`, the id of the `shot_definition` row the
  manifest was selected for, and the manifest itself (`content`). A shot's manifests are numbered
  from 1 (`UNIQUE (project_id, scene_id, shot_id, version)`), and a stored row is never changed.
  `inputs` records the artifacts the selection was made from (the shot definition, the look and
  state resolution, and the pinned definitions of the characters and the environment).

No data needs preserving, so nothing is backfilled.

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-21 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0043"
down_revision: str | Sequence[str] | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "shot_reference_manifest"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("shot_id", sa.Text(), nullable=False),
        sa.Column("shot_definition_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('ai', 'manual')", name=op.f(f"ck_{_TABLE}_source_valid")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shot_definition_id"],
            ["shot_definition.id"],
            name=op.f(f"fk_{_TABLE}_shot_definition_id_shot_definition"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TABLE}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint(
            "project_id",
            "scene_id",
            "shot_id",
            "version",
            name=op.f(f"uq_{_TABLE}_project_id"),
        ),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            f"idx_{_TABLE}_project_scene", ["project_id", "scene_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema. Every reference manifest is deleted."""
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TABLE}_project_scene")
    op.drop_table(_TABLE)
