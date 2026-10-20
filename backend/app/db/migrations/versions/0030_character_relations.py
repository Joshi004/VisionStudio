"""character relations

PHASE-047. A story project keeps a list of the relations between its discovered characters (a
younger or older self, a twin, a parent, a sibling, a grandparent), so the images stage can make
a same-person variant by editing its base character's picture, and a relative from the
relative's traits.

- `character_relations`: a new table of the shape of `character_discovery` (D-3): every run or
  edit is a new row with the next `version` and a stored row is never changed. `content` is
  `{"relations": [{"character", "kind", "of"}, ...]}`, between the slug ids of the discovered
  characters. `inputs` records the story hash and the artifacts (StoryBible, character
  discovery) the list was made from.
- `job`: its `type` CHECK gains `discover_relations`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0028 did. The migration connection runs with foreign
  keys off (see `env.py`), so rebuilding it cannot fire an ON DELETE rule. No row is changed.
- `character_look`: its `status` CHECK gains `waiting`: a look the pipeline made for a
  same-person variant, held until its base character's images are ready. The table is rebuilt
  for the same reason.

No data needs preserving, so nothing is backfilled.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-20 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
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
)
_RELATIONS_JOB_TYPE = "discover_relations"
_TABLE = "character_relations"
_LOOK_STATUS_BEFORE = "'writing_prompt', 'choosing', 'making_angles', 'ready', 'failed'"
_LOOK_STATUS_AFTER = "'waiting', " + _LOOK_STATUS_BEFORE


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def _rebuild_look_check(statuses: str) -> None:
    """`statuses` is one of the fixed lists in this file, never input."""
    with op.batch_alter_table("character_look", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_character_look_status_valid"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_character_look_status_valid"), f"status IN ({statuses})"
        )


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_RELATIONS_JOB_TYPE,))
    _rebuild_look_check(_LOOK_STATUS_AFTER)

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
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
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TABLE}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_TABLE}_project_id")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_TABLE}_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every list of relations and every `discover_relations` job row is
    deleted, and a `waiting` look is deleted (the old CHECKs would refuse them).
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TABLE}_project")
    op.drop_table(_TABLE)

    op.execute("DELETE FROM job WHERE type = 'discover_relations'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)

    op.execute("DELETE FROM character_look WHERE status = 'waiting'")
    _rebuild_look_check(_LOOK_STATUS_BEFORE)
