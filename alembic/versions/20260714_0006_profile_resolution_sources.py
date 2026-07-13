"""Make profile aggregates source-aware and vehicle signatures stable."""

from alembic import op
import sqlalchemy as sa

revision = "20260714_0006"
down_revision = "20260714_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("profile_signature_key", sa.String(64)))
    op.create_index(
        "uq_vehicles_profile_signature_key",
        "vehicles",
        ["profile_signature_key"],
        unique=True,
        postgresql_where=sa.text("profile_signature_key IS NOT NULL"),
    )
    op.create_table(
        "profile_relation_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "left_profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), nullable=False
        ),
        sa.Column(
            "right_profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), nullable=False
        ),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column(
            "message_id", sa.Integer(), sa.ForeignKey("telegram_messages.id"), nullable=False
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "left_profile_id < right_profile_id", name="ck_profile_relation_observations_pair"
        ),
        sa.UniqueConstraint("left_profile_id", "right_profile_id", "relation_type", "message_id"),
    )
    op.create_table(
        "profile_vehicle_link_observations",
        sa.Column(
            "profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), primary_key=True
        ),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id"), primary_key=True),
        sa.Column(
            "message_id", sa.Integer(), sa.ForeignKey("telegram_messages.id"), primary_key=True
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("profile_vehicle_link_observations")
    op.drop_table("profile_relation_observations")
    op.drop_index("uq_vehicles_profile_signature_key", table_name="vehicles")
    op.drop_column("vehicles", "profile_signature_key")
