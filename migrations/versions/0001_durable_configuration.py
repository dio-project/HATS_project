"""Create durable configuration and audit tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_durable_configuration"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "configuration_snapshots",
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
    )
    op.create_table(
        "app_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("active_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["active_version"], ["configuration_snapshots.version"]
        ),
    )
    op.create_table(
        "configuration_drafts",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("at", sa.String(length=64), nullable=False),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("configuration_drafts")
    op.drop_table("app_state")
    op.drop_table("configuration_snapshots")
