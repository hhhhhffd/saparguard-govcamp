"""Add observed transport profiles and vehicles."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260714_0005"
down_revision = "20260714_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transport_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_kind", sa.String(32), nullable=False),
        sa.Column("canonical_label", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("active_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("resolver_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "profile_identifiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), nullable=False
        ),
        sa.Column("identifier_type", sa.String(32), nullable=False),
        sa.Column("identifier_role", sa.String(32), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), sa.ForeignKey("telegram_messages.id")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_profile_identifiers_type_normalized",
        "profile_identifiers",
        ["identifier_type", "normalized_value"],
    )
    op.create_index(
        "ix_profile_identifiers_profile_type",
        "profile_identifiers",
        ["profile_id", "identifier_type"],
    )
    op.create_index(
        "uq_profile_phone_anchor",
        "profile_identifiers",
        ["normalized_value"],
        unique=True,
        postgresql_where=sa.text("identifier_type = 'phone' AND identifier_role = 'anchor'"),
    )
    op.create_index(
        "uq_profile_telegram_anchor",
        "profile_identifiers",
        ["normalized_value"],
        unique=True,
        postgresql_where=sa.text(
            "identifier_type = 'telegram_user_id' AND identifier_role = 'anchor'"
        ),
    )
    op.create_table(
        "profile_occurrences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), nullable=False
        ),
        sa.Column(
            "message_id", sa.Integer(), sa.ForeignKey("telegram_messages.id"), nullable=False
        ),
        sa.Column("match_method", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("source_deleted", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile_id", "message_id"),
    )
    op.create_table(
        "profile_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "left_profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), nullable=False
        ),
        sa.Column(
            "right_profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), nullable=False
        ),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "left_profile_id < right_profile_id", name="ck_profile_relations_canonical_pair"
        ),
        sa.UniqueConstraint("left_profile_id", "right_profile_id", "relation_type"),
    )
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_kind", sa.String(32), nullable=False),
        sa.Column("normalized_plate", sa.String(128), unique=True),
        sa.Column("make", sa.String(128)),
        sa.Column("model", sa.String(128)),
        sa.Column("generation", sa.String(128)),
        sa.Column("year", sa.Integer()),
        sa.Column("canonical_label", sa.String(255), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "vehicle_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column(
            "message_id", sa.Integer(), sa.ForeignKey("telegram_messages.id"), nullable=False
        ),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id")),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("extracted_entity_id", sa.Integer(), sa.ForeignKey("extracted_entities.id")),
        sa.Column("plate_detection_id", sa.Integer(), sa.ForeignKey("plate_detections.id")),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "vehicle_id",
            "message_id",
            "source_type",
            "extracted_entity_id",
            name="uq_vehicle_observation_text_source",
        ),
        sa.UniqueConstraint(
            "vehicle_id",
            "message_id",
            "source_type",
            "plate_detection_id",
            name="uq_vehicle_observation_plate_source",
        ),
    )
    op.create_table(
        "profile_vehicle_links",
        sa.Column(
            "profile_id", sa.Integer(), sa.ForeignKey("transport_profiles.id"), primary_key=True
        ),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id"), primary_key=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "profile_resolution_conflicts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "message_id", sa.Integer(), sa.ForeignKey("telegram_messages.id"), nullable=False
        ),
        sa.Column("conflict_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_profile_resolution_conflicts_message_id", "profile_resolution_conflicts", ["message_id"]
    )
    op.create_table(
        "profile_resolution_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("telegram_messages.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("resolver_version", sa.String(64), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_profile_resolution_jobs_pending",
        "profile_resolution_jobs",
        ["status", "next_retry_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_resolution_jobs_pending", table_name="profile_resolution_jobs")
    op.drop_table("profile_resolution_jobs")
    op.drop_index(
        "ix_profile_resolution_conflicts_message_id", table_name="profile_resolution_conflicts"
    )
    op.drop_table("profile_resolution_conflicts")
    op.drop_table("profile_vehicle_links")
    op.drop_table("vehicle_observations")
    op.drop_table("vehicles")
    op.drop_table("profile_relations")
    op.drop_table("profile_occurrences")
    op.drop_index("uq_profile_telegram_anchor", table_name="profile_identifiers")
    op.drop_index("uq_profile_phone_anchor", table_name="profile_identifiers")
    op.drop_index("ix_profile_identifiers_profile_type", table_name="profile_identifiers")
    op.drop_index("ix_profile_identifiers_type_normalized", table_name="profile_identifiers")
    op.drop_table("profile_identifiers")
    op.drop_table("transport_profiles")
