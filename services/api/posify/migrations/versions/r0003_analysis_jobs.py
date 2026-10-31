"""Durable capture jobs with bounded retries and fencing tokens."""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text('''CREATE TABLE analysis_jobs(
      id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES factories(id),
      capture_id TEXT NOT NULL REFERENCES captures(id),
      mode TEXT NOT NULL CHECK(mode IN ('ocr','detect_ocr')),
      status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
      attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
      available_at DOUBLE PRECISION NOT NULL, lease_until DOUBLE PRECISION,
      claim_token TEXT, result TEXT, error_code TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )'''))
    op.execute(sa.text('CREATE INDEX job_claim ON analysis_jobs(status,available_at,lease_until)'))
    op.execute(sa.text('CREATE INDEX job_site ON analysis_jobs(site_id,created_at)'))


def downgrade():
    raise RuntimeError('Drain and archive job records before a manually reviewed downgrade')
