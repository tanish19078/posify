import {
  ArrowUpRight,
  Camera,
  ClipboardCheck,
  Plus,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
import { date, json, segment, sitePath } from "../api";
import {
  Button,
  Empty,
  ErrorPanel,
  Field,
  Loading,
  Modal,
  PageHead,
  Panel,
  Status,
} from "../components/ui";
import { useWorkspace } from "../context";
import { useLoad } from "../hooks";
import type {
  Asset,
  Capture,
  Inspection,
  InspectionDetail,
  Procedure,
} from "../types";

import { MutationForm, text } from "../components/forms";
export function Inspections({ inspectionId }: { inspectionId?: string }) {
  const { api, site, role, session, navigate, notify } = useWorkspace();
  const [adding, setAdding] = useState(false);
  const [filter, setFilter] = useState("");
  const [selectedAsset, setSelectedAsset] = useState("");
  const rows = useLoad(
    (signal) =>
      api<Inspection[]>(
        `/v1/inspections?site_id=${segment(site)}&limit=200${filter ? "&status=" + filter : ""}`,
        { signal },
      ),
    [site, filter],
  );
  const assets = useLoad(
    (signal) =>
      api<Asset[]>(`/v1/assets?site_id=${segment(site)}&limit=500`, { signal }),
    [site],
  );
  const procedures = useLoad(
    (signal) =>
      api<Procedure[]>(`/v1/procedures?site_id=${segment(site)}&limit=200`, {
        signal,
      }),
    [site],
  );
  if (inspectionId)
    return (
      <InspectionReview
        id={inspectionId}
        assets={assets.data || []}
        procedures={procedures.data || []}
      />
    );
  const a = assets.data?.find((a) => a.id === selectedAsset);
  const applicable = procedures.data?.filter(
    (p) => p.manufacturer === a?.manufacturer && p.model === a?.model,
  );
  return (
    <>
      <PageHead
        eyebrow="INSPECTIONS / TRACEABLE RECORDS"
        title="From evidence to a record."
        description="Follow applicable procedures. Preserve observations, evidence and review history."
        actions={
          <Button
            disabled={session.demo || role === "viewer"}
            onClick={() => setAdding(true)}
          >
            <Plus size={17} />
            New inspection
          </Button>
        }
      />
      <div className="section-toolbar">
        <div className="segmented">
          {[
            ["", "All inspections"],
            ["open", "Open"],
            ["submitted", "Submitted"],
          ].map(([value, label]) => (
            <button
              key={value}
              className={filter === value ? "selected" : ""}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="muted">Up to 200 records</span>
      </div>
      {rows.loading ? (
        <Loading />
      ) : rows.error ? (
        <ErrorPanel message={rows.error} retry={rows.reload} />
      ) : !rows.data?.length ? (
        <Empty title="No inspections here yet">
          Start a checklist for a confirmed physical asset.
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Inspection</th>
                <th>Asset</th>
                <th>Procedure</th>
                <th>Created</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.data.map((i) => (
                <tr key={i.id}>
                  <td>
                    <button
                      className="table-title"
                      onClick={() => navigate("inspections/" + i.id)}
                    >
                      <span className="asset-icon">
                        <ClipboardCheck size={20} />
                      </span>
                      <b>{i.id.slice(0, 8)}</b>
                    </button>
                  </td>
                  <td>
                    {assets.data?.find((a) => a.id === i.asset_id)?.tag ||
                      i.asset_id.slice(0, 8)}
                  </td>
                  <td>
                    {procedures.data?.find((p) => p.id === i.procedure_id)
                      ?.title || "Procedure"}
                  </td>
                  <td>{date(i.created_at)}</td>
                  <td>
                    <Status value={i.status} />
                  </td>
                  <td>
                    <a
                      href={`#/inspections/${i.id}`}
                      className="icon-button"
                      aria-label="Open inspection"
                    >
                      <ArrowUpRight size={17} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {adding && (
        <Modal title="Start an inspection" close={() => setAdding(false)}>
          <MutationForm
            label="Create inspection"
            submit={async (data) => {
              const created = await api<Inspection>(
                "/v1/inspections",
                json({
                  site_id: site,
                  asset_id: selectedAsset,
                  procedure_id: text(data, "procedure"),
                  asset_confirmed: true,
                }),
              );
              setAdding(false);
              notify("Inspection created with its procedure version pinned.");
              navigate("inspections/" + created.id);
            }}
          >
            <Field label="Physical asset">
              <select
                required
                value={selectedAsset}
                onChange={(e) => setSelectedAsset(e.target.value)}
              >
                <option value="">Select an asset…</option>
                {assets.data?.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.tag} · {a.model}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Applicable procedure">
              <select name="procedure" required key={selectedAsset}>
                <option value="">Select a procedure…</option>
                {applicable?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title} · v{p.version}
                  </option>
                ))}
              </select>
            </Field>
            {selectedAsset && !applicable?.length && (
              <p className="notice">
                Add a matching factory procedure in Knowledge first.
              </p>
            )}
            <label className="check-field">
              <input type="checkbox" required />I verified the identity of the
              physical asset.
            </label>
          </MutationForm>
        </Modal>
      )}
    </>
  );
}
function InspectionReview({
  id,
  assets,
  procedures,
}: {
  id: string;
  assets: Asset[];
  procedures: Procedure[];
}) {
  const { api, site, session, role, notify } = useWorkspace();
  const detail = useLoad(
    (signal) =>
      api<InspectionDetail>(
        `/v1/inspections/${segment(id)}?site_id=${segment(site)}`,
        { signal },
      ),
    [id, site],
  );
  const [submit, setSubmit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const captures = useLoad(
    (signal) =>
      api<Capture[]>(`${sitePath(site)}/captures?limit=200`, { signal }),
    [site],
  );
  const reviews = useLoad(
    (signal) =>
      api<{ id: string; outcome: string; note: string; created_at: string }[]>(
        `${sitePath(site)}/inspections/${segment(id)}/reviews`,
        { signal },
      ),
    [site, id],
  );
  if (detail.loading) return <Loading />;
  if (detail.error)
    return <ErrorPanel message={detail.error} retry={detail.reload} />;
  const record = {
    ...detail.data!,
    capture_ids: detail.data!.capture_ids || [],
  };
  const asset = assets.find((a) => a.id === record.asset_id);
  const procedure = procedures.find((p) => p.id === record.procedure_id);
  const editable =
    record.status === "open" && role !== "viewer" && !session.demo;
  async function finish() {
    setBusy(true);
    try {
      await api(
        `/v1/inspections/${id}/submit?site_id=${segment(site)}`,
        json({}),
      );
      setSubmit(false);
      detail.reload();
      notify("Inspection submitted. Observations are now immutable.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <a className="text-link" href="#/inspections">
        ← All inspections
      </a>
      <PageHead
        eyebrow="INSPECTION / PROCEDURE VERSION PINNED"
        title={asset?.tag || "Inspection record"}
        description={`${procedure?.title || "Procedure"}${procedure ? " · v" + procedure.version : ""} · ${date(record.created_at)}`}
        actions={<Status value={record.status} />}
      />
      {error && <ErrorPanel message={error} />}
      <Panel
        title="Procedure checklist"
        caption={`${record.observations.length} of ${procedure?.steps.length ?? "…"} steps recorded`}
      >
        {!procedure ? (
          <ErrorPanel message="The pinned procedure is not in the loaded procedure page. Ask your administrator to retrieve this procedure before continuing." />
        ) : (
          procedure.steps.map((step, index) => {
            const observation = record.observations.find(
              (o) => o.step_id === step.id,
            );
            return (
              <div className="checklist-step" key={step.id}>
                <span className="step-count">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <h3>{step.instruction}</h3>
                  {observation ? (
                    <>
                      <Status value={observation.result} />
                      <p>{observation.note || "No note recorded."}</p>
                    </>
                  ) : editable ? (
                    <MutationForm
                      label="Record observation"
                      submit={async (data) => {
                        await api(
                          `/v1/inspections/${id}/observations`,
                          json({
                            id: crypto.randomUUID(),
                            site_id: site,
                            step_id: step.id,
                            result: text(data, "result"),
                            note: text(data, "note"),
                          }),
                        );
                        detail.reload();
                        notify("Observation recorded.");
                      }}
                    >
                      <Field label="Finding">
                        <select name="result" required>
                          <option value="">Choose a result…</option>
                          <option value="pass">Pass</option>
                          <option value="fail">Fail</option>
                          <option value="unknown">
                            Unknown / cannot verify
                          </option>
                        </select>
                      </Field>
                      <Field label="Observation note">
                        <textarea name="note" maxLength={4000} rows={2} />
                      </Field>
                    </MutationForm>
                  ) : (
                    <p className="muted">No observation recorded.</p>
                  )}
                </div>
              </div>
            );
          })
        )}
        <div className="panel-content">
          <Button
            onClick={() => setSubmit(true)}
            disabled={
              !editable ||
              !procedure ||
              procedure.steps.length !== record.observations.length
            }
          >
            <ShieldCheck size={16} />
            Submit completed inspection
          </Button>
        </div>
      </Panel>
      <div className="knowledge-grid">
        <Panel
          title="Capture evidence"
          caption="Only captures confirmed for this asset can be attached."
        >
          <div className="panel-content">
            {record.capture_ids.map((c) => (
              <a className="evidence-link" key={c} href={`#/captures/${c}`}>
                <Camera size={17} />
                Capture {c.slice(0, 8)}
                <ArrowUpRight size={15} />
              </a>
            ))}
            {editable && (
              <MutationForm
                label="Attach confirmed capture"
                submit={async (data) => {
                  await api(
                    `${sitePath(site)}/inspections/${id}/evidence`,
                    json({ capture_id: text(data, "capture") }),
                  );
                  detail.reload();
                  notify("Evidence attached.");
                }}
              >
                <Field label="Capture">
                  <select name="capture" required>
                    <option value="">Select a confirmed capture…</option>
                    {captures.data
                      ?.filter((c) => !record.capture_ids.includes(c.id))
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.id.slice(0, 8)} · {date(c.created_at)}
                        </option>
                      ))}
                  </select>
                </Field>
              </MutationForm>
            )}
            {!record.capture_ids.length && !editable && (
              <p className="muted">No image evidence attached.</p>
            )}
          </div>
        </Panel>
        <Panel
          title="Independent review"
          caption="Submitted records can be reviewed by another authorized person."
        >
          <div className="panel-content">
            {reviews.error && (
              <ErrorPanel message={reviews.error} retry={reviews.reload} />
            )}{" "}
            {reviews.data?.map((r) => (
              <article className="source-card" key={r.id}>
                <Status value={r.outcome} />
                <p>{r.note}</p>
                <small>{date(r.created_at)}</small>
              </article>
            ))}
            {record.status === "submitted" &&
            ["supervisor", "manager"].includes(role) &&
            !session.demo &&
            session.me.id ? (
              <MutationForm
                label="Record review"
                submit={async (data) => {
                  await api(
                    `${sitePath(site)}/inspections/${id}/reviews`,
                    json({
                      id: crypto.randomUUID(),
                      outcome: text(data, "outcome"),
                      note: text(data, "note"),
                    }),
                  );
                  reviews.reload();
                  notify("Independent review recorded.");
                }}
              >
                <Field label="Outcome">
                  <select name="outcome">
                    <option value="accepted">Accepted</option>
                    <option value="follow_up">Follow-up required</option>
                  </select>
                </Field>
                <Field label="Review note">
                  <textarea name="note" required maxLength={4000} rows={3} />
                </Field>
              </MutationForm>
            ) : (
              <p className="muted">
                Requires a submitted inspection and an independent supervisor
                credential.
              </p>
            )}
          </div>
        </Panel>
      </div>
      {submit && (
        <Modal title="Submit this inspection?" close={() => setSubmit(false)}>
          <p className="modal-intro">
            All observations will become immutable. Review the findings and
            attached capture evidence before submitting.
          </p>
          <div className="form-actions">
            <Button variant="secondary" onClick={() => setSubmit(false)}>
              Review again
            </Button>
            <Button busy={busy} onClick={finish}>
              Submit inspection
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
