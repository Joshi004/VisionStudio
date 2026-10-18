"""MiniMax H3 reference clips take a list of audios, and the audio is optional

GPU API 0.14.0 replaced the single `audio_asset_id` of `POST /v1/h3/videos/audio-to-video` by the
list `audio_asset_ids` (up to 3), and 0.15.0 keeps it optional. `lab_video_run` follows:

- `audio_references`: the audios a MiniMax H3 reference clip was made from, in the order the
  prompt names them (`<Audio 1>`, `<Audio 2>`), as a list of `{source: "voice_run" | "voice",
  id}`. NULL for every other clip and for a reference clip with no audio. The runs made before
  this revision get a list of the one audio they had, so a reference clip is always read from
  this column. `audio_input` stays: for a reference clip it holds the first audio (or NULL), and
  for a lip-synced LTX clip its one speech.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-18 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audio_references", sa.JSON(none_as_null=True), nullable=True)
        )
    # A MiniMax H3 reference run is the one that has pictures (`references`, a reserved word in
    # SQL, so it is quoted) and its one audio reference.
    op.execute(
        "UPDATE lab_video_run SET audio_references = json_array(json(audio_input)) "
        'WHERE "references" IS NOT NULL AND audio_input IS NOT NULL'
    )


def downgrade() -> None:
    """Downgrade schema. A reference clip with no audio, or with two, keeps only its first audio
    in `audio_input` (already there), so nothing is needed beyond dropping the column.
    """
    with op.batch_alter_table("lab_video_run", schema=None) as batch_op:
        batch_op.drop_column("audio_references")
