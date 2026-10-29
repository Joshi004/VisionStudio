"""audio video lab

AVLAB. A test of the Audio video lab, inside a library character: a whole text spoken as one
speech, some marked parts of it made into H3 clips from slices of that speech, and two rendered
videos to compare.

- `av_lab_test`: one row per test. `parts` is what the author marked, `voice_run_id` the speech,
  `word_timing` the time of every word (Parakeet), `render_job_id` and the two output paths the
  render. Deleted with its character.
- `av_lab_segment`: one row per marked part: its words, its place in the speech, its slice of the
  speech (a `lab_voice_run`) and the character take that makes its clip. Deleted with its test.
- `job`: its `type` CHECK gains `time_lab_speech_words` and `render_av_test`. `job` is rebuilt
  (SQLite cannot change a CHECK in place), the same way revision 0074 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0075
Revises: 0074
Create Date: 2026-10-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0075"
down_revision: str | Sequence[str] | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEST = "av_lab_test"
_SEGMENT = "av_lab_segment"

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
    "time_speech_words",
    "write_callout_plan",
)
_NEW_JOB_TYPES = ("time_lab_speech_words", "render_av_test")


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
    op.create_table(
        _TEST,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("audio_marker", sa.Text(), nullable=False),
        sa.Column("orientation", sa.Text(), nullable=False),
        sa.Column("first_frame", sa.JSON(), nullable=False),
        sa.Column("parts", sa.JSON(), nullable=False),
        sa.Column("voice_run_id", sa.Integer(), nullable=True),
        sa.Column("timing_job_id", sa.Integer(), nullable=True),
        sa.Column("word_timing", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("render_job_id", sa.Integer(), nullable=True),
        sa.Column("mixed_path", sa.Text(), nullable=True),
        sa.Column("tts_path", sa.Text(), nullable=True),
        sa.Column("render_info", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("copied_from_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "audio_marker IN ('fully_copy', 'partially_copy')",
            name=op.f(f"ck_{_TEST}_marker_valid"),
        ),
        sa.CheckConstraint(
            "orientation IN ('portrait', 'landscape')",
            name=op.f(f"ck_{_TEST}_orientation_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["library_character.id"],
            name=op.f(f"fk_{_TEST}_character_id_library_character"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["voice_run_id"],
            ["lab_voice_run.id"],
            name=op.f(f"fk_{_TEST}_voice_run_id_lab_voice_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["timing_job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TEST}_timing_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["render_job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TEST}_render_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TEST}")),
    )
    with op.batch_alter_table(_TEST, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_TEST}_character", ["character_id"], unique=False)

    op.create_table(
        _SEGMENT,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("start_word", sa.Integer(), nullable=False),
        sa.Column("end_word", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("clip_frames", sa.Integer(), nullable=False),
        sa.Column("slice_run_id", sa.Integer(), nullable=True),
        sa.Column("take_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["test_id"],
            [f"{_TEST}.id"],
            name=op.f(f"fk_{_SEGMENT}_test_id_{_TEST}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["slice_run_id"],
            ["lab_voice_run.id"],
            name=op.f(f"fk_{_SEGMENT}_slice_run_id_lab_voice_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["take_id"],
            ["character_take.id"],
            name=op.f(f"fk_{_SEGMENT}_take_id_character_take"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_SEGMENT}")),
        sa.UniqueConstraint("test_id", "position", name=op.f(f"uq_{_SEGMENT}_test_id")),
    )
    with op.batch_alter_table(_SEGMENT, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_SEGMENT}_take", ["take_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every test and segment row, and every `time_lab_speech_words` and
    `render_av_test` job row, is deleted (the old `job.type` CHECK would refuse the jobs).
    """
    with op.batch_alter_table(_SEGMENT, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_SEGMENT}_take")
    op.drop_table(_SEGMENT)
    with op.batch_alter_table(_TEST, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TEST}_character")
    op.drop_table(_TEST)
    op.execute("DELETE FROM job WHERE type IN ('time_lab_speech_words', 'render_av_test')")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
