"""Provision an initial administrator directly against the configured database."""
import argparse
import json
import os
from pathlib import Path

from posify.audit import actor, record_event
from posify.database import Database
from posify.security import UserCreate, create_user, issue_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--output', required=True, type=Path, help='New private credential file; never overwritten')
    args = parser.parse_args()
    db = Database(os.getenv('POSIFY_DB', 'var/posify.db'), url=os.getenv('POSIFY_DATABASE_URL'))
    marker = actor.set({'id': None, 'type': 'operator'})
    try:
        with db.connect() as session:
            user = create_user(session, UserCreate(name=args.name, is_admin=True))
            credential = issue_token(session, user['id'], 30)
            record_event(session, '@security', 'user.provisioned', user['id'], {'method': 'operator_cli'})
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as handle:
                json.dump(credential, handle, indent=2)
                handle.write('\n')
        print(f'Administrator created; credential saved to {args.output}')
    finally:
        actor.reset(marker)
        db.engine.dispose()


if __name__ == '__main__':
    main()
