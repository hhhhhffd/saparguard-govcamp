"""Add uploaded media attachments for citizen complaints."""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0014"
down_revision = "20260719_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "complaint_media",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("complaint_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["complaint_id"], ["complaints.id"], ondelete="CASCADE", name="fk_complaint_media_complaint_id_complaints"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_complaint_media"),
    )
    op.create_index("ix_complaint_media_complaint_id", "complaint_media", ["complaint_id"])


def downgrade() -> None:
    op.drop_index("ix_complaint_media_complaint_id", table_name="complaint_media")
    op.drop_table("complaint_media")
