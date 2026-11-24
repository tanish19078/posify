"""Run a separate local worker: python -m posify.worker [--once]."""
import argparse
import os
import socket
import time

from posify.app import create_app
from posify.jobs import record_worker_heartbeat, work_once


def _detector_revision(app):
    manifest = getattr(app.state.detector, 'manifest', None)
    if manifest:
        return f'{manifest.model_id}@{manifest.revision}'
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--poll-seconds', type=float, default=2)
    parser.add_argument('--lease-seconds', type=int, default=300)
    args = parser.parse_args()
    if not .1 <= args.poll_seconds <= 60 or not 30 <= args.lease_seconds <= 3600:
        parser.error('Poll interval must be 0.1–60s and lease duration 30–3600s')
    app = create_app()
    worker_id = f'{socket.gethostname()}:{os.getpid()}'
    ocr_engine = app.state.ocr.engine
    jobs_processed = 0
    try:
        record_worker_heartbeat(
            app.state.database, worker_id, ocr_engine,
            detector_revision=_detector_revision(app), status='starting', jobs_processed=jobs_processed,
        )
        while True:
            handled = work_once(app, args.lease_seconds)
            if handled:
                jobs_processed += 1
            record_worker_heartbeat(
                app.state.database, worker_id, ocr_engine,
                detector_revision=_detector_revision(app),
                status='active' if handled else 'idle',
                jobs_processed=jobs_processed,
            )
            if args.once:
                print('Processed one job' if handled else 'No eligible jobs')
                return
            if not handled:
                time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            record_worker_heartbeat(
                app.state.database, worker_id, ocr_engine,
                detector_revision=_detector_revision(app), status='stopped', jobs_processed=jobs_processed,
            )
        except Exception:
            pass
        app.state.database.engine.dispose()


if __name__ == '__main__':
    main()
