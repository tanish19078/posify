import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Crop,
  Expand,
  FileImage,
  Focus,
  ImagePlus,
  Info,
  Layers,
  Loader2,
  ScanLine,
  ShieldCheck,
  Upload,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { date, json, readable, segment, sitePath } from "../api";
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
import { analysisErrorMessage } from "../analysisErrors";
import { useLoad } from "../hooks";
import type { Analysis, Asset, Assignment, Capture, Job } from "../types";

export default function Captures({ captureId }: { captureId?: string }) {
  const { api, site, role, navigate, notify } = useWorkspace();
  const [upload, setUpload] = useState(false);
  const list = useLoad(
    (signal) =>
      api<Capture[]>(`${sitePath(site)}/captures?limit=50`, { signal }),
    [site],
  );
  const selected = captureId || list.data?.[0]?.id;
  return (
    <>
      <PageHead
        eyebrow="IDENTIFY / REVIEW / CONFIRM"
        title="Capture review"
        description="Turn a field photo into evidence you can work with."
        actions={
          <Button disabled={role === "viewer"} onClick={() => setUpload(true)}>
            <ImagePlus size={17} />
            New capture
          </Button>
        }
      />
      <div className="workflow-strip">
        <span className="complete">
          <span>01</span> Capture
        </span>
        <ChevronRight size={14} />
        <span className="current">
          <span>02</span> Review evidence
        </span>
        <ChevronRight size={14} />
        <span>
          <span>03</span> Confirm asset
        </span>
        <div className="workflow-note">
          <ShieldCheck size={15} />
          You make the final call
        </div>
      </div>
      {list.loading ? (
        <Loading />
      ) : list.error ? (
        <ErrorPanel message={list.error} retry={list.reload} />
      ) : !selected ? (
        <Empty
          title="Your first capture starts here"
          action={
            <Button
              onClick={() => setUpload(true)}
              disabled={role === "viewer"}
            >
              <Upload size={16} />
              Upload a photo
            </Button>
          }
        >
          Photograph an equipment nameplate clearly. We’ll keep the image and
          extracted evidence together.
        </Empty>
      ) : (
        <>
          <div className="capture-switcher">
            <span className="eyebrow">RECENT CAPTURES</span>
            <div>
              {list.data?.map((capture, i) => (
                <button
                  key={capture.id}
                  className={selected === capture.id ? "selected" : ""}
                  onClick={() => navigate(`captures/${capture.id}`)}
                >
                  <FileImage size={15} />
                  {`Capture ${String(i + 1).padStart(2, "0")}`}
                  <small>{date(capture.created_at)}</small>
                </button>
              ))}
            </div>
            <small className="muted">Latest 50</small>
          </div>
          <Review key={`${site}:${selected}`} id={selected} />
        </>
      )}
      {upload && (
        <UploadModal
          close={() => setUpload(false)}
          saved={(id) => {
            setUpload(false);
            list.reload();
            navigate(`captures/${id}`);
            notify("Capture saved. Review the image, then run analysis.");
          }}
        />
      )}
    </>
  );
}
function UploadModal({
  close,
  saved,
}: {
  close: () => void;
  saved: (id: string) => void;
}) {
  const { api, site, session } = useWorkspace();
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  function choose(value?: File) {
    setError("");
    if (!value) return;
    if (!["image/png", "image/jpeg"].includes(value.type)) {
      setError("Choose a PNG or JPEG image.");
      return;
    }
    if (value.size > 8 * 1024 * 1024) {
      setError("The image must be 8 MiB or smaller.");
      return;
    }
    setFile(value);
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ capture: Capture }>(
        `${sitePath(site)}/captures`,
        { method: "POST", body: file, headers: { "Content-Type": file.type } },
      );
      saved(result.capture.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Add a field capture" close={close}>
      <p className="modal-intro">
        Use a clear photo with the full nameplate in frame. Image metadata is
        removed by the backend.
      </p>
      <form onSubmit={submit}>
        <label
          className={`dropzone ${drag ? "dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            choose(e.dataTransfer.files[0]);
          }}
        >
          <span className="upload-icon">
            <Upload size={26} />
          </span>
          <strong>{file ? file.name : "Drop a photo here, or browse"}</strong>
          <span>
            {file
              ? `${(file.size / 1024 / 1024).toFixed(2)} MiB · Ready to upload`
              : "PNG or JPEG · 8 MiB max · 6 MP max · 4096 px per side"}
          </span>
          <input
            aria-label="Choose capture image"
            type="file"
            accept="image/png,image/jpeg"
            onChange={(e) => choose(e.target.files?.[0])}
          />
        </label>
        {session.demo && (
          <div className="notice">
            <Info size={17} />
            Connect your backend to upload and analyze your own images.
          </div>
        )}
        {error && <ErrorPanel message={error} />}
        <div className="form-actions">
          <Button type="button" variant="secondary" onClick={close}>
            Cancel
          </Button>
          <Button busy={busy} disabled={!file || session.demo}>
            Save capture <ArrowRight size={16} />
          </Button>
        </div>
      </form>
    </Modal>
  );
}
function Review({ id }: { id: string }) {
  const { api, site, session, role, notify } = useWorkspace();
  const root = `${sitePath(site)}/captures/${segment(id)}`;
  const meta = useLoad((signal) => api<Capture>(root, { signal }), [site, id]);
  const analyses = useLoad(
    (signal) => api<Analysis[]>(root + "/analyses", { signal }),
    [site, id],
  );
  const assignment = useLoad(
    (signal) => api<Assignment | null>(root + "/confirm", { signal }),
    [site, id],
  );
  const assets = useLoad(
    (signal) =>
      api<Asset[]>(`/v1/assets?site_id=${segment(site)}&limit=500`, { signal }),
    [site],
  );
  const image = useLoad(
    (signal) =>
      api<Blob>(root + "/image", { signal, headers: { Accept: "image/png" } }),
    [site, id],
  );
  const [imageUrl, setImageUrl] = useState("");
  const [zoom, setZoom] = useState(1);
  const [crop, setCrop] = useState(false);
  const [overlay, setOverlay] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [job, setJob] = useState<Job>();
  const recoveredJobs = useLoad(
    (signal) => api<Job[]>(`${sitePath(site)}/jobs?limit=200`, { signal }),
    [site, id],
  );
  useEffect(() => {
    const active = recoveredJobs.data?.find(
      (row) =>
        row.capture_id === id && ["queued", "running"].includes(row.status),
    );
    if (active) setJob(active);
  }, [recoveredJobs.data]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"detect_ocr" | "ocr">("detect_ocr");
  const [selectedAsset, setSelectedAsset] = useState("");
  const [attested, setAttested] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const rawAnalysis = job?.result || analyses.data?.at(-1);
  const latest = rawAnalysis
    ? {
        ...rawAnalysis,
        detections: rawAnalysis.detections || [],
        pipeline_warnings: rawAnalysis.pipeline_warnings || [],
      }
    : undefined;
  useEffect(() => {
    if (!image.data) return;
    const url = URL.createObjectURL(image.data);
    setImageUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [image.data]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api<Job>(`${sitePath(site)}/jobs/${job.id}`, {
        signal: controller.signal,
      })
        .then(setJob)
        .catch((e) => {
          if (!controller.signal.aborted) {
            setError(e.message);
            setJob(undefined);
          }
        });
    }, 1800);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [job, site]);
  useEffect(() => {
    if (job?.status === "succeeded") {
      analyses.reload();
      notify(
        "Analysis complete. Review the evidence before confirming an asset.",
      );
    }
  }, [job?.status]);
  const processing = !!job && ["queued", "running"].includes(job.status);
  async function analyze() {
    setBusy(true);
    setError("");
    try {
      setJob(
        await api<Job>(root + "/jobs", json({ id: crypto.randomUUID(), mode })),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    setBusy(true);
    try {
      setJob(
        await api<Job>(`${sitePath(site)}/jobs/${job!.id}/cancel`, json({})),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api(
        root + "/confirm",
        json({ asset_id: selectedAsset, asset_confirmed: true }),
      );
      setConfirm(false);
      assignment.reload();
      notify(
        "Asset confirmed. This capture is now linked to the factory record.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (meta.loading) return <Loading />;
  if (meta.error)
    return <ErrorPanel message={meta.error} retry={meta.reload} />;
  const capture = meta.data!;
  const box = latest?.detections[0]?.box;
  const confirmedAsset = assets.data?.find(
    (x) => x.id === assignment.data?.asset_id,
  );
  const photo = (
    <div className={`image-stage ${crop ? "cropped" : ""}`}>
      <svg
        role="img"
        aria-label="Equipment capture with measured detection regions"
        viewBox={
          crop && box
            ? `${box[0]} ${box[1]} ${box[2] - box[0]} ${box[3] - box[1]}`
            : `0 0 ${capture.width} ${capture.height}`
        }
        style={{ transform: `scale(${zoom})` }}
      >
        {imageUrl && (
          <image
            href={imageUrl}
            width={capture.width}
            height={capture.height}
          />
        )}{" "}
        {overlay &&
          latest?.detections.map((d, i) => (
            <g key={i}>
              <rect
                className="detection-box"
                x={d.box[0]}
                y={d.box[1]}
                width={d.box[2] - d.box[0]}
                height={d.box[3] - d.box[1]}
              />
              <title>
                {d.label}: {d.confidence.toFixed(3)} detector score
              </title>
            </g>
          ))}
      </svg>
      {!imageUrl &&
        (image.error ? (
          <ErrorPanel message={image.error} retry={image.reload} />
        ) : (
          <Loading />
        ))}
      {latest && (
        <span className="image-corner">
          <span className="amber-dot" />
          {latest.detections.length} detected region
          {latest.detections.length === 1 ? "" : "s"}
        </span>
      )}
    </div>
  );
  return (
    <>
      {error && <ErrorPanel message={error} />}
      <div className="review-grid">
        <Panel
          className="capture-panel"
          title="The original evidence"
          caption={`${capture.width} × ${capture.height} px · ${date(capture.created_at)}`}
          action={
            <Badge tone="neutral">
              <FileImage size={12} />
              Capture
            </Badge>
          }
        >
          <div className="image-toolbar">
            <div className="segmented">
              <button
                className={!crop ? "selected" : ""}
                onClick={() => {
                  setCrop(false);
                  setZoom(1);
                }}
              >
                Original
              </button>
              <button
                disabled={!box}
                className={crop ? "selected" : ""}
                onClick={() => {
                  setCrop(true);
                  setZoom(1);
                }}
              >
                <Crop size={13} />
                Nameplate crop
              </button>
            </div>
            <button
              className={`icon-button ${overlay ? "toggled" : ""}`}
              title="Toggle detection overlay"
              aria-label="Toggle detection overlay"
              aria-pressed={overlay}
              onClick={() => setOverlay(!overlay)}
            >
              <Focus size={17} />
            </button>
          </div>
          {photo}
          <div className="image-bottom">
            <span>
              <ShieldCheck size={14} />
              Original coordinates preserved
            </span>
            <div>
              <button
                className="icon-button"
                aria-label="Zoom out"
                disabled={zoom <= 1}
                onClick={() => setZoom(Math.max(1, zoom - 0.25))}
              >
                <ZoomOut size={16} />
              </button>
              <span>{Math.round(zoom * 100)}%</span>
              <button
                className="icon-button"
                aria-label="Zoom in"
                disabled={zoom >= 3}
                onClick={() => setZoom(Math.min(3, zoom + 0.25))}
              >
                <ZoomIn size={16} />
              </button>
              <span className="toolbar-divider" />
              <button
                className="icon-button"
                aria-label="Expand capture"
                onClick={() => setFullscreen(true)}
              >
                <Expand size={16} />
              </button>
            </div>
          </div>
          <div className="photo-credit">
            Image evidence stays attached to this capture.
            {session.demo && (
              <>
                {" "}
                Photo:{" "}
                <a
                  href="https://commons.wikimedia.org/wiki/File:Nameplate_of_a_CT.jpg"
                  target="_blank"
                  rel="noreferrer"
                >
                  SAM31416 · CC BY-SA 4.0 ↗
                </a>
              </>
            )}
          </div>
        </Panel>
        <Panel
          className="evidence-panel"
          title="What the image tells us"
          caption="Machine output. Ready for your review."
          action={<ScanLine size={19} />}
        >
          {analyses.loading ? (
            <Loading />
          ) : analyses.error ? (
            <ErrorPanel message={analyses.error} retry={analyses.reload} />
          ) : latest ? (
            <>
              <div className="detection-summary">
                <span className="detection-icon">
                  <ScanLine size={23} />
                </span>
                <div>
                  <strong>
                    {latest.detections.length
                      ? "Nameplate region detected"
                      : "OCR analysis complete"}
                  </strong>
                  <small>{latest.detector_revision || latest.engine}</small>
                </div>
                <Badge tone="green">Processed</Badge>
              </div>
              {latest.detections.length > 0 && (
                <div className="score-row">
                  <span>
                    Detector score <Info size={13} />
                  </span>
                  <b>{latest.detections[0].confidence.toFixed(3)}</b>
                  <div className="score-track">
                    <span
                      style={{
                        width: `${latest.detections[0].confidence * 100}%`,
                      }}
                    />
                  </div>
                  <small>
                    A detector score measures region confidence, not asset
                    identity.
                  </small>
                </div>
              )}
              <div className="section-label">
                <span>EXTRACTED TEXT</span>
                <Badge tone="amber">Unverified OCR</Badge>
              </div>
              <div className="ocr-lines">
                {latest.lines.length ? (
                  latest.lines.map((line, i) => (
                    <div key={i}>
                      <span className="line-number">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <code>{line.text}</code>
                      <span className="ocr-confidence" title="OCR confidence">
                        {Math.round(line.confidence * 100)}%
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="muted">
                    No readable text was extracted. Try a closer, sharper
                    capture.
                  </p>
                )}
              </div>
              <div className="evidence-notice">
                <Info size={17} />
                <div>
                  <strong>
                    {latest.status === "candidate_found"
                      ? "A possible factory asset was found"
                      : "Identity needs your confirmation"}
                  </strong>
                  <p>
                    {latest.status === "candidate_found"
                      ? "Check the physical identifiers against the suggested record below."
                      : "Review the physical nameplate and select the correct factory record. OCR alone has not verified an asset."}
                  </p>
                </div>
              </div>
              {latest.pipeline_warnings.map((warning, i) => (
                <div className="notice" key={i}>
                  {readable(warning)}
                </div>
              ))}
            </>
          ) : (
            <Empty title="Ready when you are">
              Run analysis to locate the nameplate and extract readable text.
            </Empty>
          )}
          <div className="analysis-controls">
            <select
              aria-label="Analysis mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as typeof mode)}
            >
              <option value="detect_ocr">Nameplate detection + OCR</option>
              <option value="ocr">Full image OCR only</option>
            </select>
            <Button
              variant="secondary"
              busy={busy}
              disabled={
                processing ||
                recoveredJobs.loading ||
                !!recoveredJobs.error ||
                session.demo ||
                role === "viewer"
              }
              onClick={analyze}
            >
              <ScanLine size={16} />
              {latest ? "Run again" : "Analyze capture"}
            </Button>
          </div>
          {processing && (
            <div className="job-state" role="status">
              <Loader2 className="spin" size={16} />
              <span>{readable(job!.status)} · Waiting for worker updates</span>
              <button onClick={cancel} disabled={busy}>
                Cancel
              </button>
            </div>
          )}
          {job?.status === "failed" && (
            <ErrorPanel
              message={analysisErrorMessage(job.error_code)}
            />
          )}
        </Panel>
      </div>
      <Panel
        className="confirmation-panel"
        title="Connect the evidence to an asset"
        caption="Factory-specific identity. Explicitly confirmed by you."
        action={
          <Badge tone={assignment.data ? "green" : "amber"}>
            {assignment.data ? "Confirmed" : "Human review required"}
          </Badge>
        }
      >
        {assignment.loading ? (
          <Loading />
        ) : assignment.error ? (
          <ErrorPanel message={assignment.error} retry={assignment.reload} />
        ) : assignment.data ? (
          <div className="confirmed">
            <CheckCircle2 size={29} />
            <div>
              <h3>{confirmedAsset?.tag || assignment.data.asset_id}</h3>
              <p>
                Confirmed {date(assignment.data.confirmed_at)}. This image can
                now be attached to inspections for this asset.
              </p>
            </div>
            <a className="button secondary" href="#/inspections">
              Continue to inspections <ArrowRight size={16} />
            </a>
          </div>
        ) : (
          <div className="confirmation-body">
            <div className="match-explanation">
              <span className="asset-bubble">
                <Layers size={23} />
              </span>
              <div>
                <h3>
                  {latest?.candidates.length
                    ? `${latest.candidates.length} possible match${latest.candidates.length === 1 ? "" : "es"}`
                    : "Select a factory asset"}
                </h3>
                <p>
                  {latest?.candidates.length
                    ? "Candidates are suggestions. Verify the tag or serial before confirming."
                    : "No automatic identity has been accepted. Match the physical tag or serial to your registry."}
                </p>
              </div>
            </div>
            <div className="confirm-fields">
              {assets.error ? (
                <ErrorPanel message={assets.error} retry={assets.reload} />
              ) : (
                <Field label="Factory asset">
                  <select
                    aria-label="Factory asset"
                    value={selectedAsset}
                    onChange={(e) => {
                      setSelectedAsset(e.target.value);
                      setAttested(false);
                    }}
                  >
                    <option value="">Choose a verified registry record…</option>
                    {assets.data?.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.tag} · {a.manufacturer} {a.model}
                        {latest?.candidates.some((c) => c.id === a.id)
                          ? " · suggested"
                          : ""}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={attested}
                  onChange={(e) => setAttested(e.target.checked)}
                />
                I checked the physical asset against this record.
              </label>
              <Button
                disabled={
                  !selectedAsset ||
                  !attested ||
                  session.demo ||
                  role === "viewer"
                }
                onClick={() => setConfirm(true)}
              >
                <ShieldCheck size={16} />
                Confirm asset <ArrowRight size={16} />
              </Button>
              {!assets.loading && assets.data?.length === 0 && (
                <a className="text-link" href="#/assets">
                  Register an asset first →
                </a>
              )}
            </div>
          </div>
        )}
        {recoveredJobs.error && (
          <ErrorPanel
            message={recoveredJobs.error}
            retry={recoveredJobs.reload}
          />
        )}
      </Panel>
      <div className="capture-bottom-note">
        <ShieldCheck size={16} />
        <span>
          Detection finds a region. OCR reads text. You establish identity.
        </span>
        <span className="mono muted">{id.slice(0, 8)}</span>
      </div>
      {fullscreen && (
        <Modal title="Capture evidence" close={() => setFullscreen(false)}>
          <div className="expanded-image">{photo}</div>
        </Modal>
      )}
      {confirm && (
        <Modal
          title="Confirm this asset identity?"
          close={() => setConfirm(false)}
        >
          <p className="modal-intro">
            Link this capture to{" "}
            <b>{assets.data?.find((x) => x.id === selectedAsset)?.tag}</b>. This
            confirmation is recorded in the factory audit trail. Existing
            assignments cannot be silently replaced.
          </p>
          <div className="form-actions">
            <Button variant="secondary" onClick={() => setConfirm(false)}>
              Review again
            </Button>
            <Button busy={busy} onClick={save}>
              <Check size={17} />
              Confirm identity
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
