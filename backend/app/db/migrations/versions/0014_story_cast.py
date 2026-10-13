"""a project's cast: characters, locations and which of them a scene shows

Project cast and character consistency. Four things change:

- `job`: its `type` CHECK gains `extract_cast`, `write_character_reference_prompt`,
  `generate_character_reference` and `assign_cast`. `job` is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0013 did. The migration connection runs with foreign
  keys off (see `env.py`), so rebuilding a table cannot fire an ON DELETE CASCADE or an ON
  DELETE SET NULL.
- `asset`: its `kind` CHECK gains `reference` (the picture that pins how a character or a
  location looks). `asset` is rebuilt the same way.
- `character` and `location`: the cast of a project, each with the text that describes it, the
  prompt for its reference picture and the reference picture itself.
- `scene`: `character_id` and `location_id` (the one character and the one place a scene
  shows, both optional), `cast_assignment_source` (`manual` or `ai`) and
  `cast_assignment_job_id` (the `assign_cast` job that chose them).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-12 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover', 'lab_image', "
    "'write_last_frame_prompt', 'generate_last_frame', 'write_talk_prompts')"
)
_NEW_JOB_TYPES = (
    "type IN ('transcribe', 'plan_scenes', 'draft_descriptions', 'write_image_prompt', "
    "'generate_frame', 'generate_clip', 'render_final', 'lab_video', 'write_lab_video_prompt', "
    "'auto_pipeline', 'lab_voice', 'generate_voiceover', 'lab_image', "
    "'write_last_frame_prompt', 'generate_last_frame', 'write_talk_prompts', "
    "'extract_cast', 'write_character_reference_prompt', 'generate_character_reference', "
    "'assign_cast')"
)
_NEW_JOB_TYPE_NAMES = (
    "'extract_cast', 'write_character_reference_prompt', 'generate_character_reference', "
    "'assign_cast'"
)
_OLD_ASSET_KINDS = "kind IN ('voiceover', 'frame', 'clip', 'final')"
_NEW_ASSET_KINDS = "kind IN ('voiceover', 'frame', 'clip', 'final', 'reference')"
_STATUS_CHECK = "status IN ('pending', 'prompted', 'ready', 'failed')"
_SOURCE_CHECK = "ck_scene_cast_assignment_source_valid"
_CHARACTER_FK = "fk_scene_character_id_character"
_LOCATION_FK = "fk_scene_location_id_location"
_JOB_FK = "fk_scene_cast_assignment_job_id_job"


def _cast_table(name: str, *, with_personality: bool) -> None:
    columns = [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("appearance_description", sa.Text(), nullable=False),
    ]
    if with_personality:
        columns += [
            sa.Column("personality_description", sa.Text(), nullable=True),
            sa.Column("voice_description", sa.Text(), nullable=True),
        ]
    columns += [
        sa.Column("reference_prompt", sa.Text(), nullable=True),
        sa.Column("reference_prompt_job_id", sa.Integer(), nullable=True),
        sa.Column("reference_asset_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(_STATUS_CHECK, name=op.f(f"ck_{name}_status_valid")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f(f"fk_{name}_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reference_prompt_job_id"],
            ["job.id"],
            name=op.f(f"fk_{name}_reference_prompt_job_id_job"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reference_asset_id"],
            ["asset.id"],
            name=op.f(f"fk_{name}_reference_asset_id_asset"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    ]
    op.create_table(name, *columns)
    with op.batch_alter_table(name, schema=None) as batch_op:
        batch_op.create_index(f"idx_{name}_project", ["project_id"], unique=False)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _NEW_JOB_TYPES)

    with op.batch_alter_table("asset", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_asset_kind_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_asset_kind_valid"), _NEW_ASSET_KINDS)

    _cast_table("character", with_personality=True)
    _cast_table("location", with_personality=False)

    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.add_column(sa.Column("character_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("location_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("cast_assignment_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("cast_assignment_job_id", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            op.f(_SOURCE_CHECK), "cast_assignment_source IN ('manual', 'ai')"
        )
        batch_op.create_foreign_key(
            batch_op.f(_CHARACTER_FK), "character", ["character_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            batch_op.f(_LOCATION_FK), "location", ["location_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            batch_op.f(_JOB_FK), "job", ["cast_assignment_job_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    """Downgrade schema. The cast is dropped, and so are the cast jobs and the reference
    pictures, because the old CHECKs would refuse them. Files stay in `media/`.
    """
    with op.batch_alter_table("scene", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_JOB_FK), type_="foreignkey")
        batch_op.drop_constraint(batch_op.f(_LOCATION_FK), type_="foreignkey")
        batch_op.drop_constraint(batch_op.f(_CHARACTER_FK), type_="foreignkey")
        batch_op.drop_constraint(op.f(_SOURCE_CHECK), type_="check")
        batch_op.drop_column("cast_assignment_job_id")
        batch_op.drop_column("cast_assignment_source")
        batch_op.drop_column("location_id")
        batch_op.drop_column("character_id")

    for name in ("location", "character"):
        with op.batch_alter_table(name, schema=None) as batch_op:
            batch_op.drop_index(f"idx_{name}_project")
        op.drop_table(name)

    op.execute(f"DELETE FROM job WHERE type IN ({_NEW_JOB_TYPE_NAMES})")
    op.execute(
        "UPDATE job SET result_asset_id = NULL "
        "WHERE result_asset_id IN (SELECT id FROM asset WHERE kind = 'reference')"
    )
    op.execute("DELETE FROM asset WHERE kind = 'reference'")

    with op.batch_alter_table("asset", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_asset_kind_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_asset_kind_valid"), _OLD_ASSET_KINDS)
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), _OLD_JOB_TYPES)
