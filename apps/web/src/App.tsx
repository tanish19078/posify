import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Boxes,
  Camera,
  ChevronDown,
  CircleHelp,
  ClipboardCheck,
  Command,
  LayoutDashboard,
  Library,
  LogOut,
  Menu,
  ScanLine,
  Search,
  Settings2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { request } from "./api";
import { Badge, Button, ErrorPanel, Field, Modal } from "./components/ui";
import { makeApi, useWorkspace, WorkspaceContext } from "./context";
import { demoSession } from "./demo";
import { useLoad, useRoute } from "./hooks";
import { Activity } from "./pages/Activity";
import { Assets } from "./pages/Assets";
import Captures from "./pages/Captures";
import { Catalogue } from "./pages/Catalogue";
import { Inspections } from "./pages/Inspections";
import { Knowledge } from "./pages/Knowledge";
import { Overview } from "./pages/Overview";
import type { Asset, Factory, Principal, Session } from "./types";

const navigation: [string, string, LucideIcon][] = [
  ["overview", "Overview", LayoutDashboard],
  ["captures", "Captures", Camera],
  ["assets", "Factory assets", Boxes],
  ["catalogue", "Global catalogue", Library],
  ["knowledge", "Knowledge", BookOpen],
  ["inspections", "Inspections", ClipboardCheck],
];
export default function App() {
  const [session, setSession] = useState<Session>(demoSession);
  const [connectionVersion, setConnectionVersion] = useState(0);
  const [site, setSite] = useState(demoSession.factories[0].id);
  const [connect, setConnect] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [message, setMessage] = useState("");
  const [help, setHelp] = useState(false);
  const [search, setSearch] = useState(false);
  const route = useRoute();
  const page = route[0] || "captures";
  useEffect(() => { window.scrollTo({top: 0, left: 0}); }, [route.join("/")]);
  const navigate = (path: string) => {
    location.hash = "/" + path;
    setMobile(false);
  };
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(""), 6000);
    return () => clearTimeout(timer);
  }, [message]);
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearch(true);
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
  const factory = session.factories.find((x) => x.id === site);
  const role = session.me.is_admin
    ? "manager"
    : session.me.memberships.find((x) => x.site_id === site)?.role || "viewer";
  const api = useMemo(() => makeApi(session), [session]);
  return (
    <WorkspaceContext.Provider
      value={{ session, site, role, api, notify: setMessage, navigate }}
    >
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to content
      </a>
      <div className="app-shell">
        {mobile && (
          <button
            className="nav-backdrop"
            aria-label="Close navigation"
            onClick={() => setMobile(false)}
          />
        )}
        <aside className={`sidebar ${mobile ? "is-open" : ""}`}>
          <a href="#/overview" className="brand">
            <span className="brand-mark">
              <ScanLine size={22} />
            </span>
            <span>
              Field<span className="brand-light">workspace</span>
            </span>
          </a>
          <div className="workspace-label">YOUR WORKSPACE</div>
          <nav aria-label="Main navigation">
            {navigation.map(([id, label, Icon]) => (
              <a
                key={id}
                href={`#/${id}`}
                onClick={() => setMobile(false)}
                aria-current={page === id ? "page" : undefined}
                className={page === id ? "active" : ""}
              >
                <Icon size={19} />
                <span>{label}</span>
                {page === id && <span className="nav-dot" />}
              </a>
            ))}
          </nav>
          <div className="sidebar-note">
            <span className="note-icon">
              <ScanLine size={19} />
            </span>
            <strong>Evidence comes first.</strong>
            <p>
              Every identification stays reviewable. You make the final call.
            </p>
            <a href="#/captures">
              Open capture workspace <ArrowUpRight size={14} />
            </a>
          </div>
          <nav className="nav-bottom" aria-label="Workspace tools">
            <a
              href="#/activity"
              aria-current={page === "activity" ? "page" : undefined}
            >
              <ClipboardCheck size={18} />
              Activity log
            </a>
            <button onClick={() => setConnect(true)}>
              <Settings2 size={18} />
              Connection settings
            </button>
            <button onClick={() => setHelp(true)}>
              <CircleHelp size={18} />
              Workspace guide
            </button>
          </nav>
          <div className="profile">
            <div className="avatar">
              {session.demo
                ? "DT"
                : (session.me.name || "User").slice(0, 2).toUpperCase()}
            </div>
            <div>
              <strong>{session.me.name || "Workspace administrator"}</strong>
              <span>{session.demo ? "Demo technician" : role}</span>
            </div>
            {!session.demo && (
              <button
                className="icon-button"
                aria-label="Disconnect backend"
                onClick={() => {
                  setSession(demoSession);
                  setSite(demoSession.factories[0].id);
                  navigate("captures");
                  setMessage("Disconnected. Credential removed from memory.");
                }}
              >
                <LogOut size={17} />
              </button>
            )}
          </div>
        </aside>
        <div className="workspace-main">
          <header className="topbar">
            <div className="topbar-left">
              <button
                className="icon-button mobile-menu"
                aria-label="Open navigation"
                onClick={() => setMobile(true)}
              >
                <Menu size={22} />
              </button>
              <span className="top-label">WORKSPACE</span>
              <span className="top-divider" />
              <div className="factory-picker">
                <span className="online-dot" />
                <select
                  aria-label="Active factory"
                  value={site}
                  onChange={(e) => {
                    setSite(e.target.value);
                    navigate("captures");
                  }}
                >
                  {session.factories.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} />
              </div>
            </div>
            <div className="topbar-right">
              <button className="search-button" onClick={() => setSearch(true)}>
                <Search size={16} />
                <span>Find an asset</span>
                <kbd>
                  <Command size={11} /> K
                </kbd>
              </button>
              <Badge tone={session.demo ? "neutral" : "green"}>
                {session.demo ? "Demo workspace" : "Connected"}
              </Badge>
            </div>
          </header>
          {session.demo && (
            <div className="demo-banner">
              <span>
                <span className="small-dot" />
                Explore the workbench. Registry records are sample data;
                detection and OCR use a real smoke-test image.
              </span>
              <button onClick={() => setConnect(true)}>
                Connect your backend <ArrowRight size={14} />
              </button>
            </div>
          )}
          <main
            id="main-content"
            tabIndex={-1}
            className="main-content"
            key={`${connectionVersion}:${session.demo}:${site}`}
          >
            {!site ? (
              <div className="empty">
                <h1>No factory access yet</h1>
                <p>Ask your administrator to provision a factory membership.</p>
                <Button onClick={() => setConnect(true)}>
                  Connection settings
                </Button>
              </div>
            ) : page === "captures" ? (
              <Captures captureId={route[1]} />
            ) : page === "assets" ? (
              <Assets assetId={route[1]} />
            ) : page === "catalogue" ? (
              <Catalogue />
            ) : page === "knowledge" ? (
              <Knowledge />
            ) : page === "inspections" ? (
              <Inspections inspectionId={route[1]} />
            ) : page === "overview" ? (
              <Overview />
            ) : page === "activity" ? (
              <Activity />
            ) : (
              <div className="empty">
                <h1>Page not found</h1>
                <Button onClick={() => navigate("captures")}>
                  Back to captures
                </Button>
              </div>
            )}
          </main>
          <footer className="workspace-footer">
            <span>
              <span className="online-dot" />
              {session.demo
                ? "Read-only demo · no changes are saved"
                : factory?.name || site}
            </span>
            <span>Evidence. Context. A human decision.</span>
          </footer>
        </div>
      </div>
      {message && (
        <div className="toast" role="status">
          <ScanLine size={19} />
          {message}
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setMessage("")}
          >
            <X size={16} />
          </button>
        </div>
      )}
      {connect && (
        <Connection
          close={() => setConnect(false)}
          connected={(value) => {
            setSession(value);
            setConnectionVersion((x) => x + 1);
            setSite(value.factories[0]?.id || "");
            setConnect(false);
            navigate("captures");
            setMessage(
              "Backend connected. Your credential is kept in memory for this tab only.",
            );
          }}
        />
      )}
      {help && (
        <Modal
          title="A workspace built around evidence"
          close={() => setHelp(false)}
        >
          <div className="guide">
            <p>
              <b>1. Capture.</b> Upload an equipment or nameplate photo. PNG and
              JPEG files up to 8 MiB are accepted.
            </p>
            <p>
              <b>2. Review.</b> Queue local detection and OCR. Review the
              detected region, raw text and any factory asset candidates.
            </p>
            <p>
              <b>3. Confirm.</b> Verify the physical asset and explicitly
              confirm its identity. A detector score alone does not establish
              identity.
            </p>
            <p>
              <b>4. Inspect.</b> Select an applicable factory procedure, record
              every step and submit the inspection.
            </p>
            <p>
              Shared catalogue knowledge stays separate from each factory’s
              installed asset records.
            </p>
            <a href="/images/CREDITS.md" target="_blank" rel="noreferrer">
              Demo image attribution and evidence notes ↗
            </a>
          </div>
        </Modal>
      )}
      {search && <AssetSearch close={() => setSearch(false)} />}
    </WorkspaceContext.Provider>
  );
}
function Connection({
  close,
  connected,
}: {
  close: () => void;
  connected: (session: Session) => void;
}) {
  const [token, setToken] = useState("");
  const [auth, setAuth] = useState<"bearer" | "bootstrap">("bearer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const credential = { token: token.trim(), auth };
      const me = await request<Principal>(credential, "/v1/me");
      const factories = await request<Factory[]>(credential, "/v1/workspaces");
      connected({ ...credential, me, factories, demo: false });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Connect your backend" close={close}>
      <p className="modal-intro">
        Use a provisioned workspace credential. Requests go to this origin’s
        API; your credential stays in memory.
      </p>
      <form onSubmit={submit}>
        <Field label="Credential type">
          <select
            value={auth}
            onChange={(e) => setAuth(e.target.value as typeof auth)}
          >
            <option value="bearer">Individual bearer token</option>
            <option value="bootstrap">Development bootstrap key</option>
          </select>
        </Field>
        <Field
          label="Access credential"
          hint="Refreshing or disconnecting clears the credential. No browser storage is used."
        >
          <input
            autoComplete="off"
            type="password"
            required
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Paste your access token"
          />
        </Field>
        {error && <ErrorPanel message={error} />}
        <div className="form-actions">
          <Button type="button" variant="secondary" onClick={close}>
            Keep exploring
          </Button>
          <Button busy={busy} disabled={!token.trim()}>
            Connect workspace <ArrowRight size={16} />
          </Button>
        </div>
      </form>
    </Modal>
  );
}
function AssetSearch({ close }: { close: () => void }) {
  const { api, site, navigate } = useWorkspace();
  const [query, setQuery] = useState("");
  const data = useLoad(
    (signal) =>
      api<Asset[]>(`/v1/assets?site_id=${encodeURIComponent(site)}&limit=500`, {
        signal,
      }),
    [site],
  );
  const results = data.data?.filter((a) =>
    [a.tag, a.model, a.manufacturer, a.serial, a.location]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <Modal title="Find a factory asset" close={close}>
      <div className="search-field">
        <Search size={18} />
        <input
          autoFocus
          aria-label="Search assets"
          placeholder="Tag, serial, manufacturer or location…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {data.error && <ErrorPanel message={data.error} retry={data.reload} />}
      <div className="search-results">
        {results?.slice(0, 20).map((a) => (
          <button
            key={a.id}
            onClick={() => {
              navigate("assets/" + a.id);
              close();
            }}
          >
            <span className="asset-icon">
              <Boxes size={20} />
            </span>
            <div>
              <strong>
                {a.tag} <span>{a.model}</span>
              </strong>
              <small>{a.location}</small>
            </div>
            <ArrowUpRight size={16} />
          </button>
        ))}
        {results?.length === 0 && <p>No assets match your search.</p>}
      </div>
      <small className="muted">
        Searches up to the first 500 assets in this factory.
      </small>
    </Modal>
  );
}
