"""MiniMax H3 for a project's scenes

`project.video_model` and `scene.video_model` also accept `minimax-h3`, so MiniMax H3 can be
chosen for a project, for one scene, or as the app's default, and not only in the labs
(revisions 0017 and 0019 did the same for `lab_video_run` and `character_take`).

Both tables are rebuilt, because SQLite cannot change a CHECK in place. The migration connection
runs with foreign keys off (see `env.py`), so rebuilding them cannot fire an ON DELETE rule.
No row is changed.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-18 20:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("project", "scene")
_OLD_CHECK = "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5')"
_NEW_CHECK = "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5', 'minimax-h3')"


def _check_name(table: str) -> str:
    return f"ck_{table}_video_model_valid"


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(op.f(_check_name(table)), type_="check")
            batch_op.create_check_constraint(op.f(_check_name(table)), _NEW_CHECK)


def downgrade() -> None:
    """Downgrade schema. A project or a scene that chose MiniMax H3 goes back to "inherit"
    (NULL), because the old CHECK would refuse the value. Nothing is deleted, and the clips
    already made keep the model they were made with (their provenance names it).
    """
    for table in _TABLES:
        op.execute(f"UPDATE {table} SET video_model = NULL WHERE video_model = 'minimax-h3'")
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(op.f(_check_name(table)), type_="check")
            batch_op.create_check_constraint(op.f(_check_name(table)), _OLD_CHECK)
