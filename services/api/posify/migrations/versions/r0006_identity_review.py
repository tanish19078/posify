"""Individual credentials, factory membership and immutable inspection reviews."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('active', sa.Integer(), nullable=False),
        sa.Column('is_admin', sa.Integer(), nullable=False),
        sa.Column('is_curator', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False))
    op.create_table('user_tokens',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('user_id', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('digest', sa.Text(), nullable=False, unique=True),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.Column('revoked', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False))
    op.create_table('factory_memberships',
        sa.Column('user_id', sa.Text(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('site_id', sa.Text(), sa.ForeignKey('factories.id'), primary_key=True),
        sa.Column('role', sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('viewer','technician','supervisor','manager')"))
    op.add_column('audit', sa.Column('actor_id', sa.Text(), nullable=True))
    op.add_column('audit', sa.Column('actor_type', sa.Text(), nullable=False, server_default='legacy'))
    op.add_column('inspections', sa.Column('created_by', sa.Text(), nullable=True))
    op.add_column('inspections', sa.Column('submitted_by', sa.Text(), nullable=True))
    op.create_table('inspection_reviews',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('inspection_id', sa.Text(), sa.ForeignKey('inspections.id'), nullable=False, unique=True),
        sa.Column('reviewer_id', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('outcome', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.CheckConstraint("outcome IN ('accepted','follow_up')"))
    op.create_index('audit_entity', 'audit', ['site_id', 'entity_id', 'sequence'])


def downgrade():
    raise RuntimeError('Identity and review rollback requires a reviewed backup restore')
