"""Run schema upgrades as a separate deployment step. Does not copy database data."""
import os

from posify.database import Database

if __name__ == '__main__':
    db = Database(os.getenv('POSIFY_DB', 'var/posify.db'), url=os.getenv('POSIFY_DATABASE_URL'), migrate=True)
    print('Database upgraded to head:', db.dialect)
    db.engine.dispose()
