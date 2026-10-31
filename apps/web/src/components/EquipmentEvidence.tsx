import { Eye, FileSearch, Info, ShieldCheck } from "lucide-react";
import type { Analysis } from "../types";
import { readable } from "../api";
import { Badge } from "./ui";

const names: Record<string, string> = {
  manufacturer: "Manufacturer",
  model: "Model / type",
  serial: "Serial number",
  asset_tag: "Factory asset tag",
  voltage: "Voltage",
  power: "Power",
  speed: "Speed",
  frequency: "Frequency",
  frame: "Frame",
};
const statuses: Record<string, string> = {
  supported_model_candidate: "A model candidate has supporting evidence",
  ambiguous_model_candidates: "Several model variants fit the evidence",
  conflicting_evidence: "The readings do not agree",
  multiple_nameplates: "Several nameplates need separate review",
  partial_evidence: "Only part of the model identity is supported",
  insufficient_evidence: "Not enough evidence to identify an equipment model",
  not_evaluated: "Structured recognition has not run",
};

export default function EquipmentEvidence({
  analysis,
  inspect,
}: {
  analysis: Analysis;
  inspect: (box: [number, number, number, number]) => void;
}) {
  const fields = analysis.equipment_fields || [];
  const attempts = analysis.reading_attempts || [];
  const candidates = analysis.equipment_candidates || [];
  const ordered = Object.keys(names).filter((name) =>
    fields.some((field) => field.field === name),
  );
  return (
    <div className="equipment-evidence">
      <div className="recognition-status">
        <span className="detection-icon">
          <FileSearch size={22} />
        </span>
        <div>
          <strong>
            {statuses[analysis.equipment_status || "not_evaluated"] ||
              readable(analysis.equipment_status || "not_evaluated")}
          </strong>
          <p>
            Field readings are proposals. No physical machine has been
            confirmed.
          </p>
        </div>
      </div>
      <div className="section-label">
        <span>STRUCTURED EQUIPMENT EVIDENCE</span>
        <Badge tone="amber">Review required</Badge>
      </div>
      {!ordered.length && (
        <div className="recognition-empty">
          <Info size={17} />
          <p>
            {analysis.recognition_version
              ? "No usable identifying fields were extracted. Try a sharper, closer view of the nameplate."
              : "This is an older raw-OCR result. Run a new detection analysis for structured fields and catalogue checks."}
          </p>
        </div>
      )}
      <div className="field-evidence-list">
        {ordered.map((name) => (
          <section className="field-evidence-group" key={name}>
            <h3>{names[name]}</h3>
            {fields
              .filter((field) => field.field === name)
              .map((field) => (
                <div
                  className={`field-evidence-value ${field.status}`}
                  key={field.id}
                >
                  <div className="field-evidence-heading">
                    <code>
                      {field.value}
                      {field.unit ? ` ${field.unit}` : ""}
                    </code>
                    <Badge
                      tone={
                        field.status === "conflicting"
                          ? "red"
                          : field.status === "low_confidence"
                            ? "amber"
                            : "neutral"
                      }
                    >
                      {field.status === "conflicting"
                        ? "Conflicting reading"
                        : field.status === "low_confidence"
                          ? "Low readability"
                          : "Observed text"}
                    </Badge>
                  </div>
                  <p className="field-source">Source: “{field.raw_text}”</p>
                  <div className="field-evidence-foot">
                    <small>
                      {(field.corroborating_attempts || []).length} reading
                      attempt
                      {(field.corroborating_attempts || []).length === 1
                        ? ""
                        : "s"}{" "}
                      · {readable(field.basis)}
                    </small>
                    <button
                      className="source-button"
                      disabled={!field.box}
                      onClick={() =>
                        field.box &&
                        inspect(field.box as [number, number, number, number])
                      }
                    >
                      <Eye size={13} />
                      View source
                    </button>
                  </div>
                </div>
              ))}
          </section>
        ))}
      </div>
      <div className="section-label">
        <span>PUBLISHED CATALOGUE CANDIDATES</span>
        <Badge tone="neutral">Model level</Badge>
      </div>
      {candidates.length ? (
        candidates.map((candidate) => (
          <article
            className={`equipment-candidate ${candidate.status}`}
            key={candidate.catalog_model_id}
          >
            <div>
              <h3>
                {candidate.manufacturer} · {candidate.model}
              </h3>
              <Badge
                tone={
                  candidate.status === "conflicting_evidence"
                    ? "red"
                    : candidate.status === "evidence_supported"
                      ? "green"
                      : "amber"
                }
              >
                {candidate.status === "evidence_supported"
                  ? "Evidence agrees"
                  : candidate.status === "conflicting_evidence"
                    ? "Contradiction"
                    : "Partial evidence"}
              </Badge>
            </div>
            <p>
              {candidate.category} · Variant: {candidate.variant}
            </p>
            {candidate.matched_fields.length > 0 && (
              <small>Agrees on: {candidate.matched_fields.join(", ")}</small>
            )}
            {candidate.missing_fields.length > 0 && (
              <small>
                Not supported: {candidate.missing_fields.join(", ")}
              </small>
            )}
            {candidate.conflicting_fields.length > 0 && (
              <small className="conflict-text">
                Conflicting: {candidate.conflicting_fields.join(", ")}
              </small>
            )}
            <small>
              Retrieval: {readable(candidate.retrieval_basis)}. Source:{" "}
              {candidate.source_ref}
            </small>
          </article>
        ))
      ) : (
        <p className="no-catalogue-match">
          No published model candidate is supported by the available catalogue
          and readings. A catalogue entry must exist before it can be retrieved.
        </p>
      )}
      <div className="model-boundary">
        <ShieldCheck size={16} />
        <p>
          A model describes an equipment type. Confirm the individual installed
          asset using its physical tag or serial.
        </p>
      </div>
      <details className="reading-history">
        <summary>
          Reading history · {attempts.length} attempt
          {attempts.length === 1 ? "" : "s"}
        </summary>
        {attempts.map((attempt) => (
          <details key={attempt.id}>
            <summary>
              <span>
                {readable(attempt.method)} · {attempt.rotation}°
              </span>
              <Badge tone={attempt.selected ? "green" : "neutral"}>
                {attempt.selected ? "Display reading" : "Alternative"}
              </Badge>
            </summary>
            <p className="muted">
              Alternative preprocessing attempts are not independent accuracy
              measurements.
            </p>
            {(attempt.lines || []).map((line, index) => (
              <div className="reading-history-line" key={index}>
                <code>{line.text}</code>
                <button
                  className="source-button"
                  disabled={!line.box}
                  onClick={() =>
                    line.box &&
                    inspect(line.box as [number, number, number, number])
                  }
                >
                  <Eye size={12} />
                  Source
                </button>
              </div>
            ))}
          </details>
        ))}
      </details>
    </div>
  );
}
