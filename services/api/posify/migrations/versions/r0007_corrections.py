"""Reviewable corrections without rewriting inspection evidence."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('correction_requests',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('site_id', sa.Text(), sa.ForeignKey('factories.id'), nullable=False),
        sa.Column('entity_kind', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('expected_revision', sa.Integer(), nullable=True),
        sa.Column('before_value', sa.Text(), nullable=False),
        sa.Column('after_value', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('requested_by', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('reviewed_by', sa.Text(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('reviewed_at', sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('pending','approved','rejected')"),
        sa.CheckConstraint("entity_kind IN ('asset_catalog','capture_assignment')"))
    op.create_index('correction_site', 'correction_requests', ['site_id', 'status', 'created_at'])


def downgrade():
    raise RuntimeError('Correction history rollback requires a reviewed backup restore')
