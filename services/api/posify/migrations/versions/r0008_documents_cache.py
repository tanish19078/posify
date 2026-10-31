"""Page-preserving PDF imports and persistent passage embeddings."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('document_imports',
        sa.Column('document_id', sa.Text(), sa.ForeignKey('catalog_documents.id'), primary_key=True),
        sa.Column('sha256', sa.Text(), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=False),
        sa.Column('empty_pages', sa.Text(), nullable=False))
    op.create_table('document_pages',
        sa.Column('document_id', sa.Text(), sa.ForeignKey('catalog_documents.id'), primary_key=True),
        sa.Column('page_number', sa.Integer(), primary_key=True),
        sa.Column('source_text', sa.Text(), nullable=False))
    op.create_table('embedding_cache',
        sa.Column('namespace', sa.Text(), primary_key=True),
        sa.Column('passage_hash', sa.Text(), primary_key=True),
        sa.Column('vector', sa.Text(), nullable=False))


def downgrade():
    raise RuntimeError('Document and embedding cache rollback requires explicit review')
