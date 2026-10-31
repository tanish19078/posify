"""Adopt the existing v2 schema without dropping or rewriting data."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "\nCREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);\nINSERT OR IGNORE INTO schema_version VALUES(1);\nCREATE TABLE IF NOT EXISTS assets(\n id TEXT PRIMARY KEY, site_id TEXT NOT NULL, tag TEXT NOT NULL,\n manufacturer TEXT NOT NULL, model TEXT NOT NULL, serial TEXT,\n category TEXT NOT NULL, location TEXT NOT NULL,\n UNIQUE(site_id,tag), UNIQUE(site_id,serial)\n);\nCREATE TABLE IF NOT EXISTS procedures(\n id TEXT PRIMARY KEY, site_id TEXT NOT NULL, manufacturer TEXT NOT NULL,\n model TEXT NOT NULL, title TEXT NOT NULL, version INTEGER NOT NULL,\n steps TEXT NOT NULL, source_text TEXT NOT NULL,\n UNIQUE(site_id,manufacturer,model,title,version)\n);\nCREATE TABLE IF NOT EXISTS inspections(\n id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),\n procedure_id TEXT NOT NULL REFERENCES procedures(id),\n status TEXT NOT NULL CHECK(status IN ('open','submitted')),\n created_at TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS observations(\n id TEXT PRIMARY KEY, inspection_id TEXT NOT NULL REFERENCES inspections(id),\n step_id TEXT NOT NULL, result TEXT NOT NULL, note TEXT NOT NULL,\n UNIQUE(inspection_id,step_id)\n);\nCREATE TABLE IF NOT EXISTS audit(\n sequence INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT NOT NULL,\n kind TEXT NOT NULL, entity_id TEXT NOT NULL, created_at TEXT NOT NULL,\n payload TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS captures(\n id TEXT PRIMARY KEY, site_id TEXT NOT NULL, sha256 TEXT NOT NULL,\n width INTEGER NOT NULL, height INTEGER NOT NULL, warnings TEXT NOT NULL,\n created_at TEXT NOT NULL, UNIQUE(site_id,sha256)\n);\nCREATE TABLE IF NOT EXISTS capture_analyses(\n id TEXT PRIMARY KEY, capture_id TEXT NOT NULL REFERENCES captures(id),\n created_at TEXT NOT NULL, result TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS capture_assignments(\n capture_id TEXT PRIMARY KEY REFERENCES captures(id),\n asset_id TEXT NOT NULL REFERENCES assets(id), confirmed_at TEXT NOT NULL\n);\nCREATE TABLE IF NOT EXISTS inspection_evidence(\n inspection_id TEXT NOT NULL REFERENCES inspections(id),\n capture_id TEXT NOT NULL REFERENCES captures(id),\n PRIMARY KEY(inspection_id,capture_id)\n);\nINSERT OR IGNORE INTO schema_version VALUES(2);\nCREATE INDEX IF NOT EXISTS capture_site ON captures(site_id);\nCREATE INDEX IF NOT EXISTS asset_site ON assets(site_id);\nCREATE INDEX IF NOT EXISTS audit_site ON audit(site_id,sequence);\n"


def upgrade():
    postgres = op.get_bind().dialect.name == 'postgresql'
    for statement in SCHEMA.split(';'):
        statement = statement.strip()
        if not statement:
            continue
        if postgres:
            statement = statement.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
            if statement.startswith('INSERT OR IGNORE'):
                statement = statement.replace('INSERT OR IGNORE', 'INSERT') + ' ON CONFLICT DO NOTHING'
        op.execute(sa.text(statement))


def downgrade():
    raise RuntimeError('Baseline downgrade is intentionally unsupported; restore a verified backup')
