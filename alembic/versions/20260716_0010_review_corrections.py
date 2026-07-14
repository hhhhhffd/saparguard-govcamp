"""Preserve review provenance and conflict identity."""

from alembic import op
import sqlalchemy as sa


revision = "20260716_0010"
down_revision = "20260715_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("message_annotations", sa.Column("source_text_hash", sa.String(64)))
    op.execute("UPDATE message_annotations SET source_text_hash = repeat('0', 64)")
    op.alter_column("message_annotations", "source_text_hash", nullable=False)
    op.add_column("profile_resolution_conflicts", sa.Column("conflict_key", sa.String(128)))
    op.execute("UPDATE profile_resolution_conflicts SET conflict_key = 'legacy:' || id::text")
    op.alter_column("profile_resolution_conflicts", "conflict_key", nullable=False)
    op.create_unique_constraint(
        "uq_profile_resolution_conflicts_key", "profile_resolution_conflicts", ["conflict_key"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_profile_resolution_conflicts_key", "profile_resolution_conflicts", type_="unique"
    )
    op.drop_column("profile_resolution_conflicts", "conflict_key")
    op.drop_column("message_annotations", "source_text_hash")
