"""Request-scoped attribution; workers are explicitly recorded as system actors."""
import json
from contextvars import ContextVar
from datetime import datetime, timezone

actor = ContextVar('posify_actor', default={'id': None, 'type': 'system'})


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def record_event(db, site, kind, entity_id, payload):
    who = actor.get()
    db.execute('INSERT INTO audit(site_id,kind,entity_id,created_at,payload,actor_id,actor_type) VALUES(?,?,?,?,?,?,?)',
               (site, kind, str(entity_id), timestamp(), json.dumps(payload), who['id'], who['type']))
