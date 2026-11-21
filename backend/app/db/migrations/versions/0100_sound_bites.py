"""sound bites

SB-001 (`Sound_bite_implementation_phases.md`). This one migration creates every column and job
type sound bites need, so the later phases add no migration.

- `evidence_item`: `kind` may now be `video`. New nullable columns hold a clip's stored window
  (`video_path`, `video_sha256`), YouTube's caption track (`captions_path`, `captions_sha256`),
  the words the app heard in it (`heard_words`), the fidelity class, the proposed trim, the flags
  the owner must acknowledge, and the transcription job (`transcribe_job_id`). The plain text of
  the captions reuses `text_path` and `text_sha256`. Nothing is filled in until SB-006.
- `evidence_clip`: `purpose` may now also be `soundbite`.
- `job`: its `type` CHECK gains `transcribe_evidence_clip` (no handler yet, SB-006). `job` is
  rebuilt (SQLite cannot change a CHECK in place), the same way revision 0098 did.

No row is changed. Foreign keys are off on the migration connection, so a rebuilt table cascades
nothing.

Revision ID: 0100
Revises: 0099
Create Date: 2026-11-21 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0100"
down_revision: str | Sequence[str] | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ITEM = "evidence_item"
_CLIP = "evidence_clip"

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
)
_NEW_JOB_TYPES = ("transcribe_evidence_clip",)

_KIND_CHECK = op.f(f"ck_{_ITEM}_kind_valid")
_FIDELITY_CHECK = op.f(f"ck_{_ITEM}_fidelity_valid")
_PURPOSE_CHECK = op.f(f"ck_{_CLIP}_purpose_valid")
_TRANSCRIBE_FK = op.f(f"fk_{_ITEM}_transcribe_job_id_job")

_FIDELITIES = "'exact', 'near', 'paraphrase', 'mismatch'"

_NEW_COLUMNS = (
    "video_path",
    "video_sha256",
    "captions_path",
    "captions_sha256",
    "heard_words",
    "fidelity",
    "proposed_trim",
    "flags",
    "transcribe_job_id",
)


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

    with op.batch_alter_table(_ITEM, schema=None) as batch_op:
        batch_op.add_column(sa.Column("video_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("video_sha256", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("captions_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("captions_sha256", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("heard_words", sa.JSON(none_as_null=True), nullable=True))
        batch_op.add_column(sa.Column("fidelity", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("proposed_trim", sa.JSON(none_as_null=True), nullable=True))
        batch_op.add_column(sa.Column("flags", sa.JSON(none_as_null=True), nullable=True))
        batch_op.add_column(sa.Column("transcribe_job_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            _TRANSCRIBE_FK, "job", ["transcribe_job_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.drop_constraint(_KIND_CHECK, type_="check")
        batch_op.create_check_constraint(
            _KIND_CHECK, "kind IS NULL OR kind IN ('web', 'pdf', 'video')"
        )
        batch_op.create_check_constraint(
            _FIDELITY_CHECK, f"fidelity IS NULL OR fidelity IN ({_FIDELITIES})"
        )

    with op.batch_alter_table(_CLIP, schema=None) as batch_op:
        batch_op.drop_constraint(_PURPOSE_CHECK, type_="check")
        batch_op.create_check_constraint(
            _PURPOSE_CHECK, "purpose IN ('preview', 'shot', 'card', 'soundbite')"
        )


def downgrade() -> None:
    """Downgrade schema. The clips of purpose `soundbite` and of `video` items, the `video` items
    and the jobs of the new type (the old CHECKs would refuse them) are deleted. Files stored in
    `media/` are left where they are.
    """
    op.execute(
        f"DELETE FROM {_CLIP} WHERE purpose = 'soundbite' "
        f"OR item_id IN (SELECT id FROM {_ITEM} WHERE kind = 'video')"
    )
    op.execute(f"DELETE FROM {_ITEM} WHERE kind = 'video'")

    with op.batch_alter_table(_CLIP, schema=None) as batch_op:
        batch_op.drop_constraint(_PURPOSE_CHECK, type_="check")
        batch_op.create_check_constraint(_PURPOSE_CHECK, "purpose IN ('preview', 'shot', 'card')")

    with op.batch_alter_table(_ITEM, schema=None) as batch_op:
        batch_op.drop_constraint(_FIDELITY_CHECK, type_="check")
        batch_op.drop_constraint(_KIND_CHECK, type_="check")
        batch_op.create_check_constraint(_KIND_CHECK, "kind IS NULL OR kind IN ('web', 'pdf')")
        batch_op.drop_constraint(_TRANSCRIBE_FK, type_="foreignkey")
        for column in _NEW_COLUMNS:
            batch_op.drop_column(column)

    new_types = ", ".join(f"'{name}'" for name in _NEW_JOB_TYPES)
    op.execute(f"DELETE FROM job WHERE type IN ({new_types})")
    _rebuild_job_check(_EARLIER_JOB_TYPES)
