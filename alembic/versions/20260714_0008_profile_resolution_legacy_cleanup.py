"""Remove legacy message-scoped shared vehicle relations."""

from alembic import op


revision = "20260714_0008"
down_revision = "20260714_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM profile_relation_observations WHERE relation_type = 'shared_vehicle'")
    op.execute("DELETE FROM profile_relations WHERE relation_type = 'shared_vehicle'")


def downgrade() -> None:
    # Legacy shared-vehicle rows cannot be reconstructed without guessing.
    pass
