import { BookOpen, FileText, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { json, readable, segment } from "../api";
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
import type { Answer, Asset, Procedure } from "../types";

import { Input, MutationForm, text } from "../components/forms";
export function Knowledge() {
  const { api, site, session, role, notify } = useWorkspace();
  const [asset, setAsset] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
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
  async function ask(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setAnswer(undefined);
    try {
      setAnswer(
        await api<Answer>(
          "/v1/assistant/query",
          json({ site_id: site, asset_id: asset, question }),
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHead
        eyebrow="KNOWLEDGE / WITH PROVENANCE"
        title="Find the source. Then decide."
        description="Retrieve applicable factory procedures and linked global documents, with citations."
        actions={
          <Button
            disabled={role !== "manager" || session.demo}
            onClick={() => setAdding(true)}
          >
            <Plus size={17} />
            Add procedure
          </Button>
        }
      />
      <div className="knowledge-grid">
        <Panel
          title="Ask about an asset"
          caption="Answers stay grounded in available documents."
        >
          <form className="panel-content" onSubmit={ask}>
            <Field label="Factory asset">
              <select
                required
                disabled={busy}
                value={asset}
                onChange={(e) => {
                  setAsset(e.target.value);
                  setAnswer(undefined);
                }}
              >
                <option value="">Select an asset…</option>
                {assets.data?.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.tag} · {a.model}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Your question">
              <textarea
                required
                disabled={busy}
                maxLength={2000}
                rows={4}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="What does the applicable procedure say about nameplate readability?"
              />
            </Field>
            <Button busy={busy} disabled={!asset || !question.trim()}>
              <BookOpen size={16} />
              Find applicable sources
            </Button>
          </form>
        </Panel>
        <Panel
          title="Factory procedures"
          caption="Immutable, versioned instructions for this facility."
        >
          {procedures.loading ? (
            <Loading />
          ) : procedures.error ? (
            <ErrorPanel message={procedures.error} retry={procedures.reload} />
          ) : procedures.data?.length ? (
            procedures.data.map((p) => (
              <details className="procedure-row" key={p.id}>
                <summary>
                  <span className="document-icon">
                    <FileText size={19} />
                  </span>
                  <span>
                    <b>{p.title}</b>
                    <small>
                      {p.manufacturer} · {p.model}
                    </small>
                  </span>
                  <Badge tone="neutral">v{p.version}</Badge>
                </summary>
                <p className="source-text">{p.source_text}</p>
                <ol>
                  {p.steps.map((s) => (
                    <li key={s.id}>{s.instruction}</li>
                  ))}
                </ol>
              </details>
            ))
          ) : (
            <Empty title="No procedures yet">
              A factory manager can add versioned procedures.
            </Empty>
          )}
        </Panel>
      </div>
      {assets.error && (
        <ErrorPanel message={assets.error} retry={assets.reload} />
      )}{" "}
      {error && <ErrorPanel message={error} />}{" "}
      {answer && (
        <Panel
          title="Retrieved evidence"
          caption={answer.notice || readable(answer.mode)}
          action={<Badge tone="amber">Review required</Badge>}
        >
          <div className="panel-content">
            {answer.answer && <p className="answer-text">{answer.answer}</p>}
            {answer.sources.length ? (
              answer.sources.map((source) => (
                <article className="source-card" key={source.id}>
                  <div>
                    <Badge tone="neutral">{readable(source.source_kind)}</Badge>
                    <span className="mono">{source.id}</span>
                  </div>
                  <h3>
                    {source.title} · v{source.version}
                    {source.page_number ? ` · page ${source.page_number}` : ""}
                  </h3>
                  <p>{source.excerpt}</p>
                  {source.source_ref && (
                    <small>Source: {source.source_ref}</small>
                  )}
                </article>
              ))
            ) : (
              <Empty title="No supporting evidence found">
                Try a more specific question or add applicable source material.
              </Empty>
            )}
          </div>
        </Panel>
      )}
      {adding && (
        <Modal title="Add a factory procedure" close={() => setAdding(false)}>
          <MutationForm
            label="Save procedure version"
            submit={async (data) => {
              const selected = assets.data?.find(
                (a) => a.id === text(data, "asset"),
              );
              if (!selected) throw new Error("Select an asset.");
              const steps = text(data, "steps")
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean)
                .map((instruction, i) => ({
                  id: `step-${i + 1}`,
                  instruction,
                }));
              await api(
                "/v1/procedures",
                json({
                  site_id: site,
                  manufacturer: selected.manufacturer,
                  model: selected.model,
                  title: text(data, "title"),
                  version: Number(text(data, "version")),
                  source_text: text(data, "source"),
                  steps,
                }),
              );
              setAdding(false);
              procedures.reload();
              notify(
                "Procedure version saved. Existing inspection procedures stay unchanged.",
              );
            }}
          >
            <Field label="Manufacturer / model from asset">
              <select name="asset" required>
                <option value="">Choose an asset…</option>
                {assets.data?.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.manufacturer} {a.model}
                  </option>
                ))}
              </select>
            </Field>
            <div className="form-grid">
              <Input label="Procedure title" name="title" />
              <Input label="Version" name="version" type="number" value="1" />
            </div>
            <Field label="Source text">
              <textarea name="source" required maxLength={30000} rows={4} />
            </Field>
            <Field
              label="Checklist steps"
              hint="One instruction per line. Maximum 100 steps."
            >
              <textarea name="steps" required rows={4} />
            </Field>
          </MutationForm>
        </Modal>
      )}
    </>
  );
}
