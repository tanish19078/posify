import {
  ArrowRight,
  ArrowUpRight,
  Boxes,
  Camera,
  ChevronRight,
  ClipboardCheck,
} from "lucide-react";
import { date, segment, sitePath } from "../api";
import { Empty, ErrorPanel, Loading, PageHead, Panel } from "../components/ui";
import { useWorkspace } from "../context";
import { useLoad } from "../hooks";
import type { Asset, Capture, Inspection } from "../types";

export function Overview() {
  const { api, site } = useWorkspace();
  const data = useLoad(
    async (signal) => {
      const [assets, captures, inspections] = await Promise.all([
        api<Asset[]>(`/v1/assets?site_id=${segment(site)}&limit=500`, {
          signal,
        }),
        api<Capture[]>(`${sitePath(site)}/captures?limit=200`, { signal }),
        api<Inspection[]>(
          `/v1/inspections?site_id=${segment(site)}&limit=200`,
          { signal },
        ),
      ]);
      return { assets, captures, inspections };
    },
    [site],
  );
  return (
    <>
      <PageHead
        eyebrow="YOUR FACILITY / AT A GLANCE"
        title="A little clarity for the field."
        description="Pick up your next capture, review the registry or continue an inspection."
        actions={
          <a className="button primary" href="#/captures">
            <Camera size={17} />
            Open capture workspace
          </a>
        }
      />
      {data.loading ? (
        <Loading />
      ) : data.error ? (
        <ErrorPanel message={data.error} retry={data.reload} />
      ) : (
        <>
          <div className="stat-grid">
            {[
              [Boxes, "Factory assets", data.data!.assets.length, "assets"],
              [Camera, "Captures", data.data!.captures.length, "captures"],
              [
                ClipboardCheck,
                "Open inspections",
                data.data!.inspections.filter((i) => i.status === "open")
                  .length,
                "inspections",
              ],
            ].map(([Icon, label, count, path]) => {
              const I = Icon as typeof Boxes;
              return (
                <a className="stat-card" key={String(path)} href={`#/${path}`}>
                  <span className="stat-icon">
                    <I size={21} />
                  </span>
                  <span>{String(label)}</span>
                  <strong>{String(count)}</strong>
                  <ArrowUpRight size={19} />
                </a>
              );
            })}
          </div>
          <div className="overview-grid">
            <a className="overview-feature" href="#/captures">
              <div>
                <span className="eyebrow">THE CAPTURE WORKBENCH</span>
                <h2>
                  A photo.
                  <br />A reviewable result.
                </h2>
                <p>
                  Locate the plate, examine the text and confirm the physical
                  asset.
                </p>
                <span className="button primary">
                  Review captures <ArrowRight size={16} />
                </span>
              </div>
              <div className="feature-illustration">
                <ScanIcon />
              </div>
            </a>
            <Panel
              title="Continue an inspection"
              caption="Open records in this factory."
            >
              {data
                .data!.inspections.filter((i) => i.status === "open")
                .slice(0, 4)
                .map((i) => (
                  <a
                    key={i.id}
                    className="list-row"
                    href={`#/inspections/${i.id}`}
                  >
                    <span className="asset-icon">
                      <ClipboardCheck size={20} />
                    </span>
                    <div>
                      <strong>
                        {data.data!.assets.find((a) => a.id === i.asset_id)
                          ?.tag || i.id.slice(0, 8)}
                      </strong>
                      <small>{date(i.created_at)}</small>
                    </div>
                    <ChevronRight size={16} />
                  </a>
                ))}
              {!data.data!.inspections.some((i) => i.status === "open") && (
                <Empty title="All clear for now">
                  No open inspections in the loaded records.
                </Empty>
              )}
            </Panel>
          </div>
          <div className="section-footnote">
            Counts reflect loaded records: up to 500 assets and 200 captures /
            inspections.
          </div>
        </>
      )}
    </>
  );
}
function ScanIcon() {
  return (
    <svg viewBox="0 0 240 210" fill="none" aria-hidden="true">
      <rect x="25" y="25" width="180" height="155" rx="18" fill="#e4e8dc" />
      <rect
        x="50"
        y="65"
        width="130"
        height="82"
        rx="6"
        fill="#fffefa"
        stroke="#8b987d"
      />
      <path
        d="M65 85h74m-74 15h98m-98 15h60m-60 15h87"
        stroke="#b7bcae"
        strokeWidth="4"
      />
      <path
        d="M40 80V55h25m100 0h25v25m0 50v25h-25m-100 0H40v-25"
        stroke="#53644c"
        strokeWidth="3"
      />
      <path d="M25 109h181" stroke="#bf9b4a" strokeWidth="2" />
    </svg>
  );
}
