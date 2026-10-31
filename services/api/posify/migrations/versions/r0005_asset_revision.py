"""Version installed asset metadata for optimistic concurrency control."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('assets', sa.Column('revision', sa.Integer(), nullable=False, server_default='1'))


def downgrade():
    raise RuntimeError('Removing asset revisions requires explicit review')
