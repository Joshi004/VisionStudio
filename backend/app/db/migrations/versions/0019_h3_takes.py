"""MiniMax H3 in the Character lab's video takes

`character_take` changes in two ways:

- its `video_model` CHECK also accepts `minimax-h3`. The table is rebuilt (SQLite cannot change a
  CHECK in place), the same way revision 0017 rebuilt `lab_video_run`. The migration connection
  runs with foreign keys off (see `env.py`), so rebuilding it cannot fire an ON DELETE rule.
- the columns a MiniMax H3 take needs, all NULL (or off) for every take made before this
  revision:
  - `audio_marker`: how the speech is used (`fully_copy`, `partially_copy`, `reference`,
    `weak_reference`: MiniMax's own words for it).
  - `match_audio_duration`: the clip is as long as the speech.
  - `num_inference_steps`: 4 to 100, or NULL for the pipeline's own default.
  - `identity_refs`: the look's pictures are sent as extra reference pictures too.
  - `first_frame`: `{source: "lab" | "asset", id}` when the author picked the first frame
    instead of having one made. NULL: the take makes it (`image_run_id`).
  - `make_last_frame`, `last_frame` and `last_frame_run_id`: the last frame is made from the
    first frame (`make_last_frame`, then `last_frame_run_id`), or picked (`last_frame`, the same
    shape as `first_frame`). Neither: the clip has no last frame.
  - `audio_input`: `{source: "voice_run" | "voice", id}` when the author picked the speech
    instead of having one made. NULL: the take makes it (`voice_run_id`).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-14 23:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODEL_CHECK = "ck_character_take_video_model_valid"
_OLD_MODEL_CHECK = "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5')"
_NEW_MODEL_CHECK = "video_model IS NULL OR video_model IN ('ltx-2.3', 'ltx-2.5', 'minimax-h3')"
_MARKER_CHECK = "ck_character_take_audio_marker_valid"
_MARKER_RULE = (
    "audio_marker IS NULL OR audio_marker IN "
    "('fully_copy', 'partially_copy', 'reference', 'weak_reference')"
)
_LAST_FRAME_FK = "fk_character_take_last_frame_run_id_lab_run"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("character_take", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_MODEL_CHECK), type_="check")
        batch_op.create_check_constraint(op.f(_MODEL_CHECK), _NEW_MODEL_CHECK)
        batch_op.add_column(sa.Column("audio_marker", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "match_audio_duration", sa.Boolean(), server_default=sa.text("0"), nullable=False
            )
        )
        batch_op.add_column(sa.Column("num_inference_steps", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("identity_refs", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )
        batch_op.add_column(sa.Column("first_frame", sa.JSON(none_as_null=True), nullable=True))
        batch_op.add_column(
            sa.Column("make_last_frame", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )
        batch_op.add_column(sa.Column("last_frame", sa.JSON(none_as_null=True), nullable=True))
        batch_op.add_column(sa.Column("last_frame_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("audio_input", sa.JSON(none_as_null=True), nullable=True))
        batch_op.create_check_constraint(op.f(_MARKER_CHECK), _MARKER_RULE)
        batch_op.create_foreign_key(
            batch_op.f(_LAST_FRAME_FK),
            "lab_run",
            ["last_frame_run_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema. The MiniMax H3 takes are deleted, because the old CHECK would refuse
    them. The runs and jobs they started stay (a take holds the link, not the other way round),
    and so do the pictures, speeches and clips: only the rows that listed them are lost.
    """
    op.execute("DELETE FROM character_take WHERE video_model = 'minimax-h3'")
    with op.batch_alter_table("character_take", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_LAST_FRAME_FK), type_="foreignkey")
        batch_op.drop_constraint(op.f(_MARKER_CHECK), type_="check")
        batch_op.drop_column("audio_input")
        batch_op.drop_column("last_frame_run_id")
        batch_op.drop_column("last_frame")
        batch_op.drop_column("make_last_frame")
        batch_op.drop_column("first_frame")
        batch_op.drop_column("identity_refs")
        batch_op.drop_column("num_inference_steps")
        batch_op.drop_column("match_audio_duration")
        batch_op.drop_column("audio_marker")
        batch_op.drop_constraint(op.f(_MODEL_CHECK), type_="check")
        batch_op.create_check_constraint(op.f(_MODEL_CHECK), _OLD_MODEL_CHECK)
