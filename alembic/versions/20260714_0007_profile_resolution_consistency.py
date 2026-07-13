"""Finalize semantic profile-resolution sources and timestamps."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260714_0007"
down_revision = "20260714_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profile_relation_observations", sa.Column("observed_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "profile_vehicle_link_observations", sa.Column("observed_at", sa.DateTime(timezone=True))
    )
    op.add_column("vehicle_observations", sa.Column("observed_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE profile_relation_observations source SET observed_at = message.published_at "
        "FROM telegram_messages message WHERE message.id = source.message_id"
    )
    op.execute(
        "UPDATE profile_vehicle_link_observations source SET observed_at = message.published_at "
        "FROM telegram_messages message WHERE message.id = source.message_id"
    )
    op.execute(
        "UPDATE vehicle_observations source SET observed_at = message.published_at "
        "FROM telegram_messages message WHERE message.id = source.message_id"
    )
    op.alter_column("profile_relation_observations", "observed_at", nullable=False)
    op.alter_column("profile_vehicle_link_observations", "observed_at", nullable=False)
    op.alter_column("vehicle_observations", "observed_at", nullable=False)
    op.create_table(
        "profile_shared_vehicle_observations",
        sa.Column(
            "left_profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), nullable=False
        ),
        sa.Column(
            "right_profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), nullable=False
        ),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "left_profile_id < right_profile_id", name="ck_profile_shared_vehicle_pair"
        ),
        sa.PrimaryKeyConstraint("left_profile_id", "right_profile_id", "vehicle_id"),
    )
    for table, columns in (
        ("profile_relation_observations", ["message_id", "left_profile_id", "right_profile_id"]),
        ("profile_vehicle_link_observations", ["message_id", "vehicle_id", "profile_id"]),
        ("vehicle_observations", ["message_id", "vehicle_id", "observed_at"]),
        (
            "profile_shared_vehicle_observations",
            ["vehicle_id", "left_profile_id", "right_profile_id"],
        ),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table, columns in (
        (
            "profile_shared_vehicle_observations",
            ["vehicle_id", "left_profile_id", "right_profile_id"],
        ),
        ("vehicle_observations", ["message_id", "vehicle_id", "observed_at"]),
        ("profile_vehicle_link_observations", ["message_id", "vehicle_id", "profile_id"]),
        ("profile_relation_observations", ["message_id", "left_profile_id", "right_profile_id"]),
    ):
        for column in columns:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
    op.drop_table("profile_shared_vehicle_observations")
    op.drop_column("vehicle_observations", "observed_at")
    op.drop_column("profile_vehicle_link_observations", "observed_at")
    op.drop_column("profile_relation_observations", "observed_at")
