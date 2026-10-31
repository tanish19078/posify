"""Versioned persistence for SQLite development and PostgreSQL deployment."""
import os
import re
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, make_url


class Rows:
    def __init__(self, result):
        self.rowcount = result.rowcount
        self._rows = result.mappings()

    def fetchone(self):
        return self._rows.fetchone()

    def fetchall(self):
        return self._rows.fetchall()

    def __iter__(self):
        return iter(self._rows)


class Session:
    """Keep existing parameterized repositories portable across both drivers."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        if sql == 'BEGIN IMMEDIATE':
            if self.connection.dialect.name == 'sqlite':
                result = self.connection.exec_driver_sql(sql)
            else:
                # Preserve the original coarse write serialization across processes.
                result = self.connection.execute(text('SELECT pg_advisory_xact_lock(7221431)'))
            return Rows(result)
        if sql == 'BEGIN':
            if self.connection.dialect.name == 'sqlite':
                return Rows(self.connection.exec_driver_sql(sql))
            return Rows(self.connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')))
        if not isinstance(parameters, dict):
            parts = sql.split('?')
            if len(parts) - 1 != len(parameters):
                raise ValueError('SQL placeholder count does not match supplied parameters')
            sql = ''.join(part + (f':p{i}' if i < len(parameters) else '') for i, part in enumerate(parts))
            parameters = {f'p{i}': value for i, value in enumerate(parameters)}
        return Rows(self.connection.execute(text(sql), parameters))


class Database:
    def __init__(self, path='var/posify.db', url=None, migrate=None):
        self.path = path
        if url:
            parsed = make_url(url)
            if parsed.drivername in {'postgresql', 'postgres'}:
                parsed = parsed.set(drivername='postgresql+psycopg')
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            parsed = URL.create('sqlite', database=path)
        if parsed.get_backend_name() not in {'sqlite', 'postgresql'}:
            raise RuntimeError('Only SQLite and PostgreSQL are supported')
        options = {'connect_args': {'timeout': 30}} if parsed.get_backend_name() == 'sqlite' else {}
        self.engine = create_engine(parsed, pool_pre_ping=True, **options)
        self.dialect = self.engine.dialect.name
        if self.dialect == 'sqlite':
            @event.listens_for(self.engine, 'connect')
            def configure_sqlite(dbapi, _):
                dbapi.execute('PRAGMA foreign_keys=ON')
                dbapi.execute('PRAGMA journal_mode=WAL')
        self.migration_config = Config()
        self.migration_config.set_main_option('script_location', str(Path(__file__).parent / 'migrations'))
        if migrate is None:
            migrate = os.getenv('POSIFY_AUTO_MIGRATE', 'true' if self.dialect == 'sqlite' else 'false').lower() == 'true'
        if migrate:
            self.upgrade()
        else:
            with self.engine.connect() as connection:
                actual = MigrationContext.configure(connection).get_current_revision()
            expected = ScriptDirectory.from_config(self.migration_config).get_current_head()
            if actual != expected:
                raise RuntimeError('Database migrations are required; run python scripts/migrate.py')

    def upgrade(self):
        with self.engine.begin() as connection:
            self.migration_config.attributes['connection'] = connection
            try:
                command.upgrade(self.migration_config, 'head')
            finally:
                self.migration_config.attributes.pop('connection', None)

    @contextmanager
    def connect(self):
        with self.engine.connect() as connection:
            try:
                yield Session(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
