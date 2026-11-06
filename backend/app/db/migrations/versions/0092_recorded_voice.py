"""recorded voice

REC-002. A continuous explainer can have its voice recorded by a person instead of made by
the speech model. Every table of the recorded-voice design is made here, so the later phases add
no migration.

- `project.take_source`: `generated` (today) or `recorded`. Every project is `generated`.
- `speech_unit_audio.mode`: the CHECK gains `recorded`. The table is rebuilt (SQLite cannot
  change a CHECK in place); foreign keys are off on the migration connection, so nothing
  cascades. No row is changed.
- `voice_recording`: one row per recording received or made by splicing. A stored row is never
  changed.
- `voice_recording_timing`: the time of each script word of one recording, one row per
  recording.
- `recording_boundary_decision`: the owner's decision on one scene boundary of one full
  recording version.

No data needs preserving, so nothing is backfilled.

Revision ID: 0092
Revises: 0091
Create Date: 2026-11-06 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0092"
down_revision: str | Sequence[str] | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECORDING = "voice_recording"
_TIMING = "voice_recording_timing"
_DECISION = "recording_boundary_decision"
_AUDIO = "speech_unit_audio"
_MODE_CHECK = op.f(f"ck_{_AUDIO}_mode_valid")
_SOURCE_CHECK = op.f("ck_project_take_source_valid")
_CREATED_AT_DEFAULT = sa.text("(CURRENT_TIMESTAMP)")


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "take_source", sa.Text(), server_default=sa.text("'generated'"), nullable=False
            )
        )
        batch_op.create_check_constraint(_SOURCE_CHECK, "take_source IN ('generated', 'recorded')")

    with op.batch_alter_table(_AUDIO, schema=None) as batch_op:
        batch_op.drop_constraint(_MODE_CHECK, type_="check")
        batch_op.create_check_constraint(_MODE_CHECK, "mode IN ('clone', 'direction', 'recorded')")

    op.create_table(
        _RECORDING,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("base_recording_id", sa.Integer(), nullable=True),
        sa.Column("patch_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), server_default=_CREATED_AT_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "scope IN ('full', 'scene', 'patch')", name=op.f(f"ck_{_RECORDING}_scope_valid")
        ),
        sa.CheckConstraint(
            "origin IN ('browser', 'upload', 'splice')", name=op.f(f"ck_{_RECORDING}_origin_valid")
        ),
        sa.CheckConstraint(
            "(scope = 'scene') = (scene_id IS NOT NULL)",
            name=op.f(f"ck_{_RECORDING}_scene_only_for_scene"),
        ),
        sa.CheckConstraint(
            "(scope = 'full') = (version IS NOT NULL)",
            name=op.f(f"ck_{_RECORDING}_version_only_for_full"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_RECORDING}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["base_recording_id"],
            [f"{_RECORDING}.id"],
            name=op.f(f"fk_{_RECORDING}_base_recording_id_{_RECORDING}"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["patch_id"],
            [f"{_RECORDING}.id"],
            name=op.f(f"fk_{_RECORDING}_patch_id_{_RECORDING}"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_RECORDING}")),
        sa.UniqueConstraint("project_id", "version", name=op.f(f"uq_{_RECORDING}_project_id")),
    )
    with op.batch_alter_table(_RECORDING, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_RECORDING}_project", ["project_id"])

    op.create_table(
        _TIMING,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("voice_recording_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("match_percent", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("words", sa.JSON(), nullable=False),
        sa.Column("heard_text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=_CREATED_AT_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "source IN ('parakeet', 'estimated')", name=op.f(f"ck_{_TIMING}_source_valid")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TIMING}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["voice_recording_id"],
            [f"{_RECORDING}.id"],
            name=op.f(f"fk_{_TIMING}_voice_recording_id_{_RECORDING}"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TIMING}_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TIMING}")),
        sa.UniqueConstraint("voice_recording_id", name=op.f(f"uq_{_TIMING}_voice_recording_id")),
    )
    with op.batch_alter_table(_TIMING, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_TIMING}_project", ["project_id"])

    op.create_table(
        _DECISION,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("after_scene_id", sa.Text(), nullable=False),
        sa.Column("before_scene_id", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("cut_s", sa.Float(), nullable=True),
        sa.Column("created_at", UTCDateTime(), server_default=_CREATED_AT_DEFAULT, nullable=False),
        sa.Column("updated_at", UTCDateTime(), server_default=_CREATED_AT_DEFAULT, nullable=False),
        sa.CheckConstraint(
            "decision IN ('keep', 'cut_at')", name=op.f(f"ck_{_DECISION}_decision_valid")
        ),
        sa.CheckConstraint(
            "(decision = 'cut_at') = (cut_s IS NOT NULL)",
            name=op.f(f"ck_{_DECISION}_cut_only_for_cut_at"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_DECISION}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"],
            [f"{_RECORDING}.id"],
            name=op.f(f"fk_{_DECISION}_recording_id_{_RECORDING}"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_DECISION}")),
        sa.UniqueConstraint(
            "recording_id",
            "after_scene_id",
            "before_scene_id",
            name=op.f(f"uq_{_DECISION}_recording_id"),
        ),
    )
    with op.batch_alter_table(_DECISION, schema=None) as batch_op:
        batch_op.create_index(f"idx_{_DECISION}_project", ["project_id"])


def downgrade() -> None:
    """Downgrade schema. Every recording, timing and decision is deleted, and so is every
    recorded take with its word timing (the old `mode` CHECK would refuse the takes). Stored
    audio files are never deleted.
    """
    with op.batch_alter_table(_DECISION, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_DECISION}_project")
    op.drop_table(_DECISION)
    with op.batch_alter_table(_TIMING, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_TIMING}_project")
    op.drop_table(_TIMING)
    with op.batch_alter_table(_RECORDING, schema=None) as batch_op:
        batch_op.drop_index(f"idx_{_RECORDING}_project")
    op.drop_table(_RECORDING)

    op.execute(
        "DELETE FROM speech_word_timing WHERE speech_unit_audio_id IN "
        f"(SELECT id FROM {_AUDIO} WHERE mode = 'recorded')"
    )
    op.execute(f"DELETE FROM {_AUDIO} WHERE mode = 'recorded'")
    with op.batch_alter_table(_AUDIO, schema=None) as batch_op:
        batch_op.drop_constraint(_MODE_CHECK, type_="check")
        batch_op.create_check_constraint(_MODE_CHECK, "mode IN ('clone', 'direction')")

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(_SOURCE_CHECK, type_="check")
        batch_op.drop_column("take_source")
