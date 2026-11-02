"""Create immutable feature snapshot storage."""
import sqlalchemy as sa
from alembic import op

revision = "0002_feature_snapshots"
down_revision = "0001_durable_configuration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("feature_snapshots"):
        op.create_table(
            "feature_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("schema_version", sa.Integer(), nullable=False),
            sa.Column("feature_set_version", sa.String(length=40), nullable=False),
            sa.Column("symbol", sa.String(length=20), nullable=False),
            sa.Column("timeframe", sa.String(length=8), nullable=False),
            sa.Column("source", sa.String(length=100), nullable=False),
            sa.Column("candle_open_time_utc", sa.String(length=40), nullable=False),
            sa.Column("candle_close_time_utc", sa.String(length=40), nullable=False),
            sa.Column("input_count", sa.Integer(), nullable=False),
            sa.Column("feature_json", sa.Text(), nullable=False),
            sa.Column("feature_digest", sa.String(length=64), nullable=False),
            sa.Column("computed_at_utc", sa.String(length=40), nullable=False),
            sa.UniqueConstraint(
                "symbol", "timeframe", "source", "candle_close_time_utc",
                "feature_set_version", name="uq_feature_snapshot_input_version",
            ),
        )
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("feature_snapshots")}
    if "ix_feature_snapshots_lookup" not in indexes:
        op.create_index(
            "ix_feature_snapshots_lookup",
            "feature_snapshots",
            ["symbol", "timeframe", "source", "id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("feature_snapshots"):
        indexes = {item["name"] for item in inspector.get_indexes("feature_snapshots")}
        if "ix_feature_snapshots_lookup" in indexes:
            op.drop_index("ix_feature_snapshots_lookup", table_name="feature_snapshots")
        op.drop_table("feature_snapshots")
