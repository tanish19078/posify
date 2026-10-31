"""Enforce factory references on legacy tables without rebuilding SQLite data."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        for table in ('assets', 'procedures', 'captures'):
            op.execute(sa.text(f'ALTER TABLE {table} ADD CONSTRAINT fk_{table}_factory FOREIGN KEY (site_id) REFERENCES factories(id)'))
    else:
        for table in ('assets', 'procedures', 'captures'):
            for operation in ('INSERT', 'UPDATE OF site_id'):
                name = operation.split()[0].lower()
                op.execute(sa.text(f'''CREATE TRIGGER {table}_factory_{name} BEFORE {operation} ON {table}
                  WHEN NOT EXISTS (SELECT 1 FROM factories WHERE id=NEW.site_id)
                  BEGIN SELECT RAISE(ABORT, 'Factory is not registered'); END'''))
        op.execute(sa.text('''CREATE TRIGGER factory_restrict_delete BEFORE DELETE ON factories
          WHEN EXISTS(SELECT 1 FROM assets WHERE site_id=OLD.id)
            OR EXISTS(SELECT 1 FROM procedures WHERE site_id=OLD.id)
            OR EXISTS(SELECT 1 FROM captures WHERE site_id=OLD.id)
          BEGIN SELECT RAISE(ABORT, 'Factory still owns records'); END'''))


def downgrade():
    raise RuntimeError('Removing ownership constraints requires explicit review')
