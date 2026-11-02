"""Merge the market-data and feature-snapshot migration branches."""

revision = "0004_merge_heads"
down_revision = ("0002_market_data", "0003_feature_input_provenance")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
