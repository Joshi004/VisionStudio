"""speech unit audio

PHASE-019. Each speech unit planned by PHASE-018 is spoken by a new `synthesize_speech_unit`
job, and the stored audio and its measured length are kept in a new table.

- `speech_unit_audio`: one row per speech made (or being made) for one unit. `audio_key` is a
  hash of what the audio depends on (the text, the voice, the Breeze mode and the instruction),
  so an unchanged unit keeps its audio when its scene is planned again. `path`, `size_bytes`,
  `sha256`, `duration_s` (measured with ffprobe) and `sample_rate` stay NULL until the job has
  stored the speech. `inputs` records the `speech_units` row and where the voice came from
  (the artifact provenance convention, DATABASE_STRUCTURE.md Section 2.1).
- `job`: its `type` CHECK gains `synthesize_speech_unit`. `job` is rebuilt (SQLite cannot change
  a CHECK in place), the same way revisions 0028 to 0036 did. No row is changed.

No data needs preserving, so nothing is backfilled.

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-21 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
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
)
_SPEECH_JOB_TYPE = "synthesize_speech_unit"
_TABLE = "speech_unit_audio"


def _type_check(job_types: Sequence[str]) -> str:
    """The `job.type` CHECK for these types. They are fixed names in this file, never input."""
    return "type IN (" + ", ".join(f"'{name}'" for name in job_types) + ")"


def _rebuild_job_check(job_types: Sequence[str]) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _type_check(job_types))


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_job_check(_EARLIER_JOB_TYPES + (_SPEECH_JOB_TYPE,))
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("speaker_id", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=True),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("audio_key", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('narration', 'dialogue')", name=op.f(f"ck_{_TABLE}_kind_valid")
        ),
        sa.CheckConstraint("mode IN ('clone', 'direction')", name=op.f(f"ck_{_TABLE}_mode_valid")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TABLE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f(f"fk_{_TABLE}_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TABLE}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
    )
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            f"idx_{_TABLE}_project_key", ["project_id", "audio_key"], unique=False
        )
        batch_op.create_index(
            f"idx_{_TABLE}_project_scene", ["project_id", "scene_id"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema. Every speech unit audio row and every `synthesize_speech_unit` job row
    is deleted (the old `job.type` CHECK would refuse the jobs). Stored files are kept.
    """
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TABLE}_project_scene")
        batch_op.drop_index(f"idx_{_TABLE}_project_key")
    op.drop_table(_TABLE)

    op.execute("DELETE FROM job WHERE type = 'synthesize_speech_unit'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
