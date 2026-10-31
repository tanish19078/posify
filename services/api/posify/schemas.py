from typing import Annotated, Literal
from uuid import UUID
from posify.detector import Detection

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetCreate(StrictModel):
    site_id: Text
    tag: Text
    manufacturer: Text
    model: Text
    serial: Text | None = None
    category: Text
    location: Text


class AssetUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    location: Text | None = None
    category: Text | None = None

    @model_validator(mode="after")
    def has_change(self):
        if not self.model_fields_set.intersection({"location", "category"}):
            raise ValueError("Supply location or category")
        if any(getattr(self, name) is None for name in self.model_fields_set & {"location", "category"}):
            raise ValueError("Asset metadata cannot be null")
        return self


class Step(StrictModel):
    id: Text
    instruction: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class ProcedureCreate(StrictModel):
    site_id: Text
    manufacturer: Text
    model: Text
    title: Text
    version: int = Field(ge=1)
    steps: list[Step] = Field(min_length=1, max_length=100)
    source_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30000)]

    @model_validator(mode="after")
    def unique_steps(self):
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("Step IDs must be unique")
        return self


class IdentifyRequest(StrictModel):
    site_id: Text
    tag: Text | None = None
    serial: Text | None = None
    category: Text | None = None


class InspectionCreate(StrictModel):
    site_id: Text
    asset_id: UUID
    procedure_id: UUID
    asset_confirmed: Literal[True]


class ObservationCreate(StrictModel):
    id: UUID
    site_id: Text
    step_id: Text
    result: Literal["pass", "fail", "unknown"]
    note: Note = ""


class AssistantRequest(StrictModel):
    site_id: Text
    asset_id: UUID
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Asset(AssetCreate):
    id: UUID
    revision: int = Field(default=1, ge=1)


class Procedure(ProcedureCreate):
    id: UUID


class IdentityMatch(StrictModel):
    status: Literal['insufficient_evidence', 'candidate_found', 'no_match']
    requires_confirmation: bool
    basis: str | None = None
    candidates: list[Asset]


class Inspection(StrictModel):
    id: UUID
    asset_id: UUID
    procedure_id: UUID
    status: Literal['open', 'submitted']
    created_at: str


class Observation(StrictModel):
    id: UUID
    inspection_id: UUID
    step_id: str
    result: Literal['pass', 'fail', 'unknown']
    note: str


class InspectionDetail(Inspection):
    capture_ids: list[UUID] = Field(default_factory=list)
    site_id: str
    observations: list[Observation]


class ObservationReceipt(StrictModel):
    replayed: bool
    observation: Observation


class SubmissionReceipt(StrictModel):
    status: Literal['submitted']
    replayed: bool


class SitePack(StrictModel):
    schema_version: int
    site_id: str
    generated_at: str
    assets: list[Asset]
    procedures: list[Procedure]
    inspections: list[Inspection]
    observations: list[Observation]
    captures: list['Capture'] = Field(default_factory=list)
    capture_assignments: list['CaptureAssignment'] = Field(default_factory=list)
    inspection_evidence: list['InspectionEvidence'] = Field(default_factory=list)


class SourceExcerpt(StrictModel):
    id: str
    procedure_id: UUID | None = None
    document_id: UUID | None = None
    source_kind: Literal['factory_procedure', 'catalog_document'] = 'factory_procedure'
    source_ref: str | None = None
    version: int
    title: str
    excerpt: str


class AssistantResponse(StrictModel):
    retrieval_method: Literal['lexical', 'hybrid_e5'] = 'lexical'
    mode: Literal['insufficient_evidence', 'source_excerpts', 'model_draft']
    answer: str | None
    sources: list[SourceExcerpt]
    citations: list[str]
    requires_review: bool
    notice: str | None = None


class Capture(StrictModel):
    id: UUID
    site_id: str
    sha256: str
    width: int
    height: int
    warnings: list[str]
    created_at: str


class CaptureReceipt(StrictModel):
    replayed: bool
    capture: Capture


class OCRLineResponse(StrictModel):
    text: str
    confidence: float
    box: tuple[int, int, int, int] | None


class IdentifierEvidence(StrictModel):
    kind: Literal['tag', 'serial']
    value: str
    line_index: int
    confidence: float


class CaptureAnalysis(StrictModel):
    detections: list[Detection] = Field(default_factory=list)
    inference_mode: Literal['ocr', 'detect_ocr'] = 'ocr'
    detector_revision: str | None = None
    pipeline_warnings: list[str] = Field(default_factory=list)
    id: UUID
    capture_id: UUID
    created_at: str
    engine: str
    lines: list[OCRLineResponse]
    identifiers: list[IdentifierEvidence]
    status: Literal['insufficient_evidence', 'ambiguous_identifiers', 'candidate_found', 'no_match']
    candidates: list[Asset]
    requires_confirmation: bool


class CaptureConfirm(StrictModel):
    asset_id: UUID
    asset_confirmed: Literal[True]


class CaptureAssignment(StrictModel):
    capture_id: UUID
    asset_id: UUID
    confirmed_at: str


class InspectionEvidence(StrictModel):
    inspection_id: UUID
    capture_id: UUID


class EvidenceAttach(StrictModel):
    capture_id: UUID


SitePack.model_rebuild()
