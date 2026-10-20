"""retire the narration pipeline

PHASE-046. The voiceover-driven narration pipeline is removed, so a project is now only a name,
an orientation, sizes, a frame rate and a script text, and the labs and the Character lab are
the only things that make media. The removed code is readable at the git tag `narration-final`.

What this migration changes, in this order:

1. Every `job` row of a narration type is deleted (the new `job.type` CHECK would refuse it).
   Only the six lab job types stay.
2. `job` is rebuilt (SQLite cannot change a CHECK or drop a column in place): its `type` CHECK
   keeps only the six lab types, and `scene_id` goes, with its foreign key and `idx_job_scene`.
3. The tables `scene_character`, `scene`, `character`, `location` and `transcript` are dropped.
4. `project` is rebuilt without the narration columns: `min_scene_seconds`,
   `max_scene_seconds`, `style_prefix`, `prompt_suffix`, `negative_prompt`, `clip_sound_volume`,
   `cut_instructions`, `description_instructions`, `video_model` (with its CHECK), `language`,
   `voiceover_asset_id` and `voice_id` (with their foreign keys).
5. The three settings only the narration pipeline read are deleted: `default_video_model`,
   `default_negative_prompt` and `max_parallel_ffmpeg`.

`asset` is not touched: its rows and the files they name stay (a later phase defines its own
kinds), and so does its `kind` CHECK.

The migration connection runs with foreign keys off (see `env.py`), so rebuilding a table
cannot fire an ON DELETE CASCADE or an ON DELETE SET NULL.

Applying it permanently deletes the narration rows. There is no downgrade: restore a copy of
`app.db` taken before the upgrade, or read the old schema at the tag `narration-final`.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-20 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LAB_JOB_TYPES = (
    "lab_image",
    "lab_video",
    "write_lab_video_prompt",
    "lab_voice",
    "write_character_look_prompt",
    "write_character_take_prompt",
)
_NARRATION_TABLES = ("scene_character", "scene", "character", "location", "transcript")
_PROJECT_COLUMNS = (
    "min_scene_seconds",
    "max_scene_seconds",
    "style_prefix",
    "prompt_suffix",
    "negative_prompt",
    "clip_sound_volume",
    "cut_instructions",
    "description_instructions",
    "video_model",
    "language",
    "voiceover_asset_id",
    "voice_id",
)
_SETTING_KEYS = ("default_video_model", "default_negative_prompt", "max_parallel_ffmpeg")


def _quoted(values: Sequence[str]) -> str:
    """The values as an SQL list. They are fixed names in this file, never user input."""
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Upgrade schema."""
    lab_types = _quoted(_LAB_JOB_TYPES)

    op.execute(f"DELETE FROM job WHERE type NOT IN ({lab_types})")
    with op.batch_alter_table("job", schema=None) as batch_op:
        batch_op.drop_index("idx_job_scene")
        batch_op.drop_constraint(op.f("ck_job_type_valid"), type_="check")
        batch_op.drop_constraint(batch_op.f("fk_job_scene_id_scene"), type_="foreignkey")
        batch_op.drop_column("scene_id")
        batch_op.create_check_constraint(op.f("ck_job_type_valid"), f"type IN ({lab_types})")

    for table in _NARRATION_TABLES:
        op.drop_table(table)

    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_project_video_model_valid"), type_="check")
        batch_op.drop_constraint(batch_op.f("fk_project_voice_id_voice"), type_="foreignkey")
        batch_op.drop_constraint(
            batch_op.f("fk_project_voiceover_asset_id_asset"), type_="foreignkey"
        )
        for column in _PROJECT_COLUMNS:
            batch_op.drop_column(column)

    op.execute(f"DELETE FROM setting WHERE key IN ({_quoted(_SETTING_KEYS)})")


def downgrade() -> None:
    """Downgrade schema. Not supported: the narration rows this migration deletes cannot be
    brought back. Restore a copy of `app.db` taken before the upgrade instead.
    """
    raise NotImplementedError(
        "Revision 0022 retired the narration pipeline and cannot be downgraded. "
        "Restore a copy of app.db taken before the upgrade."
    )
