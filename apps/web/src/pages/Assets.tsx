import {
  ArrowUpRight,
  Boxes,
  Layers,
  MapPin,
  Plus,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { json, readable, segment, sitePath } from "../api";
import {
  Badge,
  Button,
  Empty,
  ErrorPanel,
  Field,
  Loading,
  Modal,
  PageHead,
} from "../components/ui";
import { useWorkspace } from "../context";
import { useLoad } from "../hooks";
import type { Asset, Model } from "../types";

import { Filter, Input, MutationForm, text } from "../components/forms";
export function Assets({ assetId }: { assetId?: string }) {
  const { api, site, role, session, notify } = useWorkspace();
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<Asset>();
  const rows = useLoad(
    (signal) =>
      api<Asset[]>(`/v1/assets?site_id=${segment(site)}&limit=500`, { signal }),
    [site],
  );
  useEffect(() => {
    if (assetId && rows.data)
      setSelected(rows.data.find((a) => a.id === assetId));
  }, [assetId, rows.data]);
  const filtered = rows.data?.filter((a) =>
    [a.tag, a.model, a.manufacturer, a.serial, a.category, a.location]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <>
      <PageHead
        eyebrow="FACTORY REGISTRY"
        title="Assets, in context."
        description="The physical equipment in this facility. Each with its own identity and history."
        actions={
          <Button
            disabled={role !== "manager" || session.demo}
            onClick={() => setAdding(true)}
          >
            <Plus size={17} />
            Register asset
          </Button>
        }
      />
      <div className="section-toolbar">
        <Filter
          value={query}
          change={setQuery}
          placeholder="Search tag, serial, model or location…"
        />
        <span className="muted">
          {filtered?.length || 0} loaded assets · up to 500
        </span>
      </div>
      {rows.loading ? (
        <Loading />
      ) : rows.error ? (
        <ErrorPanel message={rows.error} retry={rows.reload} />
      ) : !filtered?.length ? (
        <Empty title={query ? "No matching assets" : "Your registry is ready"}>
          {query
            ? "Try another tag, manufacturer or location."
            : "Register the physical equipment installed in this factory."}
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Asset</th>
                <th>Manufacturer / model</th>
                <th>Location</th>
                <th>Serial</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => (
                <tr key={a.id}>
                  <td>
                    <button
                      className="table-title"
                      onClick={() => setSelected(a)}
                    >
                      <span className="asset-icon">
                        <Boxes size={20} />
                      </span>
                      <span>
                        <b>{a.tag}</b>
                        <small>{a.category}</small>
                      </span>
                    </button>
                  </td>
                  <td>
                    {a.manufacturer}
                    <small>{a.model}</small>
                  </td>
                  <td>
                    <span className="inline">
                      <MapPin size={13} />
                      {a.location}
                    </span>
                  </td>
                  <td className="mono">{a.serial || "Not recorded"}</td>
                  <td>
                    <button
                      className="icon-button"
                      aria-label={`View ${a.tag}`}
                      onClick={() => setSelected(a)}
                    >
                      <ArrowUpRight size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="section-footnote">
        <Layers size={16} />
        Factory asset records stay separate from the shared manufacturer
        catalogue.
      </div>
      {adding && (
        <Modal title="Register a factory asset" close={() => setAdding(false)}>
          <MutationForm
            label="Register asset"
            submit={async (data) => {
              await api(
                "/v1/assets",
                json({
                  site_id: site,
                  ...Object.fromEntries(
                    [
                      "tag",
                      "manufacturer",
                      "model",
                      "category",
                      "location",
                    ].map((k) => [k, text(data, k)]),
                  ),
                  serial: text(data, "serial") || null,
                }),
              );
              setAdding(false);
              rows.reload();
              notify("Factory asset registered.");
            }}
          >
            <div className="form-grid">
              {[
                "tag",
                "manufacturer",
                "model",
                "category",
                "location",
                "serial",
              ].map((name) => (
                <Input
                  key={name}
                  label={readable(name)}
                  name={name}
                  required={name !== "serial"}
                />
              ))}
            </div>
          </MutationForm>
        </Modal>
      )}
      {selected && (
        <AssetDetail
          asset={selected}
          close={() => setSelected(undefined)}
          updated={() => {
            setSelected(undefined);
            rows.reload();
          }}
        />
      )}
    </>
  );
}
function AssetDetail({
  asset,
  close,
  updated,
}: {
  asset: Asset;
  close: () => void;
  updated: () => void;
}) {
  const { api, site, role, session, notify } = useWorkspace();
  const models = useLoad(
    (signal) => api<Model[]>("/v1/catalog/models?limit=200", { signal }),
    [],
  );
  const link = useLoad(
    (signal) =>
      api<{ catalog_model_id: string } | null>(
        `${sitePath(site)}/assets/${asset.id}/catalog-link`,
        { signal },
      ),
    [site, asset.id],
  );
  return (
    <Modal title={asset.tag} close={close}>
      <div className="asset-detail-banner">
        <span className="asset-bubble">
          <Boxes size={25} />
        </span>
        <div>
          <h3>
            {asset.manufacturer} {asset.model}
          </h3>
          <p>
            {asset.category} · {asset.serial || "Serial not recorded"}
          </p>
        </div>
        <Badge tone="neutral">Revision {asset.revision}</Badge>
      </div>
      {role === "manager" && !session.demo ? (
        <MutationForm
          label="Update metadata"
          submit={async (data) => {
            await api(
              `${sitePath(site)}/assets/${asset.id}`,
              json(
                {
                  location: text(data, "location"),
                  category: text(data, "category"),
                  reason: text(data, "reason"),
                  expected_revision: asset.revision,
                },
                "PATCH",
              ),
            );
            notify("Asset metadata updated with revision protection.");
            updated();
          }}
        >
          <div className="form-grid">
            <Input label="Location" name="location" value={asset.location} />
            <Input label="Category" name="category" value={asset.category} />
          </div>
          <Input label="Reason for change" name="reason" />
        </MutationForm>
      ) : (
        <p className="notice">
          <MapPin size={17} />
          {asset.location}
        </p>
      )}
      <hr />
      <h3>Shared catalogue connection</h3>
      {link.loading ? (
        <Loading />
      ) : link.error ? (
        <ErrorPanel message={link.error} retry={link.reload} />
      ) : link.data ? (
        <p className="notice">
          <ShieldCheck size={17} />
          Linked to{" "}
          {models.data?.find((x) => x.id === link.data?.catalog_model_id)
            ?.model || link.data.catalog_model_id}
        </p>
      ) : role === "manager" && !session.demo ? (
        <MutationForm
          label="Confirm catalogue link"
          submit={async (data) => {
            await api(
              `${sitePath(site)}/assets/${asset.id}/catalog-link`,
              json({
                catalog_model_id: text(data, "model"),
                asset_confirmed: true,
              }),
            );
            link.reload();
            notify("Shared model linked to the factory asset.");
          }}
        >
          <Field label="Published model">
            <select name="model" required>
              <option value="">Choose a matching model…</option>
              {models.data
                ?.filter(
                  (m) =>
                    m.manufacturer.toLowerCase() ===
                      asset.manufacturer.toLowerCase() &&
                    m.model.toLowerCase() === asset.model.toLowerCase(),
                )
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.manufacturer} {m.model} · {m.variant}
                  </option>
                ))}
            </select>
          </Field>
          <label className="check-field">
            <input type="checkbox" required />I verified this manufacturer,
            model and variant.
          </label>
        </MutationForm>
      ) : (
        <p className="muted">
          No shared model linked. A factory manager can confirm a published
          catalogue match.
        </p>
      )}
    </Modal>
  );
}
