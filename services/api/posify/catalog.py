"""Global model catalogue, explicit factory ownership and reviewed knowledge."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, Query
from pydantic import Field
from sqlalchemy.exc import IntegrityError

from posify.schemas import StrictModel, Text
from posify.audit import record_event


class OrganizationCreate(StrictModel):
    name: Text


class Organization(OrganizationCreate):
    id: UUID
    created_at: str


class FactoryCreate(StrictModel):
    id: Text
    organization_id: UUID
    name: Text


class Factory(FactoryCreate):
    created_at: str


class CatalogCreate(StrictModel):
    manufacturer: Text
    model: Text
    variant: Text = 'base'
    category: Text
    source_ref: Text


class CatalogModel(CatalogCreate):
    id: UUID
    status: str
    created_at: str


class DocumentCreate(StrictModel):
    title: Text
    revision: int = Field(ge=1)
    source_text: str = Field(min_length=1, max_length=30000)
    source_ref: Text


class CatalogDocument(DocumentCreate):
    id: UUID
    catalog_model_id: UUID
    status: str
    created_at: str


class LinkCreate(StrictModel):
    catalog_model_id: UUID
    asset_confirmed: bool


class CatalogLink(StrictModel):
    asset_id: UUID
    catalog_model_id: UUID
    confirmed_at: str


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def require_factory(db, site):
    row = db.execute('SELECT * FROM factories WHERE id=?', (site,)).fetchone()
    if not row:
        raise HTTPException(404, 'Factory is not registered')
    return dict(row)


def model_record(db, model_id):
    row = db.execute('SELECT * FROM catalog_models WHERE id=?', (str(model_id),)).fetchone()
    if not row:
        raise HTTPException(404, 'Catalogue model not found')
    return dict(row)


def install_catalog_routes(app, database, auth):
    @app.post('/v1/organizations', response_model=Organization, dependencies=auth, status_code=201)
    def organization(body: OrganizationCreate):
        data = dict(id=str(uuid4()), name=body.name, created_at=timestamp())
        with database.connect() as db:
            db.execute('INSERT INTO organizations VALUES(:id,:name,:created_at)', data)
        return data

    @app.get('/v1/organizations', response_model=list[Organization], dependencies=auth)
    def organizations(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        with database.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM organizations ORDER BY id LIMIT ? OFFSET ?', (limit, offset))]

    @app.post('/v1/factories', response_model=Factory, status_code=201, dependencies=auth)
    def factory(body: FactoryCreate):
        data = {**body.model_dump(mode='json'), 'created_at': timestamp()}
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM organizations WHERE id=?', (data['organization_id'],)).fetchone():
                raise HTTPException(404, 'Organization not found')
            try:
                db.execute('INSERT INTO factories VALUES(:id,:organization_id,:name,:created_at)', data)
            except IntegrityError:
                raise HTTPException(409, 'Factory ID already exists')
            record_event(db, body.id, 'factory.created', body.id, {'organization_id': data['organization_id']})
        return data

    @app.get('/v1/factories', response_model=list[Factory], dependencies=auth)
    def factories(organization_id: UUID, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        with database.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM factories WHERE organization_id=? ORDER BY id LIMIT ? OFFSET ?',
                                               (str(organization_id), limit, offset))]

    @app.post('/v1/catalog/models', response_model=CatalogModel, status_code=201, dependencies=auth)
    def create_model(body: CatalogCreate):
        data = {**body.model_dump(), 'id': str(uuid4()), 'status': 'draft', 'created_at': timestamp()}
        data['identity_key'] = hashlib.sha256(json.dumps([body.manufacturer.casefold(), body.model.casefold(),
                                                          body.variant.casefold()]).encode()).hexdigest()
        with database.connect() as db:
            try:
                db.execute('INSERT INTO catalog_models VALUES(:id,:identity_key,:manufacturer,:model,:variant,:category,:source_ref,:status,:created_at)', data)
            except IntegrityError:
                raise HTTPException(409, 'Manufacturer/model/variant already exists in the catalogue')
            record_event(db, '@catalog', 'catalog.model_created', data['id'], {})
        data.pop('identity_key')
        return data

    @app.get('/v1/catalog/models', response_model=list[CatalogModel], dependencies=auth)
    def models(q: str = Query('', max_length=200), include_drafts: bool = False,
               limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        with database.connect() as db:
            rows = db.execute("SELECT * FROM catalog_models WHERE (status='published' OR ?=1) "
                              "AND (LOWER(manufacturer) LIKE ? ESCAPE '!' OR LOWER(model) LIKE ? ESCAPE '!') "
                              'ORDER BY manufacturer,model,variant LIMIT ? OFFSET ?',
                              (int(include_drafts), '%' + q.lower().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%',
                               '%' + q.lower().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%', limit, offset)).fetchall()
        return [{k: v for k, v in dict(r).items() if k != 'identity_key'} for r in rows]

    @app.post('/v1/catalog/models/{model_id}/publish', response_model=CatalogModel, dependencies=auth)
    def publish_model(model_id: UUID):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            data = model_record(db, model_id)
            if data['status'] == 'draft':
                db.execute("UPDATE catalog_models SET status='published' WHERE id=?", (str(model_id),))
                record_event(db, '@catalog', 'catalog.model_published', str(model_id), {})
            data['status'] = 'published'
        data.pop('identity_key')
        return data

    @app.post('/v1/catalog/models/{model_id}/documents', response_model=CatalogDocument, status_code=201, dependencies=auth)
    def create_document(model_id: UUID, body: DocumentCreate):
        if not body.source_text.strip():
            raise HTTPException(422, 'Document text must not be blank')
        data = {**body.model_dump(), 'id': str(uuid4()), 'catalog_model_id': str(model_id),
                'status': 'draft', 'created_at': timestamp()}
        with database.connect() as db:
            model_record(db, model_id)
            try:
                db.execute('INSERT INTO catalog_documents VALUES(:id,:catalog_model_id,:title,:revision,:source_text,:source_ref,:status,:created_at)', data)
            except IntegrityError:
                raise HTTPException(409, 'Document revision already exists; create a new revision')
            record_event(db, '@catalog', 'catalog.document_created', data['id'], {'catalog_model_id': str(model_id)})
        return data

    @app.post('/v1/catalog/documents/{document_id}/publish', response_model=CatalogDocument, dependencies=auth)
    def publish_document(document_id: UUID):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM catalog_documents WHERE id=?', (str(document_id),)).fetchone()
            if not row:
                raise HTTPException(404, 'Catalogue document not found')
            data = dict(row)
            if model_record(db, data['catalog_model_id'])['status'] != 'published':
                raise HTTPException(409, 'Publish the catalogue model first')
            if data['status'] == 'draft':
                db.execute("UPDATE catalog_documents SET status='published' WHERE id=?", (str(document_id),))
                record_event(db, '@catalog', 'catalog.document_published', str(document_id), {})
            data['status'] = 'published'
        return data

    @app.get('/v1/catalog/models/{model_id}/documents', response_model=list[CatalogDocument], dependencies=auth)
    def documents(model_id: UUID, include_drafts: bool = False, limit: int = Query(100, ge=1, le=200)):
        with database.connect() as db:
            model_record(db, model_id)
            return [dict(r) for r in db.execute("SELECT * FROM catalog_documents WHERE catalog_model_id=? "
                        "AND (status='published' OR ?=1) ORDER BY title,revision DESC LIMIT ?", (str(model_id), int(include_drafts), limit))]

    @app.post('/v1/sites/{site_id}/assets/{asset_id}/catalog-link', response_model=CatalogLink, dependencies=auth)
    def link(site_id: str, asset_id: UUID, body: LinkCreate):
        if not body.asset_confirmed:
            raise HTTPException(422, 'Explicit human confirmation is required')
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require_factory(db, site_id)
            asset = db.execute('SELECT * FROM assets WHERE id=? AND site_id=?', (str(asset_id), site_id)).fetchone()
            if not asset:
                raise HTTPException(404, 'Asset not found in this factory')
            model = model_record(db, body.catalog_model_id)
            if model['status'] != 'published':
                raise HTTPException(409, 'Catalogue model must be published')
            if (asset['manufacturer'].casefold(), asset['model'].casefold()) != (model['manufacturer'].casefold(), model['model'].casefold()):
                raise HTTPException(409, 'Manufacturer/model do not agree; correct the asset record through review')
            existing = db.execute('SELECT * FROM asset_catalog_links WHERE asset_id=?', (str(asset_id),)).fetchone()
            if existing:
                if existing['catalog_model_id'] != str(body.catalog_model_id):
                    raise HTTPException(409, 'Asset already linked; a reviewed correction is required')
                return dict(existing)
            data = dict(asset_id=str(asset_id), catalog_model_id=str(body.catalog_model_id), confirmed_at=timestamp())
            db.execute('INSERT INTO asset_catalog_links VALUES(:asset_id,:catalog_model_id,:confirmed_at)', data)
            record_event(db, site_id, 'asset.catalog_linked', str(asset_id), {'catalog_model_id': str(body.catalog_model_id)})
        return data

    @app.get('/v1/sites/{site_id}/assets/{asset_id}/catalog-link', response_model=CatalogLink, dependencies=auth)
    def get_link(site_id: str, asset_id: UUID):
        with database.connect() as db:
            row = db.execute('SELECT l.* FROM asset_catalog_links l JOIN assets a ON a.id=l.asset_id '
                             'WHERE a.id=? AND a.site_id=?', (str(asset_id), site_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Confirmed catalogue link not found in this factory')
        return dict(row)
