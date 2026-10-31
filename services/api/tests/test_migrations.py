import sqlite3

from posify.database import Database
from posify.migrations.versions.r0001_baseline import SCHEMA


def test_upgrade_legacy_preserves_data_and_registers_factory(tmp_path):
    path = str(tmp_path / 'legacy.db')
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?)',
                           ('asset-legacy', 'legacy-plant', 'P-1', 'Maker', 'M1', 'S1', 'pump', 'Bay 1'))
    db = Database(path)
    with db.connect() as connection:
        assert connection.execute('SELECT tag FROM assets WHERE id=?', ('asset-legacy',)).fetchone()['tag'] == 'P-1'
        factory = connection.execute('SELECT * FROM factories WHERE id=?', ('legacy-plant',)).fetchone()
        assert connection.execute('SELECT revision FROM assets').fetchone()['revision'] == 1
        assert factory['organization_id'] == '00000000-0000-0000-0000-000000000001'
        assert connection.execute('SELECT version_num FROM alembic_version').fetchone()['version_num'] == '0005'
    db.upgrade()
    with db.connect() as connection:
        assert len(connection.execute('SELECT * FROM factories').fetchall()) == 1


def test_transaction_rolls_back_on_error(tmp_path):
    db = Database(str(tmp_path / 'rollback.db'))
    try:
        with db.connect() as connection:
            connection.execute('INSERT INTO organizations VALUES(?,?,?)', ('one', 'One', 'now'))
            raise RuntimeError('rollback')
    except RuntimeError:
        pass
    with db.connect() as connection:
        assert connection.execute('SELECT * FROM organizations').fetchall() == []


def test_database_rejects_unregistered_factory(tmp_path):
    import pytest
    from sqlalchemy.exc import IntegrityError
    db = Database(str(tmp_path / 'constraints.db'))
    with pytest.raises(IntegrityError):
        with db.connect() as connection:
            connection.execute('INSERT INTO assets (id,site_id,tag,manufacturer,model,serial,category,location) VALUES(?,?,?,?,?,?,?,?)',
                               ('a', 'missing', 'P1', 'Maker', 'M1', None, 'pump', 'Bay'))
