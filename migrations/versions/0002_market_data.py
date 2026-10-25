"""Add durable market candle and quality-event tables."""
import sqlalchemy as sa
from alembic import op

revision = "0002_market_data"
down_revision = "0001_durable_configuration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_candles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("open_time_utc", sa.String(length=40), nullable=False),
        sa.Column("close_time_utc", sa.String(length=40), nullable=False),
        sa.Column("open", sa.String(length=40), nullable=False),
        sa.Column("high", sa.String(length=40), nullable=False),
        sa.Column("low", sa.String(length=40), nullable=False),
        sa.Column("close", sa.String(length=40), nullable=False),
        sa.Column("volume", sa.String(length=40), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("source_timestamp", sa.String(length=100), nullable=True),
        sa.Column("source_timezone", sa.String(length=100), nullable=True),
        sa.Column("ingested_at", sa.String(length=40), nullable=False),
        sa.UniqueConstraint(
            "symbol", "timeframe", "source", "open_time_utc",
            name="uq_market_candle_source_bar",
        ),
    )
    op.create_index(
        "ix_market_candles_symbol_time", "market_candles",
        ["symbol", "timeframe", "open_time_utc"],
    )
    op.create_table(
        "market_data_quality_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_at", sa.String(length=40), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_data_quality_events")
    op.drop_index("ix_market_candles_symbol_time", table_name="market_candles")
    op.drop_table("market_candles")
