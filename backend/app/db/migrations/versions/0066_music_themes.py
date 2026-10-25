"""music themes

MUSIC-007. Every theme of the Music Bible is recorded as three candidate recordings, one of
which becomes its canonical recording, and each emotion the Bible lists for the theme gets a
recording of its own.

- `music_theme`: one row per generation of one theme of a project. It holds the fields the
  model wrote for the canonical recording (`fields`), what it was made from (`inputs`) and the
  chosen candidate (`chosen_candidate_id`, `chosen_by` is `auto` or `owner`).
  `UNIQUE (project_id, theme_id, version)`.
- `music_theme_candidate`: one candidate recording of a theme, a link to the `lab_music_run`
  that made it, with the result of the technical check (`check_result`).
- `music_theme_version`: one emotional version of a theme, made from the candidate that was the
  canonical recording at the time (`candidate_id`), again a link to a `lab_music_run`.
- `job`: its `type` CHECK gains `write_music_theme_prompt`. `job` is rebuilt (SQLite cannot
  change a CHECK in place), the same way revision 0065 did. No row is changed.

`music_theme` and `music_theme_candidate` point at each other (the chosen candidate), the
intended cycle, as `character_look` and `character_named_look` do. No data needs preserving, so
nothing is backfilled.

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-25 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0066"
down_revision: str | Sequence[str] | None = "0065"
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
    "plan_environment_views",
    "write_environment_view_prompt",
    "write_music_bible",
)
_NEW_JOB_TYPES = ("write_music_theme_prompt",)

_THEME = "music_theme"
_CANDIDATE = "music_theme_candidate"
_VERSION = "music_theme_version"
_CHOSEN_FK = "fk_music_theme_chosen_candidate_id_music_theme_candidate"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        UTCDateTime(),
        server_default=sa.text("(CURRENT_TIMESTAMP)"),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _NEW_JOB_TYPES)

    op.create_table(
        _THEME,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("bible_id", sa.Integer(), nullable=False),
        sa.Column("theme_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        # The foreign key to the candidate is added below, once that table exists.
        sa.Column("chosen_candidate_id", sa.Integer(), nullable=True),
        sa.Column("chosen_by", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "chosen_by IS NULL OR chosen_by IN ('auto', 'owner')",
            name=op.f(f"ck_{_THEME}_chosen_by_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_THEME}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["bible_id"],
            ["music_bible.id"],
            name=op.f(f"fk_{_THEME}_bible_id_music_bible"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f(f"fk_{_THEME}_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_THEME}")),
        sa.UniqueConstraint(
            "project_id", "theme_id", "version", name=op.f(f"uq_{_THEME}_project_id")
        ),
    )
    with op.batch_alter_table(_THEME, schema=None) as batch_op:
        batch_op.create_index("idx_music_theme_project", ["project_id", "theme_id"], unique=False)

    op.create_table(
        _CANDIDATE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_row_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("check_result", sa.JSON(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["theme_row_id"],
            [f"{_THEME}.id"],
            name=op.f(f"fk_{_CANDIDATE}_theme_row_id_{_THEME}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lab_run_id"],
            ["lab_music_run.id"],
            name=op.f(f"fk_{_CANDIDATE}_lab_run_id_lab_music_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_CANDIDATE}")),
        sa.UniqueConstraint("theme_row_id", "position", name=op.f(f"uq_{_CANDIDATE}_theme_row_id")),
    )
    with op.batch_alter_table(_CANDIDATE, schema=None) as batch_op:
        batch_op.create_index("idx_music_theme_candidate_run", ["lab_run_id"], unique=False)

    with op.batch_alter_table(_THEME, schema=None) as batch_op:
        batch_op.create_foreign_key(
            batch_op.f(_CHOSEN_FK), _CANDIDATE, ["chosen_candidate_id"], ["id"], ondelete="SET NULL"
        )

    op.create_table(
        _VERSION,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_row_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("emotion", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("check_result", sa.JSON(), nullable=True),
        _created_at(),
        sa.CheckConstraint("method IN ('text')", name=op.f(f"ck_{_VERSION}_method_valid")),
        sa.ForeignKeyConstraint(
            ["theme_row_id"],
            [f"{_THEME}.id"],
            name=op.f(f"fk_{_VERSION}_theme_row_id_{_THEME}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            [f"{_CANDIDATE}.id"],
            name=op.f(f"fk_{_VERSION}_candidate_id_{_CANDIDATE}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f(f"fk_{_VERSION}_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lab_run_id"],
            ["lab_music_run.id"],
            name=op.f(f"fk_{_VERSION}_lab_run_id_lab_music_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_VERSION}")),
    )
    with op.batch_alter_table(_VERSION, schema=None) as batch_op:
        batch_op.create_index("idx_music_theme_version_theme", ["theme_row_id"], unique=False)
        batch_op.create_index("idx_music_theme_version_run", ["lab_run_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every theme, candidate and version is deleted (the recordings stay in
    the Music lab), and so is every job of the new type (the old `job.type` CHECK would refuse
    them).
    """
    with op.batch_alter_table(_VERSION, schema=None) as batch_op:
        batch_op.drop_index("idx_music_theme_version_run")
        batch_op.drop_index("idx_music_theme_version_theme")
    op.drop_table(_VERSION)

    # The two tables point at each other: break the cycle before dropping either.
    op.execute(f"UPDATE {_THEME} SET chosen_candidate_id = NULL")
    with op.batch_alter_table(_THEME, schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_CHOSEN_FK), type_="foreignkey")
    with op.batch_alter_table(_CANDIDATE, schema=None) as batch_op:
        batch_op.drop_index("idx_music_theme_candidate_run")
    op.drop_table(_CANDIDATE)

    with op.batch_alter_table(_THEME, schema=None) as batch_op:
        batch_op.drop_index("idx_music_theme_project")
    op.drop_table(_THEME)

    op.execute("DELETE FROM job WHERE type = 'write_music_theme_prompt'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
