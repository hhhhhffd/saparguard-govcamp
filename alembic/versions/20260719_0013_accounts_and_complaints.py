"""Add application accounts, complaints and status history."""

from alembic import op
import sqlalchemy as sa


revision = "20260719_0013"
down_revision = "20260718_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("normalized_email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("google_account_id", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("registration_source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('citizen', 'worker', 'admin')", name="ck_app_users_role"),
        sa.CheckConstraint(
            "registration_source IN ('local', 'google')",
            name="ck_app_users_registration_source",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_app_users"),
        sa.UniqueConstraint("google_account_id", name="uq_app_users_google_account_id"),
        sa.UniqueConstraint("normalized_email", name="uq_app_users_normalized_email"),
    )
    op.create_table(
        "complaints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_changed_by_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'resolved', 'rejected')",
            name="ck_complaints_status",
        ),
        sa.ForeignKeyConstraint(["author_id"], ["app_users.id"], name="fk_complaints_author_id_app_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["status_changed_by_id"], ["app_users.id"], name="fk_complaints_status_changed_by_id_app_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_complaints"),
    )
    op.create_index("ix_complaints_author_id", "complaints", ["author_id"])
    op.create_table(
        "complaint_status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("complaint_id", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(length=16), nullable=True),
        sa.Column("new_status", sa.String(length=16), nullable=False),
        sa.Column("changed_by_id", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("old_status IS NULL OR old_status IN ('new', 'in_progress', 'resolved', 'rejected')", name="ck_complaint_status_history_old_status"),
        sa.CheckConstraint("new_status IN ('new', 'in_progress', 'resolved', 'rejected')", name="ck_complaint_status_history_new_status"),
        sa.ForeignKeyConstraint(["changed_by_id"], ["app_users.id"], name="fk_complaint_status_history_changed_by_id_app_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], name="fk_complaint_status_history_complaint_id_complaints", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_complaint_status_history"),
    )
    op.create_index("ix_complaint_status_history_complaint_id", "complaint_status_history", ["complaint_id"])


def downgrade() -> None:
    op.drop_index("ix_complaint_status_history_complaint_id", table_name="complaint_status_history")
    op.drop_table("complaint_status_history")
    op.drop_index("ix_complaints_author_id", table_name="complaints")
    op.drop_table("complaints")
    op.drop_table("app_users")
