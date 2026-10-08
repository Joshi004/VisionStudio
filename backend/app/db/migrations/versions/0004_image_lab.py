"""image lab

Phase 13: the two tables behind the Image lab page, where Bitdeer's image API is tested by
hand. `lab_run` is one call (the exact request, the raw response, the timing and the usage),
and `lab_image` is an image the lab holds (an upload, or a result of a run). Nothing existing
changes, so these are plain `create_table` calls.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08 13:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "lab_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("reference_images", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("seconds", sa.REAL(), nullable=True),
        sa.Column("request_bytes", sa.Integer(), nullable=True),
        sa.Column("usage", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(none_as_null=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('text_to_image', 'image_to_image', 'edit')",
            name=op.f("ck_lab_run_mode_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')", name=op.f("ck_lab_run_status_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_run")),
    )
    with op.batch_alter_table("lab_run", schema=None) as batch_op:
        batch_op.create_index("idx_lab_run_created", ["created_at"], unique=False)

    op.create_table(
        "lab_image",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            UTCDateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("output_index", sa.Integer(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "origin IN ('upload', 'result')", name=op.f("ck_lab_image_origin_valid")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["lab_run.id"],
            name=op.f("fk_lab_image_run_id_lab_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_image")),
    )
    with op.batch_alter_table("lab_image", schema=None) as batch_op:
        batch_op.create_index("idx_lab_image_created", ["created_at"], unique=False)
        batch_op.create_index("idx_lab_image_run", ["run_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("lab_image", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_image_run")
        batch_op.drop_index("idx_lab_image_created")
    op.drop_table("lab_image")
    with op.batch_alter_table("lab_run", schema=None) as batch_op:
        batch_op.drop_index("idx_lab_run_created")
    op.drop_table("lab_run")
