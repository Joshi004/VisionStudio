"""project cast

PHASE-048. A story project can hold a "cast" of library characters and library environments the
user wants to reuse. The cast is sent to the model when the story's characters and environments
are discovered, so the model can say which discovered one is a cast member.

- `project_cast_character`: one row per library character in a project's cast, with a `mode`
  (`as_is` or `rewrite_text`). `UNIQUE (project_id, character_id)`.
- `project_cast_environment`: the same for library environments.

Both tables are new, so no data is backfilled and no existing table changes.

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-22 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHARACTER_TABLE = "project_cast_character"
_ENVIRONMENT_TABLE = "project_cast_environment"


def _create_cast_table(table: str, member_column: str, library_table: str, unique: str) -> None:
    """Makes one cast table. The names are fixed strings in this file, never input."""
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column(member_column, sa.Integer(), nullable=False),
        sa.Column("mode", sa.Text(), server_default=sa.text("'as_is'"), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN ('as_is', 'rewrite_text')", name=op.f(f"ck_{table}_mode_valid")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{table}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [member_column],
            [f"{library_table}.id"],
            name=op.f(f"fk_{table}_{member_column}_{library_table}"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("project_id", member_column, name=op.f(unique)),
    )
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.create_index(f"idx_{table}_{member_column[:-3]}", [member_column], unique=False)


def upgrade() -> None:
    """Upgrade schema."""
    _create_cast_table(
        _CHARACTER_TABLE,
        "character_id",
        "library_character",
        "uq_project_cast_character_character",
    )
    _create_cast_table(
        _ENVIRONMENT_TABLE,
        "environment_id",
        "library_environment",
        "uq_project_cast_environment_environment",
    )


def downgrade() -> None:
    """Downgrade schema. Every cast row is deleted; the library characters and environments
    themselves are not touched.
    """
    for table, member_column in (
        (_ENVIRONMENT_TABLE, "environment_id"),
        (_CHARACTER_TABLE, "character_id"),
    ):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(f"idx_{table}_{member_column[:-3]}")
        op.drop_table(table)
