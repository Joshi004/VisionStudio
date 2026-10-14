"""the Character lab replaces the Talking character lab

Phase 25. The old Talking character lab (Phase 24) is removed, by the author's explicit choice,
in the same migration that adds its replacement:

- `lab_talk_run` and `lab_character` are dropped. Their speeches and clips stay as ordinary
  Voice lab and Video lab runs, and files stay in `media/`: only the cast and the takes that
  tied them together are gone. Every `write_talk_prompts` job row is deleted (the new `job.type`
  CHECK would refuse them).
- `job`: its `type` CHECK loses `write_talk_prompts` and gains `write_character_look_prompt`
  and `write_character_take_prompt`. `job` is rebuilt (SQLite cannot change a CHECK in place),
  the same way revision 0013 did. The migration connection runs with foreign keys off (see
  `env.py`), so rebuilding a table cannot fire an ON DELETE CASCADE or an ON DELETE SET NULL.
- `library_character`: the Character lab's own, project-independent cast. Unrelated to a
  project's cast (`character`/`location`, revision 0014): the two never touch.
- `character_look`, `character_look_candidate`, `character_reference`: a character's reference
  pictures, made and chosen the same way a project's cast reference is, with four extra angles.
- `character_take`: one thing made from a character (an audio line, a picture, or a clip, with
  or without dialogue), reusing the Image, Voice and Video labs' own jobs and runs.
- `library_character.current_look_id` is added by a second ALTER, after `character_look`
  exists, because the two tables point at each other (the same intended cycle as `asset`'s own
  circular reference, DATABASE_STRUCTURE.md Section 3).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-14 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover', 'lab_image', "
    "'write_last_frame_prompt', 'generate_last_frame', 'write_talk_prompts', "
    "'extract_cast', 'write_character_reference_prompt', 'generate_character_reference', "
    "'assign_cast')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover', 'lab_image', "
    "'write_last_frame_prompt', 'generate_last_frame', "
    "'extract_cast', 'write_character_reference_prompt', 'generate_character_reference', "
    "'assign_cast', 'write_character_look_prompt', 'write_character_take_prompt')"
)
_NEW_JOB_TYPE_NAMES = "'write_character_look_prompt', 'write_character_take_prompt'"
_CURRENT_LOOK_FK = "fk_library_character_current_look_id_character_look"


def _timestamp_column(name: str) -> sa.Column:
    """A `created_at` or `updated_at` column: UTC, defaulting to the row's insert time."""
    return sa.Column(
        name, UTCDateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False
    )


def _rebuild_job_check(new_check: str) -> None:
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), new_check)


