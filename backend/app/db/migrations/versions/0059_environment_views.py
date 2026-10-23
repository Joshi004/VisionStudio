"""environment views

PHASE-052. Every environment gets views: the place seen from other directions than its master
picture, each an edit of that picture. A story project plans which views its scenes need.

- `environment_view`: a named view of a library environment (like `environment_state`):
  `slug`, `name`, `side` (relative to the master picture), `framing`, the `zone` it looks at,
  a text `description`, the written edit `prompt` and the job that wrote it, the picture
  (`reference_image_id`) with the run that made it (`lab_run_id`) and what it was made from
  (`inputs`). `UNIQUE (environment_id, slug)`; the slug can never be `establishing`, which is
  the master picture.
- `environment_view_plan`: one row per run for one discovered environment of a project, that is,
  one version of its view plan. It follows the artifact provenance convention
  (DATABASE_STRUCTURE.md Section 2.1). `UNIQUE (project_id, discovery_id, version)`.
- `library_environment_version.views`: the pictures of the views a version froze, `[]` for
  every earlier version.
- `job`: its `type` CHECK gains `plan_environment_views` and `write_environment_view_prompt`.
  `job` is rebuilt (SQLite cannot change a CHECK in place), the same way revision 0058 did. No
  row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0059"
down_revision: str | Sequence[str] | None = "0058"
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
    "resolve_looks_states",
    "synthesize_speech_unit",
    "plan_shots",
    "define_shot",
    "check_shot_continuity",
    "repair_shot_cut",
    "compile_shot_prompt",
    "generate_shot",
    "render_story",
    "check_shot_takes",
    "story_pipeline",
    "check_take_dialogue",
    "select_shot_references",
    "lab_music",
    "write_lab_music_prompt",
    "stage_scene",
)
_NEW_JOB_TYPES = ("plan_environment_views", "write_environment_view_prompt")
_VIEW_TABLE = "environment_view"
_PLAN_TABLE = "environment_view_plan"


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


def _fk(column: str, target: str, table: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete=ondelete,
    )


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _NEW_JOB_TYPES)
    op.create_table(
        _VIEW_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("framing", sa.Text(), nullable=False),
        sa.Column("zone", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("origin_project_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("reference_image_id", sa.Integer(), nullable=True),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name=op.f(f"ck_{_VIEW_TABLE}_source_valid")
        ),
        sa.CheckConstraint(
            "slug <> 'establishing'", name=op.f(f"ck_{_VIEW_TABLE}_slug_not_establishing")
        ),
        sa.CheckConstraint(
            "side IN ('ahead', 'left', 'right', 'behind')",
            name=op.f(f"ck_{_VIEW_TABLE}_side_valid"),
        ),
        sa.CheckConstraint(
            "framing IN ('wide', 'medium', 'close')", name=op.f(f"ck_{_VIEW_TABLE}_framing_valid")
        ),
        _fk("environment_id", "library_environment", _VIEW_TABLE, "CASCADE"),
        _fk("origin_project_id", "project", _VIEW_TABLE, "SET NULL"),
        _fk("job_id", "job", _VIEW_TABLE, "SET NULL"),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f(f"fk_{_VIEW_TABLE}_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        _fk("reference_image_id", "lab_image", _VIEW_TABLE, "SET NULL"),
        _fk("lab_run_id", "lab_run", _VIEW_TABLE, "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_VIEW_TABLE}")),
        sa.UniqueConstraint(
            "environment_id", "slug", name=op.f(f"uq_{_VIEW_TABLE}_environment_id")
        ),
    )
    op.create_table(
        _PLAN_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("discovery_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name=op.f(f"ck_{_PLAN_TABLE}_source_valid")
        ),
        _fk("project_id", "project", _PLAN_TABLE, "CASCADE"),
        _fk("job_id", "job", _PLAN_TABLE, "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_PLAN_TABLE}")),
        sa.UniqueConstraint(
            "project_id", "discovery_id", "version", name=op.f(f"uq_{_PLAN_TABLE}_project_id")
        ),
    )
    with op.batch_alter_table(_PLAN_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            f"idx_{_PLAN_TABLE}_project_discovery", ["project_id", "discovery_id"], unique=False
        )
    with op.batch_alter_table("library_environment_version", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("views", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )


def downgrade() -> None:
    """Downgrade schema. Every view, every view plan and every job of the two new types is
    deleted (the old `job.type` CHECK would refuse the jobs). The pictures stay in the lab's
    pictures.
    """
    with op.batch_alter_table("library_environment_version", schema=None) as batch_op:
        batch_op.drop_column("views")
    with op.batch_alter_table(_PLAN_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_PLAN_TABLE}_project_discovery")
    op.drop_table(_PLAN_TABLE)
    op.drop_table(_VIEW_TABLE)

    op.execute(
        "DELETE FROM job WHERE type IN ('plan_environment_views', 'write_environment_view_prompt')"
    )
    _rebuild_job_check(_EARLIER_JOB_TYPES)
