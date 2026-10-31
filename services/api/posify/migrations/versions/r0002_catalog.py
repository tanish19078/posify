"""Separate shared model knowledge from organization-owned installed assets."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

DDL = '''
CREATE TABLE organizations(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE factories(
 id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
 name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE catalog_models(
 id TEXT PRIMARY KEY, identity_key TEXT NOT NULL UNIQUE,
 manufacturer TEXT NOT NULL, model TEXT NOT NULL, variant TEXT NOT NULL,
 category TEXT NOT NULL, source_ref TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','published')), created_at TEXT NOT NULL
);
CREATE TABLE asset_catalog_links(
 asset_id TEXT PRIMARY KEY REFERENCES assets(id),
 catalog_model_id TEXT NOT NULL REFERENCES catalog_models(id), confirmed_at TEXT NOT NULL
);
CREATE TABLE catalog_documents(
 id TEXT PRIMARY KEY, catalog_model_id TEXT NOT NULL REFERENCES catalog_models(id),
 title TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 source_text TEXT NOT NULL, source_ref TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','published')), created_at TEXT NOT NULL,
 UNIQUE(catalog_model_id,title,revision)
);
CREATE INDEX factory_org ON factories(organization_id);
CREATE INDEX model_documents ON catalog_documents(catalog_model_id,status);
'''


def upgrade():
    for statement in DDL.split(';'):
        if statement.strip():
            op.execute(sa.text(statement))
    db = op.get_bind()
    sites = db.execute(sa.text('SELECT site_id FROM assets UNION SELECT site_id FROM procedures '
                              'UNION SELECT site_id FROM captures UNION SELECT site_id FROM audit')).scalars().all()
    if sites:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()
        legacy = '00000000-0000-0000-0000-000000000001'
        db.execute(sa.text('INSERT INTO organizations VALUES(:id,:name,:created)'),
                   {'id': legacy, 'name': 'Legacy sites — ownership review required', 'created': timestamp})
        for site in sites:
            db.execute(sa.text('INSERT INTO factories VALUES(:id,:org,:name,:created)'),
                       {'id': site, 'org': legacy, 'name': site, 'created': timestamp})


def downgrade():
    raise RuntimeError('Catalogue downgrade requires an explicit data retention plan; restore a backup')
