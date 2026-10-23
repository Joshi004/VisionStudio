"""the Music lab

The Music lab tries the GPU server's music and sound models by hand (ACE-Step 1.5, YuE2, Stable
Audio 3, Stable Audio Open and LTX text-to-audio) and compares what they make for one brief.

- `lab_music_run`: one piece of audio the lab made, or is making. The job holds the status and the
  exact request; this row holds what the page lists and compares: the kind, the model, the brief,
  the prompt fields that were sent, the seed, the stored file and, once a person has listened,
  a verdict and a note. Runs started by one click share a `group_key`.
- `job`: its `type` CHECK gains `lab_music` (the audio) and `write_lab_music_prompt` (the language
  model writing the prompt fields for one model). `job` is rebuilt (SQLite cannot change a CHECK
  in place), the same way revision 0052 did. No row is changed.

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-23 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0057"
down_revision: str | Sequence[str] | None = "0056"
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
)
_MUSIC_JOB_TYPES = ("lab_music", "write_lab_music_prompt")


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + _MUSIC_JOB_TYPES)

    op.create_table(
        "lab_music_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("group_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("brief", sa.JSON(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("duration_s", sa.REAL(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('score', 'song', 'stem', 'sfx', 'ambience')",
            name=op.f("ck_lab_music_run_kind_valid"),
        ),
        sa.CheckConstraint(
            "model IN ('ace-step-1.5', 'yue2', 'stable-audio-3', 'stable-audio-open', 'ltx-audio')",
            name=op.f("ck_lab_music_run_model_valid"),
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('good', 'usable', 'bad')",
            name=op.f("ck_lab_music_run_verdict_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f("fk_lab_music_run_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f("fk_lab_music_run_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_music_run")),
    )
    with op.batch_alter_table("lab_music_run", schema=None) as batch_op:
        batch_op.create_index("idx_lab_music_run_created", ["created_at"], unique=False)
        batch_op.create_index("idx_lab_music_run_group", ["group_key"], unique=False)
        batch_op.create_index("idx_lab_music_run_job", ["job_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. The runs are dropped (their stored files stay on disk), and every
    `lab_music` and `write_lab_music_prompt` job row is deleted, because the old `job.type`
    CHECK would refuse them.
    """
    op.drop_table("lab_music_run")
    op.execute("DELETE FROM job WHERE type IN ('lab_music', 'write_lab_music_prompt')")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
