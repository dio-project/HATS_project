"""Add input-window provenance to feature snapshots."""
import sqlalchemy as sa
from alembic import op

revision = "0003_feature_input_provenance"
down_revision = "0002_feature_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("feature_snapshots")}
    if "input_window_start_utc" not in columns:
        op.add_column(
            "feature_snapshots",
            sa.Column("input_window_start_utc", sa.String(length=40), nullable=True),
        )
    if "input_digest" not in columns:
        op.add_column(
            "feature_snapshots",
            sa.Column("input_digest", sa.String(length=64), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("feature_snapshots")}
    if "input_digest" in columns:
        op.drop_column("feature_snapshots", "input_digest")
    if "input_window_start_utc" in columns:
        op.drop_column("feature_snapshots", "input_window_start_utc")
