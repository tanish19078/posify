"""Run a separate local worker: python -m posify.worker [--once]."""
import argparse
import time

from posify.app import create_app
from posify.jobs import work_once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--poll-seconds', type=float, default=2)
    parser.add_argument('--lease-seconds', type=int, default=300)
    args = parser.parse_args()
    if not .1 <= args.poll_seconds <= 60 or not 30 <= args.lease_seconds <= 3600:
        parser.error('Poll interval must be 0.1–60s and lease duration 30–3600s')
    app = create_app()
    try:
        while True:
            handled = work_once(app, args.lease_seconds)
            if args.once:
                print('Processed one job' if handled else 'No eligible jobs')
                return
            if not handled:
                time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        app.state.database.engine.dispose()


if __name__ == '__main__':
    main()
