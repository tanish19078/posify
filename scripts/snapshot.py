"""Back up or restore the configured database with referenced capture/PDF files."""
import argparse
import json
import os
from pathlib import Path

from posify.database import Database
from posify.snapshots import snapshot, restore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    database = Database(os.getenv('POSIFY_DB', 'var/posify.db'), url=os.getenv('POSIFY_DATABASE_URL'))
    base = Path(database.path).parent
    try:
        result = (snapshot if args.action == 'backup' else restore)(database,
            Path(os.getenv('POSIFY_CAPTURE_DIR', str(base / 'captures'))),
            Path(os.getenv('POSIFY_DOCUMENT_DIR', str(base / 'documents'))), args.directory)
        print(json.dumps(result))
    finally:
        database.engine.dispose()


if __name__ == '__main__':
    main()
