"""Create durable configuration and audit tables."""
from alembic import op

from hats_api.storage import Base

revision = "0001_durable_configuration"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
