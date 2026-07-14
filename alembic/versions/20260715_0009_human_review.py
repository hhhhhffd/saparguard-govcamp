"""Add independent human annotations and non-destructive conflict decisions."""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0009"
down_revision = "20260714_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_annotations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "message_id", sa.Integer(), sa.ForeignKey("telegram_messages.id"), nullable=False
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("annotator", sa.String(255), nullable=False),
        sa.Column("expected_message_type", sa.String(32)),
        sa.Column("comment", sa.Text()),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('draft', 'reviewed', 'skipped')", name="ck_annotation_status"
        ),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index("ix_message_annotations_status", "message_annotations", ["status"])
    op.create_table(
        "annotation_phones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "annotation_id", sa.Integer(), sa.ForeignKey("message_annotations.id"), nullable=False
        ),
        sa.Column("normalized_value", sa.String(32), nullable=False),
        sa.UniqueConstraint("annotation_id", "normalized_value"),
    )
    op.create_table(
        "annotation_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "annotation_id", sa.Integer(), sa.ForeignKey("message_annotations.id"), nullable=False
        ),
        sa.Column("normalized_origin", sa.String(255), nullable=False),
        sa.Column("normalized_destination", sa.String(255), nullable=False),
        sa.UniqueConstraint("annotation_id", "normalized_origin", "normalized_destination"),
    )
    op.create_table(
        "annotation_vehicles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "annotation_id", sa.Integer(), sa.ForeignKey("message_annotations.id"), nullable=False
        ),
        sa.Column("normalized_value", sa.String(255), nullable=False),
        sa.UniqueConstraint("annotation_id", "normalized_value"),
    )
    op.add_column("profile_resolution_conflicts", sa.Column("decision_comment", sa.Text()))
    op.add_column("profile_resolution_conflicts", sa.Column("decided_by", sa.String(255)))
    op.add_column(
        "profile_resolution_conflicts", sa.Column("decided_at", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    op.drop_column("profile_resolution_conflicts", "decided_at")
    op.drop_column("profile_resolution_conflicts", "decided_by")
    op.drop_column("profile_resolution_conflicts", "decision_comment")
    op.drop_table("annotation_vehicles")
    op.drop_table("annotation_routes")
    op.drop_table("annotation_phones")
    op.drop_index("ix_message_annotations_status", table_name="message_annotations")
    op.drop_table("message_annotations")
