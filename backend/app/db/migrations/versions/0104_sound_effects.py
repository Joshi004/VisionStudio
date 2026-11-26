"""sound effects

EXM-006 (`Explainer_music_phases.md`). The two sounds a continuous explainer plays at its graphic
and evidence moments, made once for the project.

- `project.sound_effects`: whether the project has its two sound effects (XM-8). NOT NULL, default
  0, so every project that exists reads off. Only a continuous explainer can have it on; the
  create form turns it on for a new one.
- `sound_effect_take`: one row per take of one of the project's two sounds (`role` `graphic` or
  `evidence`). The audio is a Music lab run (`lab_run_id`), as for a music take. `fields` are the
  prompt fields exactly as sent, `check_result` the technical check with the measured facts.
  Selection, rejection with a note and the lock are columns of the take, as for `music_take`. A
  take is never deleted and its audio and prompt never change.
- `job`: its `type` CHECK gains `write_sound_effect`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0100 did. No row is changed.

Foreign keys are off on the migration connection, so a rebuilt table cascades nothing.

Revision ID: 0104
Revises: 0103
Create Date: 2026-11-27 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0104"
down_revision: str | Sequence[str] | None = "0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TAKE = "sound_effect_take"

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
    "time_lab_speech_words",
    "render_av_test",
    "write_lab_graphic_brief",
    "write_lab_graphic_template_spec",
    "write_lab_graphic_block_scene",
    "write_lab_graphic_component",
    "render_lab_graphic",
    "time_lab_graphic_words",
    "write_graphic_theme",
    "write_shot_graphic_brief",
    "write_shot_graphic_component",
    "write_shot_graphic_scene",
    "render_shot_graphic",
    "describe_photo",
    "render_scene",
    "write_thumbnail_concepts",
    "write_callout_look",
    "write_callout_component",
    "render_callout_preview",
    "write_callout_scene",
    "time_voice_recording",
    "split_voice_recording",
    "splice_voice_recording",
    "write_chat_reply",
    "write_youtube_draft",
    "publish_youtube",
    "suggest_evidence_claims",
    "write_evidence_brief",
    "import_evidence",
    "render_evidence_clip",
    "transcribe_evidence_clip",
)
_NEW_JOB_TYPES = ("write_sound_effect",)


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
            sa.Column("sound_effects", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )

    op.create_table(
        _TAKE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("retry_of_id", sa.Integer(), nullable=True),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("requested_s", sa.Float(), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=True),
        sa.Column("check_result", sa.JSON(), nullable=True),
        sa.Column("selected_at", UTCDateTime(), nullable=True),
        sa.Column("selected_by", sa.Text(), nullable=True),
        sa.Column("rejected_at", UTCDateTime(), nullable=True),
        sa.Column("reject_note", sa.Text(), nullable=True),
        sa.Column("locked_at", UTCDateTime(), nullable=True),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('graphic', 'evidence')", name=op.f(f"ck_{_TAKE}_role_valid")),
        sa.CheckConstraint(
            "selected_by IS NULL OR selected_by IN ('auto', 'owner')",
            name=op.f(f"ck_{_TAKE}_selected_by_valid"),
        ),
        sa.CheckConstraint(
            "locked_at IS NULL OR selected_at IS NOT NULL",
            name=op.f(f"ck_{_TAKE}_lock_needs_selection"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{_TAKE}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_id"],
            [f"{_TAKE}.id"],
            name=op.f(f"fk_{_TAKE}_retry_of_id_{_TAKE}"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lab_run_id"],
            ["lab_music_run.id"],
            name=op.f(f"fk_{_TAKE}_lab_run_id_lab_music_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f(f"fk_{_TAKE}_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TAKE}")),
    )
    with op.batch_alter_table(_TAKE, schema=None) as batch_op:
        batch_op.create_index("idx_sound_effect_take_role", ["project_id", "role"], unique=False)
        batch_op.create_index("idx_sound_effect_take_run", ["lab_run_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. Every sound effect take is deleted (the audio stays in the Music lab),
    and so is every job of the new type (the old `job.type` CHECK would refuse them).
    """
    with op.batch_alter_table(_TAKE, schema=None) as batch_op:
        batch_op.drop_index("idx_sound_effect_take_run")
        batch_op.drop_index("idx_sound_effect_take_role")
    op.drop_table(_TAKE)

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("sound_effects")

    op.execute("DELETE FROM job WHERE type = 'write_sound_effect'")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
