"""Worker heartbeat tracking for operational readiness."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'worker_heartbeats',
        sa.Column('worker_id', sa.Text(), primary_key=True),
        sa.Column('hostname', sa.Text(), nullable=False),
        sa.Column('pid', sa.Integer(), nullable=False),
        sa.Column('ocr_engine', sa.Text(), nullable=False),
        sa.Column('detector_revision', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('jobs_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_seen_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
    )


def downgrade():
    raise RuntimeError('Worker heartbeat rollback requires explicit review')
