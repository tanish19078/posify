import { date, readable, sitePath } from "../api";
import { Empty, ErrorPanel, Loading, PageHead, Panel } from "../components/ui";
import { useWorkspace } from "../context";
import { useLoad } from "../hooks";

export function Activity() {
  const { api, site } = useWorkspace();
  const data = useLoad(
    (signal) =>
      api<
        {
          sequence: number;
          kind: string;
          entity_id: string;
          created_at: string;
          payload: unknown;
        }[]
      >(`${sitePath(site)}/audit?limit=100`, { signal }),
    [site],
  );
  return (
    <>
      <PageHead
        eyebrow="FACTORY / AUDIT TRAIL"
        title="A record of every decision."
        description="Capture creation, identity confirmations and inspection changes, in sequence."
      />
      {data.loading ? (
        <Loading />
      ) : data.error ? (
        <ErrorPanel message={data.error} retry={data.reload} />
      ) : !data.data?.length ? (
        <Empty title="No activity yet">
          Factory events will appear as work is recorded.
        </Empty>
      ) : (
        <Panel
          title="Factory events"
          caption="First 100 events, ordered by sequence."
        >
          {data.data.map((e) => (
            <details className="audit-row" key={e.sequence}>
              <summary>
                <span className="event-dot" />
                <div>
                  <strong>{readable(e.kind.replaceAll(".", " "))}</strong>
                  <small>
                    {e.entity_id} · Event {e.sequence}
                  </small>
                </div>
                <span>{date(e.created_at)}</span>
              </summary>
              <pre>{JSON.stringify(e.payload, null, 2)}</pre>
            </details>
          ))}
        </Panel>
      )}
    </>
  );
}
