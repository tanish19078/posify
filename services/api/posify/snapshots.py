"""Portable, integrity-checked application snapshots; restore only into empty stores."""
import hashlib
import json
import re
import shutil
from pathlib import Path

import sqlalchemy as sa

from posify.audit import timestamp

TABLES = {
    'organizations', 'factories', 'assets', 'procedures', 'inspections', 'observations', 'audit',
    'captures', 'capture_analyses', 'capture_assignments', 'inspection_evidence',
    'catalog_models', 'asset_catalog_links', 'catalog_documents', 'analysis_jobs',
    'users', 'user_tokens', 'factory_memberships', 'inspection_reviews', 'correction_requests',
    'document_imports', 'document_pages', 'embedding_cache',
}


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def metadata(database):
    schema = sa.MetaData()
    schema.reflect(database.engine, only=sorted(TABLES))
    # Legacy SQLite ownership uses triggers, which reflection cannot infer as FKs.
    # Add metadata-only dependencies so factories restore before owned records.
    for name in ('assets', 'procedures', 'captures'):
        table = schema.tables[name]
        if not any(key.column.table.name == 'factories' for key in table.foreign_keys):
            table.append_constraint(sa.ForeignKeyConstraint(['site_id'], ['factories.id']))
    return schema


def private_json(path, data):
    with path.open('x', encoding='utf-8') as handle:
        path.chmod(0o600)
        json.dump(data, handle, ensure_ascii=False, allow_nan=False)
        handle.write('\n')


def snapshot(database, captures, documents, output):
    output = Path(output)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    schema = metadata(database)
    with database.connect() as db:
        db.execute('BEGIN')
        revision = db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']
        tables = {table.name: [dict(row) for row in db.connection.execute(sa.select(table)).mappings()]
                  for table in schema.sorted_tables}
        private_json(output / 'database.json', tables)
        files = {'database.json': digest(output / 'database.json')}
        for folder, root, keys, suffix in [
            ('captures', Path(captures), {r['sha256'] for r in tables['captures']}, '.png'),
            ('documents', Path(documents), {r['sha256'] for r in tables['document_imports']}, '.pdf'),
        ]:
            (output / folder).mkdir(mode=0o700)
            for key in sorted(keys):
                if not re.fullmatch('[0-9a-f]{64}', key):
                    raise ValueError('Invalid stored content hash')
                source = root / (key + suffix)
                if digest(source) != key:
                    raise ValueError('Stored evidence digest mismatch')
                target = output / folder / source.name
                shutil.copyfile(source, target)
                target.chmod(0o600)
                files[folder + '/' + source.name] = key
        private_json(output / 'manifest.json', {'format': 1, 'revision': revision,
                      'created_at': timestamp(), 'row_counts': {name: len(rows) for name, rows in tables.items()}, 'files': files})
    return {'revision': revision, 'row_counts': {name: len(rows) for name, rows in tables.items()}, 'files': len(files)}


def restore(database, captures, documents, source):
    source = Path(source)
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest.get('format') != 1:
        raise ValueError('Unsupported snapshot format')
    for relative, expected in manifest['files'].items():
        if relative != 'database.json' and not re.fullmatch(r'(captures/[0-9a-f]{64}\.png|documents/[0-9a-f]{64}\.pdf)', relative):
            raise ValueError('Invalid snapshot file path')
        if relative != 'database.json' and expected != Path(relative).stem:
            raise ValueError('Evidence digest must match its content-addressed filename')
        path = source / relative
        if not path.resolve().is_relative_to(source.resolve()) or digest(path) != expected:
            raise ValueError('Snapshot file integrity check failed')
    if 'database.json' not in manifest['files']:
        raise ValueError('Missing snapshot database digest')
    tables = json.loads((source / 'database.json').read_text())
    if set(tables) != TABLES:
        raise ValueError('Snapshot table set does not match this application version')
    for name, rows in tables.items():
        if manifest['row_counts'].get(name) != len(rows):
            raise ValueError('Snapshot row count mismatch')
    expected_files = {'database.json'}
    expected_files.update('captures/' + row['sha256'] + '.png' for row in tables['captures'])
    expected_files.update('documents/' + row['sha256'] + '.pdf' for row in tables['document_imports'])
    if expected_files != set(manifest['files']):
        raise ValueError('Snapshot evidence manifest does not match database references')
    schema = metadata(database)
    for root in [Path(captures), Path(documents)]:
        if root.exists() and any(root.iterdir()):
            raise ValueError('Restore evidence directories must be empty')
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        revision = db.execute('SELECT version_num FROM alembic_version').fetchone()['version_num']
        if revision != manifest['revision']:
            raise ValueError('Migrate the restore target to the snapshot schema revision first')
        for table in schema.sorted_tables:
            if db.connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one():
                raise ValueError('Restore database must be empty')
            if any(set(row) != set(table.columns.keys()) for row in tables[table.name]):
                raise ValueError('Snapshot columns do not match schema')
        for table in schema.sorted_tables:
            rows = tables[table.name]
            for offset in range(0, len(rows), 500):
                db.connection.execute(table.insert(), rows[offset:offset + 500])
        if database.dialect == 'postgresql':
            sequence = db.execute("SELECT pg_get_serial_sequence('audit','sequence') AS name").fetchone()['name']
            maximum = max((row['sequence'] for row in tables['audit']), default=0)
            db.execute('SELECT setval(CAST(? AS regclass),?,?)', (sequence, max(1, maximum), bool(maximum)))
        for folder, root in [('captures', Path(captures)), ('documents', Path(documents))]:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            for relative in sorted(manifest['files']):
                if relative.startswith(folder + '/'):
                    target = root / Path(relative).name
                    with target.open('xb') as handle, (source / relative).open('rb') as original:
                        target.chmod(0o600)
                        shutil.copyfileobj(original, handle)
    return {'revision': revision, 'row_counts': manifest['row_counts']}
