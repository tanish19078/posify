import json
import os
import secrets
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import APIKeyHeader

from posify.assistant import explain
from posify.database import Database
from posify.capture_routes import install_capture_routes
from posify.captures import capture_row
from posify.ocr import LocalOCR
from posify.detector import LocalDetector
from posify.catalog import install_catalog_routes, require_factory
from posify.jobs import install_job_routes
from posify.retrieval import HybridRetriever
from starlette.concurrency import run_in_threadpool
from posify.schemas import (
    AssetCreate, IdentifyRequest, InspectionCreate, ObservationCreate, ProcedureCreate, AssistantRequest,
    Asset, Procedure, IdentityMatch, Inspection, InspectionDetail, ObservationReceipt,
    SubmissionReceipt, SitePack, AssistantResponse,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def decode(row):
    result = dict(row)
    if "steps" in result:
        result["steps"] = json.loads(result["steps"])
    return result


def audit(db, site, kind, entity, payload):
    db.execute("INSERT INTO audit(site_id,kind,entity_id,created_at,payload) VALUES(?,?,?,?,?)",
               (site, kind, entity, now(), json.dumps(payload)))


def asset(db, asset_id, site):
    row = db.execute("SELECT * FROM assets WHERE id=? AND site_id=?", (str(asset_id), site)).fetchone()
    if not row:
        raise HTTPException(404, "Asset not found in this site")
    return dict(row)


def inspection(db, inspection_id, site):
    row = db.execute("SELECT i.*,a.site_id FROM inspections i JOIN assets a ON a.id=i.asset_id "
                     "WHERE i.id=? AND a.site_id=?", (inspection_id, site)).fetchone()
    if not row:
        raise HTTPException(404, "Inspection not found in this site")
    return dict(row)


def create_app(db_path=None, api_token=None, database_url=None):
    token = api_token or os.getenv("POSIFY_API_TOKEN")
    if not token or token == "replace-with-a-generated-token":
        raise RuntimeError("Set POSIFY_API_TOKEN to a generated development token")
    database = Database(db_path or os.getenv("POSIFY_DB", "var/posify.db"),
                        url=database_url or (os.getenv("POSIFY_DATABASE_URL") if db_path is None else None))
    app = FastAPI(title="Equipment inspection API", version="0.1.0")
    app.state.database = database
    header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def authorize(key: str | None = Depends(header)):
        if not key or not secrets.compare_digest(key.encode(), token.encode()):
            raise HTTPException(401, "Invalid API key")

    auth = [Depends(authorize)]
    install_catalog_routes(app, database, auth)
    install_job_routes(app, database, auth)
    app.state.ocr = LocalOCR()
    app.state.detector = LocalDetector()
    app.state.retriever = HybridRetriever()
    capture_root = Path(os.getenv("POSIFY_CAPTURE_DIR", str(Path(database.path).parent / "captures")))
    app.state.capture_root = capture_root
    install_capture_routes(app, database, auth, capture_root)

    app.state.model_name = os.getenv("POSIFY_OLLAMA_MODEL", "")
    app.state.model_url = os.getenv("POSIFY_OLLAMA_URL", "http://127.0.0.1:11434")
    app.state.model_transport = None

    @app.post("/v1/assistant/query", response_model=AssistantResponse, dependencies=auth)
    async def assistant_query(body: AssistantRequest):
        with database.connect() as db:
            a = asset(db, body.asset_id, body.site_id)
            rows = db.execute(
                "SELECT p.* FROM procedures p WHERE p.site_id=? AND p.manufacturer=? AND p.model=? "
                "AND p.version=(SELECT MAX(q.version) FROM procedures q WHERE "
                "q.site_id=p.site_id AND q.manufacturer=p.manufacturer AND q.model=p.model AND q.title=p.title)",
                (body.site_id, a["manufacturer"], a["model"])).fetchall()
            global_rows = db.execute(
                "SELECT d.id,d.title,d.revision AS version,d.source_text,d.source_ref FROM catalog_documents d "
                "JOIN asset_catalog_links l ON l.catalog_model_id=d.catalog_model_id "
                "JOIN catalog_models m ON m.id=d.catalog_model_id "
                "WHERE l.asset_id=? AND d.status='published' AND m.status='published' "
                "AND d.revision=(SELECT MAX(newer.revision) FROM catalog_documents newer WHERE "
                "newer.catalog_model_id=d.catalog_model_id AND newer.title=d.title AND newer.status='published')",
                (a['id'],)).fetchall()
            knowledge = [dict(r) for r in rows] + [{**dict(r), 'source_kind': 'catalog_document'} for r in global_rows]
        sources = await run_in_threadpool(app.state.retriever.search, knowledge, body.question)
        result = await explain(sources, body.question, app.state.model_name,
                               app.state.model_url, app.state.model_transport)
        result['retrieval_method'] = 'hybrid_e5' if app.state.retriever.model_path else 'lexical'
        return result


    @app.get("/v1/runtime", dependencies=auth)
    def runtime_status():
        return {
            "ocr": app.state.ocr.readiness(),
            "retrieval": app.state.retriever.readiness(),
            "assistant": {"runtime": "ollama", "configured": bool(app.state.model_name),
                          "model": app.state.model_name or None, "inference_verified": False},
            "detector": app.state.detector.readiness(),
            "database": {"dialect": database.dialect},
        }

    @app.get("/health")
    def health():
        with database.connect() as db:
            db.execute("SELECT 1")
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/v1/assets", status_code=201, response_model=Asset, dependencies=auth)
    def create_asset(body: AssetCreate):
        data = {"id": str(uuid4()), **body.model_dump()}
        with database.connect() as db:
            require_factory(db, body.site_id)
            try:
                db.execute("INSERT INTO assets VALUES(:id,:site_id,:tag,:manufacturer,:model,:serial,:category,:location)", data)
            except IntegrityError:
                raise HTTPException(409, "Asset tag or serial already exists in this site")
            audit(db, body.site_id, "asset.created", data["id"], data)
        return data

    @app.get("/v1/assets", response_model=list[Asset], dependencies=auth)
    def list_assets(site_id: str = Query(min_length=1), limit: int = Query(100, ge=1, le=500),
                    offset: int = Query(0, ge=0)):
        with database.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM assets WHERE site_id=? ORDER BY id LIMIT ? OFFSET ?", (site_id, limit, offset))]

    @app.post("/v1/identify", response_model=IdentityMatch, dependencies=auth)
    def identify(body: IdentifyRequest):
        with database.connect() as db:
            # Contradictory identifiers must not silently fall back to category.
            clauses, args = ["site_id=?"], [body.site_id]
            if body.tag:
                clauses.append("tag=?")
                args.append(body.tag)
            if body.serial:
                clauses.append("serial=?")
                args.append(body.serial)
            if not body.tag and not body.serial:
                return {"status": "insufficient_evidence", "requires_confirmation": True, "candidates": []}
            rows = db.execute("SELECT * FROM assets WHERE " + " AND ".join(clauses), args).fetchall()
        return {"status": "candidate_found" if rows else "no_match", "requires_confirmation": True,
                "basis": "exact_supplied_identifiers", "candidates": [dict(r) for r in rows]}

    @app.post("/v1/procedures", status_code=201, response_model=Procedure, dependencies=auth)
    def create_procedure(body: ProcedureCreate):
        data = {"id": str(uuid4()), **body.model_dump()}
        stored = {**data, "steps": json.dumps(data["steps"])}
        with database.connect() as db:
            require_factory(db, body.site_id)
            try:
                db.execute("INSERT INTO procedures VALUES(:id,:site_id,:manufacturer,:model,:title,:version,:steps,:source_text)", stored)
            except IntegrityError:
                raise HTTPException(409, "Procedure version already exists; create a new version")
            audit(db, body.site_id, "procedure.created", data["id"], {"version": body.version})
        return data

    @app.post("/v1/inspections", status_code=201, response_model=Inspection, dependencies=auth)
    def create_inspection(body: InspectionCreate):
        with database.connect() as db:
            a = asset(db, body.asset_id, body.site_id)
            p = db.execute("SELECT * FROM procedures WHERE id=? AND site_id=?",
                           (str(body.procedure_id), body.site_id)).fetchone()
            if not p:
                raise HTTPException(404, "Procedure not found in this site")
            if (a["manufacturer"], a["model"]) != (p["manufacturer"], p["model"]):
                raise HTTPException(409, "Procedure does not apply to this equipment model")
            data = {"id": str(uuid4()), "asset_id": a["id"], "procedure_id": p["id"],
                    "status": "open", "created_at": now()}
            db.execute("INSERT INTO inspections VALUES(:id,:asset_id,:procedure_id,:status,:created_at)", data)
            audit(db, body.site_id, "inspection.created", data["id"], {"procedure_id": p["id"]})
        return data

    @app.get("/v1/inspections/{inspection_id}", response_model=InspectionDetail, dependencies=auth)
    def get_inspection(inspection_id: str, site_id: str = Query(min_length=1)):
        with database.connect() as db:
            data = inspection(db, inspection_id, site_id)
            data["capture_ids"] = [r["capture_id"] for r in db.execute(
                "SELECT capture_id FROM inspection_evidence WHERE inspection_id=? ORDER BY capture_id", (inspection_id,))]
            data["observations"] = [dict(r) for r in db.execute(
                "SELECT * FROM observations WHERE inspection_id=? ORDER BY step_id", (inspection_id,))]
        return data

    @app.post("/v1/inspections/{inspection_id}/observations", response_model=ObservationReceipt, dependencies=auth)
    def add_observation(inspection_id: str, body: ObservationCreate):
        data = {"id": str(body.id), "inspection_id": inspection_id,
                "step_id": body.step_id, "result": body.result, "note": body.note}
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = inspection(db, inspection_id, body.site_id)
            existing = db.execute("SELECT * FROM observations WHERE id=?", (str(body.id),)).fetchone()
            if existing:
                if dict(existing) != data:
                    raise HTTPException(409, "Observation ID reused with different content")
                return {"replayed": True, "observation": data}
            if current["status"] != "open":
                raise HTTPException(409, "Submitted inspections are immutable")
            p = db.execute("SELECT steps FROM procedures WHERE id=?", (current["procedure_id"],)).fetchone()
            if body.step_id not in {s["id"] for s in json.loads(p["steps"])}:
                raise HTTPException(422, "Unknown procedure step")
            try:
                db.execute("INSERT INTO observations VALUES(:id,:inspection_id,:step_id,:result,:note)", data)
            except IntegrityError:
                raise HTTPException(409, "A result is already recorded for this step")
            audit(db, body.site_id, "observation.created", data["id"], data)
        return {"replayed": False, "observation": data}

    @app.post("/v1/inspections/{inspection_id}/submit", response_model=SubmissionReceipt, dependencies=auth)
    def submit(inspection_id: str, site_id: str = Query(min_length=1)):
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = inspection(db, inspection_id, site_id)
            if current["status"] == "submitted":
                return {"status": "submitted", "replayed": True}
            p = db.execute("SELECT steps FROM procedures WHERE id=?", (current["procedure_id"],)).fetchone()
            expected = {s["id"] for s in json.loads(p["steps"])}
            actual = {r["step_id"] for r in db.execute(
                "SELECT step_id FROM observations WHERE inspection_id=?", (inspection_id,))}
            if expected != actual:
                raise HTTPException(409, {"message": "Record every step before submission", "missing": sorted(expected - actual)})
            db.execute("UPDATE inspections SET status='submitted' WHERE id=?", (inspection_id,))
            audit(db, site_id, "inspection.submitted", inspection_id, {})
        return {"status": "submitted", "replayed": False}

    @app.get("/v1/sites/{site_id}/pack", response_model=SitePack, dependencies=auth)
    def site_pack(site_id: str):
        with database.connect() as db:
            db.execute("BEGIN")
            assets = [dict(r) for r in db.execute("SELECT * FROM assets WHERE site_id=? ORDER BY id", (site_id,))]
            procedures = [decode(r) for r in db.execute("SELECT * FROM procedures WHERE site_id=? ORDER BY id", (site_id,))]
            inspections = [dict(r) for r in db.execute("SELECT i.* FROM inspections i JOIN assets a ON a.id=i.asset_id WHERE a.site_id=? ORDER BY i.id", (site_id,))]
            observations = [dict(r) for r in db.execute("SELECT o.* FROM observations o JOIN inspections i ON i.id=o.inspection_id JOIN assets a ON a.id=i.asset_id WHERE a.site_id=? ORDER BY o.id", (site_id,))]
            captures = [capture_row(r) for r in db.execute("SELECT * FROM captures WHERE site_id=? ORDER BY id", (site_id,))]
            assignments = [dict(r) for r in db.execute(
                "SELECT ca.* FROM capture_assignments ca JOIN captures c ON c.id=ca.capture_id WHERE c.site_id=? ORDER BY ca.capture_id", (site_id,))]
            evidence = [dict(r) for r in db.execute(
                "SELECT e.* FROM inspection_evidence e JOIN captures c ON c.id=e.capture_id WHERE c.site_id=? ORDER BY e.inspection_id,e.capture_id", (site_id,))]
        return {"schema_version": 2, "site_id": site_id, "generated_at": now(),
                "assets": assets, "procedures": procedures, "inspections": inspections, "observations": observations,
                "captures": captures, "capture_assignments": assignments, "inspection_evidence": evidence}

    @app.get("/v1/sites/{site_id}/audit", dependencies=auth)
    def history(site_id: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        with database.connect() as db:
            rows = db.execute("SELECT * FROM audit WHERE site_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                              (site_id, after, limit)).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    return app


def __getattr__(name):
    # Factory imports and contract export do not require a process-level token.
    if name == "app":
        return create_app()
    raise AttributeError(name)
