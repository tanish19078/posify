import {
  ArrowUpRight,
  Boxes,
  Check,
  FileText,
  Globe2,
  Plus,
  Upload,
} from "lucide-react";
import { useState } from "react";
import { json, readable } from "../api";
import {
  Badge,
  Button,
  Empty,
  ErrorPanel,
  Field,
  Loading,
  Modal,
  PageHead,
  Status,
} from "../components/ui";
import { useWorkspace } from "../context";
import { useLoad } from "../hooks";
import type { Document, Model } from "../types";

import { Filter, Input, MutationForm, text } from "../components/forms";
export function Catalogue() {
  const { api, session, notify } = useWorkspace();
  const [query, setQuery] = useState("");
  const [drafts, setDrafts] = useState(false);
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<Model>();
  const curator = session.me.is_admin || session.me.is_curator;
  const rows = useLoad(
    (signal) =>
      api<Model[]>(`/v1/catalog/models?limit=200&include_drafts=${drafts}`, {
        signal,
      }),
    [drafts],
  );
  const filtered = rows.data?.filter((m) =>
    [m.model, m.manufacturer, m.category]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <>
      <PageHead
        eyebrow="SHARED KNOWLEDGE / GLOBAL"
        title="One catalogue. Many factories."
        description="Manufacturer and model knowledge, shared without merging physical asset histories."
        actions={
          <Button
            onClick={() => setAdding(true)}
            disabled={!curator || session.demo}
          >
            <Plus size={17} />
            Add model
          </Button>
        }
      />
      <div className="section-toolbar">
        <Filter
          value={query}
          change={setQuery}
          placeholder="Find a manufacturer or model…"
        />
        {curator && (
          <label className="check-field">
            <input
              type="checkbox"
              checked={drafts}
              onChange={(e) => setDrafts(e.target.checked)}
            />
            Include drafts
          </label>
        )}
      </div>
      {rows.loading ? (
        <Loading />
      ) : rows.error ? (
        <ErrorPanel message={rows.error} retry={rows.reload} />
      ) : !filtered?.length ? (
        <Empty title="No models to show">
          Published manufacturer models will appear here.
        </Empty>
      ) : (
        <div className="catalogue-grid">
          {filtered.map((m) => (
            <button
              className="model-card"
              key={m.id}
              onClick={() => setSelected(m)}
            >
              <div className="model-card-top">
                <span className="model-icon">
                  <Boxes size={30} />
                </span>
                <Status value={m.status} />
              </div>
              <span className="eyebrow">{m.manufacturer}</span>
              <h2>{m.model}</h2>
              <p>{m.category}</p>
              <div className="model-card-footer">
                <span>{m.variant}</span>
                <span>
                  View knowledge <ArrowUpRight size={15} />
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
      <div className="section-footnote">
        <Globe2 size={16} />
        Showing up to 200 models. A source reference records provenance; it is
        not manufacturer verification.
      </div>
      {adding && (
        <Modal title="Add a shared model" close={() => setAdding(false)}>
          <p className="modal-intro">
            New models start as drafts. Review the source before publishing.
          </p>
          <MutationForm
            label="Create draft model"
            submit={async (data) => {
              await api(
                "/v1/catalog/models",
                json(
                  Object.fromEntries(
                    [
                      "manufacturer",
                      "model",
                      "category",
                      "variant",
                      "source_ref",
                    ].map((k) => [k, text(data, k)]),
                  ),
                ),
              );
              setAdding(false);
              rows.reload();
              notify("Catalogue draft created.");
            }}
          >
            <div className="form-grid">
              {[
                "manufacturer",
                "model",
                "category",
                "variant",
                "source_ref",
              ].map((k) => (
                <Input
                  key={k}
                  label={readable(k)}
                  name={k}
                  value={k === "variant" ? "base" : undefined}
                />
              ))}
            </div>
          </MutationForm>
        </Modal>
      )}
      {selected && (
        <ModelDetail
          model={selected}
          close={() => setSelected(undefined)}
          updated={rows.reload}
        />
      )}
    </>
  );
}
function ModelDetail({
  model,
  close,
  updated,
}: {
  model: Model;
  close: () => void;
  updated: () => void;
}) {
  const { api, session, notify } = useWorkspace();
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [published, setPublished] = useState(model.status === "published");
  const curator =
    (session.me.is_admin || session.me.is_curator) && !session.demo;
  const docs = useLoad(
    (signal) =>
      api<Document[]>(
        `/v1/catalog/models/${model.id}/documents?include_drafts=${curator}`,
        { signal },
      ),
    [model.id],
  );
  async function publish(path: string) {
    setBusy(true);
    setError("");
    try {
      await api(path, json({}));
      notify("Published after explicit review.");
      docs.reload();
      updated();
      if (path.includes("/models/")) setPublished(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={`${model.manufacturer} · ${model.model}`} close={close}>
      <div className="model-detail-head">
        <Badge tone="neutral">{model.variant}</Badge>
        <Status value={published ? "published" : "draft"} />
      </div>
      <p className="modal-intro">
        {model.category}
        <br />
        Source: {model.source_ref}
      </p>
      {error && <ErrorPanel message={error} />}{" "}
      {!published && curator && (
        <Button
          variant="secondary"
          busy={busy}
          onClick={() => publish(`/v1/catalog/models/${model.id}/publish`)}
        >
          <Check size={16} />
          Publish reviewed model
        </Button>
      )}
      <div className="panel-heading">
        <h3>Model documents</h3>
        {curator && (
          <Button variant="secondary" onClick={() => setAdding(!adding)}>
            <Upload size={15} />
            Import PDF
          </Button>
        )}
      </div>
      {adding && (
        <MutationForm
          label="Import PDF as draft"
          submit={async (data) => {
            const file = data.get("pdf") as File;
            if (file.size > 8 * 1024 * 1024)
              throw new Error("PDF must be 8 MiB or smaller.");
            const params = new URLSearchParams({
              title: text(data, "title"),
              revision: text(data, "revision"),
              source_ref: text(data, "source_ref"),
            });
            await api(`/v1/catalog/models/${model.id}/pdf?${params}`, {
              method: "POST",
              body: file,
              headers: { "Content-Type": "application/pdf" },
            });
            setAdding(false);
            docs.reload();
            notify(
              "PDF imported as a draft. Review extracted text before publishing.",
            );
          }}
        >
          <Input label="Document title" name="title" />
          <div className="form-grid">
            <Input label="Revision" name="revision" type="number" value="1" />
            <Input label="Source reference" name="source_ref" />
          </div>
          <Field label="PDF file">
            <input type="file" name="pdf" accept="application/pdf" required />
          </Field>
        </MutationForm>
      )}
      {docs.loading ? (
        <Loading />
      ) : docs.error ? (
        <ErrorPanel message={docs.error} retry={docs.reload} />
      ) : docs.data?.length ? (
        docs.data.map((d) => (
          <details className="document-row" key={d.id}>
            <summary>
              <FileText size={18} />
              <b>{d.title}</b>
              <span>r{d.revision}</span>
              <Status value={d.status} />
            </summary>
            <p className="source-text">{d.source_text}</p>
            <small>Source: {d.source_ref}</small>
            {d.status === "draft" && curator && (
              <Button
                variant="secondary"
                busy={busy}
                onClick={() => publish(`/v1/catalog/documents/${d.id}/publish`)}
              >
                Publish reviewed document
              </Button>
            )}
          </details>
        ))
      ) : (
        <Empty title="No documents yet">
          A curator can import source PDFs for this model.
        </Empty>
      )}
    </Modal>
  );
}
