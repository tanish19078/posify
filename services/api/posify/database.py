"""Single-instance SQLite persistence. Transactions include their audit writes."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS assets(
 id TEXT PRIMARY KEY, site_id TEXT NOT NULL, tag TEXT NOT NULL,
 manufacturer TEXT NOT NULL, model TEXT NOT NULL, serial TEXT,
 category TEXT NOT NULL, location TEXT NOT NULL,
 UNIQUE(site_id,tag), UNIQUE(site_id,serial)
);
CREATE TABLE IF NOT EXISTS procedures(
 id TEXT PRIMARY KEY, site_id TEXT NOT NULL, manufacturer TEXT NOT NULL,
 model TEXT NOT NULL, title TEXT NOT NULL, version INTEGER NOT NULL,
 steps TEXT NOT NULL, source_text TEXT NOT NULL,
 UNIQUE(site_id,manufacturer,model,title,version)
);
CREATE TABLE IF NOT EXISTS inspections(
 id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
 procedure_id TEXT NOT NULL REFERENCES procedures(id),
 status TEXT NOT NULL CHECK(status IN ('open','submitted')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations(
 id TEXT PRIMARY KEY, inspection_id TEXT NOT NULL REFERENCES inspections(id),
 step_id TEXT NOT NULL, result TEXT NOT NULL, note TEXT NOT NULL,
 UNIQUE(inspection_id,step_id)
);
CREATE TABLE IF NOT EXISTS audit(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT NOT NULL,
 kind TEXT NOT NULL, entity_id TEXT NOT NULL, created_at TEXT NOT NULL,
 payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS asset_site ON assets(site_id);
CREATE INDEX IF NOT EXISTS audit_site ON audit(site_id,sequence);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()
