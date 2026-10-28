"""caption settings and word timings

EXPLAINER-007. An explainer can have word-synced captions and callouts, and every speech of an
explainer gets a start and an end time for each of its script words.

- `project.captions` and `project.callouts`: two render-time switches, on for every project
  (existing ones included). They are only read for an explainer, and can be changed at any time.
- `speech_word_timing`: one row per `speech_unit_audio` row (unique), holding the script words
  of the speech in order, each with its `start` and `end` in seconds, and how the times were
  made (`parakeet` or `estimated`). A new speech is a new audio row, so it gets new timings.
- `job`: its `type` CHECK gains `time_speech_words`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0071 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0073
Revises: 0072
Create Date: 2026-10-28 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0073"
down_revision: str | Sequence[str] | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "speech_word_timing"

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
    "write_music_theme_prompt",
    "write_music_plan",
    "write_music_cue",
    "audit_music_cues",
    "rewrite_music_prompt",
    "place_music",
    "preview_music_mix",
)
_NEW_JOB_TYPES = ("time_speech_words",)


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _NEW_JOB_TYPES)
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("captions", sa.Boolean(), nullable=False, server_default=sa.text("1"))
        )
        batch_op.add_column(
            sa.Column("callouts", sa.Boolean(), nullable=False, server_default=sa.text("1"))
        )
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("speech_unit_audio_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("match_percent", sa.REAL(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("words", sa.JSON(), nullable=False),
        sa.Column("heard_text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('parakeet', 'estimated')", name=op.f(f"ck_{_TABLE}_source_valid")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["speech_unit_audio_id"],
            ["speech_unit_audio.id"],
            name=op.f(f"fk_{_TABLE}_speech_unit_audio_id_speech_unit_audio"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TABLE}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint("speech_unit_audio_id", name=op.f(f"uq_{_TABLE}_speech_unit_audio_id")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_TABLE}_project", ["project_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every word timing row and every `time_speech_words` job row is deleted
    (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TABLE}_project")
    op.drop_table(_TABLE)
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("callouts")
        batch_op.drop_column("captions")
    op.execute("DELETE FROM job WHERE type = 'time_speech_words'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
