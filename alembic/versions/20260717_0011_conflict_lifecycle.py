"""Backfill stable conflict keys and retain resolved conflict history."""

from alembic import op


revision = "20260717_0011"
down_revision = "20260716_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE profile_resolution_conflicts "
        "SET conflict_key = md5(message_id::text || ':' || conflict_type || ':' || details::text)"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE profile_resolution_conflicts "
        "SET conflict_key = 'legacy:' || id::text "
        "WHERE conflict_key IS NOT NULL"
    )