def upgrade() -> None:
    """Upgrade schema."""
    # --- Remove the Talking character lab ------------------------------------------------
    with op.batch_alter_table("lab_talk_run", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_talk_run_voice_run")
        batch_op.drop_index("idx_lab_talk_run_created")
    op.drop_table("lab_talk_run")

    with op.batch_alter_table("lab_character", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_character_created")
    op.drop_table("lab_character")

    op.execute("DELETE FROM job WHERE type = 'write_talk_prompts'")
    _rebuild_job_check(_NEW_JOB_TYPES)

    # --- The Character lab's own cast -----------------------------------------------------
    op.create_table(
        "library_character",
        sa.Column("id", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        _timestamp_column("updated_at"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("gender", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("species", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("era_kind", sa.Text(), server_default=sa.text("'present'"), nullable=False),
        sa.Column("era_years", sa.Integer(), nullable=True),
        sa.Column("era_setting", sa.Text(), nullable=True),
        sa.Column("appearance", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("outfit", sa.Text(), nullable=True),
        sa.Column("personality", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("has_visible_mouth", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("voice_description", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "era_kind IN ('present', 'past', 'future')",
            name=op.f("ck_library_character_era_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f("fk_library_character_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_character")),
    )
    with op.batch_alter_table("library_character", schema=None) as batch_op:
        batch_op.create_index("idx_library_character_created", ["created_at"], unique=False)

    op.create_table(
        "character_look",
        sa.Column("id", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'writing_prompt'"), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('writing_prompt', 'choosing', 'making_angles', 'ready', 'failed')",
            name=op.f("ck_character_look_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["library_character.id"],
            name=op.f("fk_character_look_character_id_library_character"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f("fk_character_look_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_character_look")),
    )
    with op.batch_alter_table("character_look", schema=None) as batch_op:
        batch_op.create_index("idx_character_look_character", ["character_id"], unique=False)

    op.create_table(
        "character_look_candidate",
        sa.Column("id", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("look_id", sa.Integer(), nullable=False),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["look_id"],
            ["character_look.id"],
            name=op.f("fk_character_look_candidate_look_id_character_look"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lab_run_id"],
            ["lab_run.id"],
            name=op.f("fk_character_look_candidate_lab_run_id_lab_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_character_look_candidate")),
    )
    with op.batch_alter_table("character_look_candidate", schema=None) as batch_op:
        batch_op.create_index("idx_character_look_candidate_look", ["look_id"], unique=False)

    op.create_table(
        "character_reference",
        sa.Column("id", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("look_id", sa.Integer(), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("lab_run_id", sa.Integer(), nullable=True),
        sa.Column("lab_image_id", sa.Integer(), nullable=True),
        sa.Column("cutout_path", sa.Text(), nullable=True),
        sa.Column("cutout_mime", sa.Text(), nullable=True),
        sa.Column("cutout_width", sa.Integer(), nullable=True),
        sa.Column("cutout_height", sa.Integer(), nullable=True),
        sa.Column("cutout_size_bytes", sa.Integer(), nullable=True),
        sa.Column("cutout_sha256", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "angle IN ('front', 'three_quarter', 'profile', 'back', 'face')",
            name=op.f("ck_character_reference_angle_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["look_id"],
            ["character_look.id"],
            name=op.f("fk_character_reference_look_id_character_look"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lab_run_id"],
            ["lab_run.id"],
            name=op.f("fk_character_reference_lab_run_id_lab_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lab_image_id"],
            ["lab_image.id"],
            name=op.f("fk_character_reference_lab_image_id_lab_image"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("look_id", "angle", name=op.f("uq_character_reference_look_id")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_character_reference")),
    )

    op.create_table(
        "character_take",
        sa.Column("id", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("look_id", sa.Integer(), nullable=True),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("dialogue", sa.Text(), nullable=True),
        sa.Column("video_model", sa.Text(), nullable=True),
        sa.Column("lip_sync", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("framing", sa.Text(), server_default=sa.text("'medium'"), nullable=False),
        sa.Column("orientation", sa.Text(), server_default=sa.text("'portrait'"), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("auto_continue", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("prompts", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("image_run_id", sa.Integer(), nullable=True),
        sa.Column("voice_run_id", sa.Integer(), nullable=True),
        sa.Column("video_run_id", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "output IN ('image', 'audio', 'video')", name=op.f("ck_character_take_output_valid")
        ),
        sa.CheckConstraint(
            "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5')",
            name=op.f("ck_character_take_video_model_valid"),
        ),
        sa.CheckConstraint(
            "framing IN ('close_up', 'medium', 'wide')",
            name=op.f("ck_character_take_framing_valid"),
        ),
        sa.CheckConstraint(
            "orientation IN ('portrait', 'landscape')",
            name=op.f("ck_character_take_orientation_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["library_character.id"],
            name=op.f("fk_character_take_character_id_library_character"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["look_id"],
            ["character_look.id"],
            name=op.f("fk_character_take_look_id_character_look"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f("fk_character_take_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["image_run_id"],
            ["lab_run.id"],
            name=op.f("fk_character_take_image_run_id_lab_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["voice_run_id"],
            ["lab_voice_run.id"],
            name=op.f("fk_character_take_voice_run_id_lab_voice_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["video_run_id"],
            ["lab_video_run.id"],
            name=op.f("fk_character_take_video_run_id_lab_video_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_character_take")),
    )
    with op.batch_alter_table("character_take", schema=None) as batch_op:
        batch_op.create_index("idx_character_take_character", ["character_id"], unique=False)
        batch_op.create_index("idx_character_take_created", ["created_at"], unique=False)

    # `character_look` now exists, so the character's pointer to its current look can be added.
    with op.batch_alter_table("library_character", schema=None) as batch_op:
        batch_op.add_column(sa.Column("current_look_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f(_CURRENT_LOOK_FK),
            "character_look",
            ["current_look_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema. The Character lab's cast, looks and takes are dropped: the pictures,
    speeches and clips they made stay as ordinary Image, Voice and Video lab runs, and files
    stay in `media/`. Character lab prompt jobs are deleted, because the old CHECK would refuse
    them. The old Talking character lab's tables are recreated, empty: its cast and takes were
    not kept.
    """
    with op.batch_alter_table("library_character", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_CURRENT_LOOK_FK), type_="foreignkey")
        batch_op.drop_column("current_look_id")

    with op.batch_alter_table("character_take", schema=None) as batch_op:
        batch_op.drop_index("idx_character_take_created")
        batch_op.drop_index("idx_character_take_character")
    op.drop_table("character_take")

    op.drop_table("character_reference")

    with op.batch_alter_table("character_look_candidate", schema=None) as batch_op:
        batch_op.drop_index("idx_character_look_candidate_look")
    op.drop_table("character_look_candidate")

    with op.batch_alter_table("character_look", schema=None) as batch_op:
        batch_op.drop_index("idx_character_look_character")
    op.drop_table("character_look")

    with op.batch_alter_table("library_character", schema=None) as batch_op:
        batch_op.drop_index("idx_library_character_created")
    op.drop_table("library_character")

    op.execute(f"DELETE FROM job WHERE type IN ({_NEW_JOB_TYPE_NAMES})")
    _rebuild_job_check(_OLD_JOB_TYPES)

    op.create_table(
        "lab_character",
        sa.Column("id", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("image", sa.JSON(), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("voice_instruction", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f("fk_lab_character_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_character")),
    )
    with op.batch_alter_table("lab_character", schema=None) as batch_op:
        batch_op.create_index("idx_lab_character_created", ["created_at"], unique=False)

    op.create_table(
        "lab_talk_run",
        sa.Column("id", sa.Integer(), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("dialogue", sa.Text(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=True),
        sa.Column("image", sa.JSON(), nullable=False),
        sa.Column("character_note", sa.Text(), nullable=True),
        sa.Column("delivery_note", sa.Text(), nullable=True),
        sa.Column("voice_mode", sa.Text(), nullable=True),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("voice_instruction", sa.Text(), nullable=True),
        sa.Column("video_prompt", sa.Text(), nullable=True),
        sa.Column("orientation", sa.Text(), nullable=False),
        sa.Column("video_seed", sa.Integer(), nullable=True),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("auto_continue", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("voice_run_id", sa.Integer(), nullable=True),
        sa.Column("video_run_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "voice_mode IS NULL OR voice_mode IN ('design', 'clone', 'direction')",
            name=op.f("ck_lab_talk_run_voice_mode_valid"),
        ),
        sa.CheckConstraint(
            "orientation IN ('portrait', 'landscape')",
            name=op.f("ck_lab_talk_run_orientation_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["lab_character.id"],
            name=op.f("fk_lab_talk_run_character_id_lab_character"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voice.id"],
            name=op.f("fk_lab_talk_run_voice_id_voice"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_job_id"],
            ["job.id"],
            name=op.f("fk_lab_talk_run_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["voice_run_id"],
            ["lab_voice_run.id"],
            name=op.f("fk_lab_talk_run_voice_run_id_lab_voice_run"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["video_run_id"],
            ["lab_video_run.id"],
            name=op.f("fk_lab_talk_run_video_run_id_lab_video_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_talk_run")),
    )
    with op.batch_alter_table("lab_talk_run", schema=None) as batch_op:
        batch_op.create_index("idx_lab_talk_run_created", ["created_at"], unique=False)
        batch_op.create_index("idx_lab_talk_run_voice_run", ["voice_run_id"], unique=False)
