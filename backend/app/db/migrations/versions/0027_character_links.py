"""character links

PHASE-008. A story project's discovered characters are backed by library characters, and the
project pins one version of each.

- `project_character_link`: one row per linked discovered character. It names the project, the
  discovered character by its slug (`discovery_id`, the `id` inside `character_discovery`
  content), the library character and the **pinned version** (a plain number: a version row is
  found by `(character_id, pinned_version)`, as `character_take.character_version` does). A
  pin never moves because of a lab edit. `how` is `created` (the pipeline made the library
  character from the discovery entry) or `mapped` (the user chose an existing one).
  `discovery_version` is the version of the discovered list the link was made from (provenance).
  A project links a discovered character once, and a library character to at most one
  discovered character (`UNIQUE (project_id, discovery_id)` and
  `UNIQUE (project_id, character_id)`).
- `library_character`: gains the nullable `origin_project_id` and `origin_discovery_id`, which
  mark a character the pipeline created for a project.

No data needs preserving, so nothing is backfilled.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-20 20:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "project_character_link"
_INDEX = "idx_project_character_link_character"
_ORIGIN_FK = "fk_library_character_origin_project_id_project"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("discovery_id", sa.Text(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("how IN ('created', 'mapped')", name=op.f(f"ck_{_TABLE}_how_valid")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["library_character.id"],
            name=op.f(f"fk_{_TABLE}_character_id_library_character"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint("project_id", "discovery_id", name=op.f(f"uq_{_TABLE}_discovery")),
        sa.UniqueConstraint("project_id", "character_id", name=op.f(f"uq_{_TABLE}_character")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(_INDEX, ["character_id"], unique=False)

    with op.batch_alter_table("library_character", schema=None) as batch_op:
        batch_op.add_column(sa.Column("origin_project_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("origin_discovery_id", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_ORIGIN_FK),
            "project",
            ["origin_project_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema. Every link is deleted; the library characters the pipeline created
    stay in the library and only lose the mark of where they came from.
    """
    with op.batch_alter_table("library_character", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_ORIGIN_FK), type_="foreignkey")
        batch_op.drop_column("origin_discovery_id")
        batch_op.drop_column("origin_project_id")

    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(_INDEX)
    op.drop_table(_TABLE)
