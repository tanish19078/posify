from contextlib import contextmanager
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from posify.audit import record_event
from posify.database import Database
from posify.snapshots import snapshot, restore
from test_api import client, setup_records
from test_catalog import create_model
from test_captures import upload
from test_documents import import_pdf, pdf_bytes
from test_security import person


@contextmanager
def empty_target(tmp_path):
    configured = os.getenv('POSIFY_TEST_DATABASE_URL')
    if not configured:
        database = Database(str(tmp_path / 'restored.db'))
        try:
            yield database
        finally:
            database.engine.dispose()
        return
    url = make_url(configured).set(drivername='postgresql+psycopg')
    schema = 'restore_' + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text('CREATE SCHEMA "' + schema + '"'))
    database = Database(str(tmp_path / 'restored.db'), url=url.update_query_dict({'options': '-csearch_path=' + schema}), migrate=True)
    try:
        yield database
    finally:
        database.engine.dispose()
        with admin.begin() as connection:
            connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        admin.dispose()


def make_snapshot(c, tmp_path):
    setup_records(c)
    capture = upload(c).json()['capture']
    user, credential = person(c)
    if os.name != 'nt':
        model = create_model(c).json()
        assert import_pdf(c, model['id'], pdf_bytes(['Bearing reference'])).status_code == 201
    folder = tmp_path / 'snapshot'
    result = snapshot(c.app.state.database, c.app.state.capture_root, c.app.state.document_root, folder)
    return folder, capture, user, result


def test_snapshot_restores_relations_evidence_credentials_and_audit_sequence(client, tmp_path):
    folder, capture, user, result = make_snapshot(client, tmp_path)
    assert result['row_counts']['assets'] == 1
    if os.name != 'nt':
        assert (folder.stat().st_mode & 0o777) == 0o700
    with empty_target(tmp_path) as target:
        captures, documents = tmp_path / 'restored-captures', tmp_path / 'restored-documents'
        restored = restore(target, captures, documents, folder)
        assert restored['row_counts'] == result['row_counts']
        assert (captures / (capture['sha256'] + '.png')).is_file()
        assert len(list(documents.glob('*.pdf'))) == (0 if os.name == 'nt' else 1)
        with target.connect() as db:
            assert db.execute('SELECT id FROM users').fetchone()['id'] == user['id']
            previous = db.execute('SELECT MAX(sequence) AS n FROM audit').fetchone()['n']
            record_event(db, 'plant-a', 'restore.checked', 'check', {})
        with target.connect() as db:
            assert db.execute('SELECT MAX(sequence) AS n FROM audit').fetchone()['n'] > previous
            expected_pages = 0 if os.name == 'nt' else 1
            assert db.execute('SELECT COUNT(*) AS n FROM document_pages').fetchone()['n'] == expected_pages
        with pytest.raises(ValueError, match='empty'):
            restore(target, captures, documents, folder)


def test_tampered_snapshot_is_rejected_without_restoring_records(client, tmp_path):
    folder, capture, _, _ = make_snapshot(client, tmp_path)
    (folder / 'captures' / (capture['sha256'] + '.png')).write_bytes(b'changed evidence')
    with empty_target(tmp_path) as target:
        with pytest.raises(ValueError, match='integrity'):
            restore(target, tmp_path / 'captures', tmp_path / 'documents', folder)
        with target.connect() as db:
            assert db.execute('SELECT COUNT(*) AS n FROM assets').fetchone()['n'] == 0


def test_snapshot_refuses_existing_output_and_nonempty_restore_database(client, tmp_path):
    folder, _, _, _ = make_snapshot(client, tmp_path)
    with pytest.raises(FileExistsError):
        snapshot(client.app.state.database, client.app.state.capture_root, client.app.state.document_root, folder)
    with pytest.raises(ValueError, match='empty'):
        restore(client.app.state.database, tmp_path / 'empty-captures', tmp_path / 'empty-documents', folder)
