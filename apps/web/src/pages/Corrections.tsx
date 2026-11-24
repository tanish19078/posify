import { Check, Info, Plus, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import { date, json, readable, segment, sitePath } from "../api";
import { MutationForm, text } from "../components/forms";
import {
  Badge,
  Button,
  Empty,
  ErrorPanel,
  Field,
  Loading,
  Modal,
  PageHead,
  Panel,
} from "../components/ui";
import { useWorkspace } from "../context";
import { useLoad } from "../hooks";
import type { Asset, Capture, Correction, Model } from "../types";

export function Corrections() {
  const { api, site, role, session, notify } = useWorkspace();
  const [statusFilter, setStatusFilter] = useState<
    "" | "pending" | "approved" | "rejected"
  >("");
  const [requesting, setRequesting] = useState(false);
  const [kind, setKind] = useState<"asset_catalog" | "capture_assignment">(
    "asset_catalog",
  );
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [deciding, setDeciding] = useState<{
    correction: Correction;
    decision: "approved" | "rejected";
  }>();

  const rows = useLoad(
    (signal) =>
      api<Correction[]>(
        `${sitePath(site)}/corrections${statusFilter ? "?status=" + statusFilter : ""}`,
        { signal },
      ),
    [site, statusFilter],
  );
  const assets = useLoad(
    (signal) =>
      api<Asset[]>(`/v1/assets?site_id=${segment(site)}&limit=500`, { signal }),
    [site],
  );
  const captures = useLoad(
    (signal) =>
      api<Capture[]>(`${sitePath(site)}/captures?limit=100`, { signal }),
    [site],
  );
  const models = useLoad(
    (signal) => api<Model[]>("/v1/catalog/models?limit=200", { signal }),
    [],
  );

  const canReview =
    (role === "supervisor" || role === "manager") && !session.demo;
  const canRequest = role === "manager" && !session.demo;

  function resolveEntity(c: Correction) {
    if (c.entity_kind === "asset_catalog") {
      const a = assets.data?.find((x) => x.id === c.entity_id);
      return a ? `${a.tag} · ${a.manufacturer} ${a.model}` : c.entity_id.slice(0, 8);
    }
    return `Capture ${c.entity_id.slice(0, 8)}`;
  }

  function resolveTargetValue(c: Correction, id: string) {
    if (c.entity_kind === "asset_catalog") {
      const m = models.data?.find((x) => x.id === id);
      return m ? `${m.manufacturer} ${m.model} · ${m.variant}` : id.slice(0, 8);
    }
    const a = assets.data?.find((x) => x.id === id);
    return a ? `${a.tag} · ${a.manufacturer} ${a.model}` : id.slice(0, 8);
  }

  const chosenAsset = assets.data?.find((a) => a.id === selectedAssetId);
  const applicableModels = models.data?.filter(
    (m) =>
      !chosenAsset ||
      (m.manufacturer.toLowerCase() === chosenAsset.manufacturer.toLowerCase() &&
        m.model.toLowerCase() === chosenAsset.model.toLowerCase()),
  );

  return (
    <>
      <PageHead
        eyebrow="GOVERNANCE / TWO-PERSON REVIEW"
        title="Corrections & link approvals."
        description="Managers request link or unattached capture corrections; an independent supervisor or manager approves or rejects."
        actions={
          <Button
            disabled={!canRequest}
            onClick={() => {
              setKind("asset_catalog");
              setSelectedAssetId("");
              setRequesting(true);
            }}
          >
            <Plus size={17} />
            Request correction
          </Button>
        }
      />
      <div className="section-toolbar">
        <div className="segmented">
          {(
            [
              ["", "All"],
              ["pending", "Pending"],
              ["approved", "Approved"],
              ["rejected", "Rejected"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              className={statusFilter === value ? "selected" : ""}
              onClick={() => setStatusFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="muted">Immutable audit trail</span>
      </div>
      {session.demo && (
        <div className="notice">
          <Info size={17} />
          Read-only demo workspace. Connect your backend with individual credentials to request or decide corrections.
        </div>
      )}
      {rows.loading ? (
        <Loading />
      ) : rows.error ? (
        <ErrorPanel message={rows.error} retry={rows.reload} />
      ) : !rows.data?.length ? (
        <Empty title="No correction requests">
          {statusFilter
            ? `No ${statusFilter} correction requests in this factory.`
            : "Correction requests for catalogue links or unattached captures appear here."}
        </Empty>
      ) : (
        <div className="panel-content">
          {rows.data.map((c) => {
            const isSelf =
              !!session.me.id && session.me.id === c.requested_by;
            const tone =
              c.status === "approved"
                ? "green"
                : c.status === "rejected"
                  ? "red"
                  : "amber";
            return (
              <Panel
                key={c.id}
                title={resolveEntity(c)}
                caption={`${c.entity_kind === "asset_catalog" ? "Asset catalogue link" : "Capture assignment"} · Requested ${date(c.created_at)}`}
                action={<Badge tone={tone}>{readable(c.status)}</Badge>}
              >
                <div className="panel-content">
                  <p>
                    <strong>Change:</strong>{" "}
                    <code>{resolveTargetValue(c, c.before_value)}</code> →{" "}
                    <code>{resolveTargetValue(c, c.after_value)}</code>
                  </p>
                  <p>
                    <strong>Reason:</strong> {c.reason}
                  </p>
                  {c.review_note && (
                    <p className="muted">
                      <strong>Review note:</strong> {c.review_note}
                      {c.reviewed_at ? ` · ${date(c.reviewed_at)}` : ""}
                    </p>
                  )}
                  {c.status === "pending" && canReview && (
                    <>
                      {isSelf && (
                        <div className="notice">
                          <ShieldAlert size={16} />
                          Self-review blocked: a different supervisor or manager must review this request.
                        </div>
                      )}
                      <div className="form-actions">
                        <Button
                          variant="secondary"
                          disabled={isSelf}
                          onClick={() =>
                            setDeciding({ correction: c, decision: "rejected" })
                          }
                        >
                          <X size={15} />
                          Reject
                        </Button>
                        <Button
                          disabled={isSelf}
                          onClick={() =>
                            setDeciding({ correction: c, decision: "approved" })
                          }
                        >
                          <Check size={15} />
                          Approve
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              </Panel>
            );
          })}
        </div>
      )}
      {requesting && (
        <Modal
          title="Request a link correction"
          close={() => setRequesting(false)}
        >
          <p className="modal-intro">
            Corrections remain pending until another authorized reviewer approves or rejects them.
          </p>
          <div className="segmented">
            <button
              type="button"
              className={kind === "asset_catalog" ? "selected" : ""}
              onClick={() => setKind("asset_catalog")}
            >
              Asset catalogue link
            </button>
            <button
              type="button"
              className={kind === "capture_assignment" ? "selected" : ""}
              onClick={() => setKind("capture_assignment")}
            >
              Capture assignment
            </button>
          </div>
          <MutationForm
            label="Submit correction request"
            submit={async (data) => {
              const id = crypto.randomUUID();
              const reason = text(data, "reason");
              if (kind === "asset_catalog") {
                const assetId = text(data, "asset_id");
                const targetAsset = assets.data?.find((a) => a.id === assetId);
                if (!targetAsset) {
                  throw new Error("Select a valid factory asset.");
                }
                await api(
                  `${sitePath(site)}/assets/${segment(assetId)}/corrections`,
                  json({
                    id,
                    expected_revision: targetAsset.revision,
                    catalog_model_id: text(data, "catalog_model_id"),
                    reason,
                  }),
                );
              } else {
                const captureId = text(data, "capture_id");
                await api(
                  `${sitePath(site)}/captures/${segment(captureId)}/corrections`,
                  json({
                    id,
                    asset_id: text(data, "asset_id"),
                    reason,
                  }),
                );
              }
              setRequesting(false);
              rows.reload();
              notify("Correction request submitted for independent review.");
            }}
          >
            {kind === "asset_catalog" ? (
              <>
                <Field
                  label="Factory asset"
                  hint={
                    chosenAsset
                      ? `Current revision ${chosenAsset.revision}`
                      : undefined
                  }
                >
                  <select
                    name="asset_id"
                    required
                    value={selectedAssetId}
                    onChange={(e) => setSelectedAssetId(e.target.value)}
                  >
                    <option value="">Choose an asset…</option>
                    {assets.data?.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.tag} · {a.manufacturer} {a.model} (rev {a.revision})
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Target published catalogue model">
                  <select name="catalog_model_id" required>
                    <option value="">Choose target model variant…</option>
                    {applicableModels?.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.manufacturer} {m.model} · {m.variant}
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            ) : (
              <>
                <Field label="Confirmed unattached capture">
                  <select name="capture_id" required>
                    <option value="">Choose a capture…</option>
                    {captures.data?.map((cap) => (
                      <option key={cap.id} value={cap.id}>
                        {cap.id.slice(0, 8)} · {date(cap.created_at)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Target factory asset">
                  <select name="asset_id" required>
                    <option value="">Choose target asset…</option>
                    {assets.data?.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.tag} · {a.manufacturer} {a.model}
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            )}
            <Field label="Reason for correction">
              <textarea
                name="reason"
                required
                maxLength={2000}
                rows={3}
                placeholder="Explain the physical verification supporting this change…"
              />
            </Field>
          </MutationForm>
        </Modal>
      )}
      {deciding && (
        <Modal
          title={
            deciding.decision === "approved"
              ? "Approve correction?"
              : "Reject correction?"
          }
          close={() => setDeciding(undefined)}
        >
          <p className="modal-intro">
            Record your independent decision for{" "}
            <b>{resolveEntity(deciding.correction)}</b>. Decisions are immutable
            and audited.
          </p>
          <MutationForm
            label={
              deciding.decision === "approved"
                ? "Confirm approval"
                : "Confirm rejection"
            }
            submit={async (data) => {
              await api(
                `${sitePath(site)}/corrections/${segment(deciding.correction.id)}/decision`,
                json({
                  decision: deciding.decision,
                  note: text(data, "note"),
                }),
              );
              setDeciding(undefined);
              rows.reload();
              notify(`Correction ${deciding.decision}.`);
            }}
          >
            <Field label="Review note">
              <textarea
                name="note"
                required
                maxLength={2000}
                rows={3}
                placeholder="Document your independent check…"
              />
            </Field>
          </MutationForm>
        </Modal>
      )}
    </>
  );
}
