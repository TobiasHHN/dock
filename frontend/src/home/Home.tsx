// Home (Task 2.6): Dokumente, Tabellen, Workflows live aus dem Kanal `workspace` (L 7.2), „Neues Dokument“,
// Zähler für Aufgaben und Benachrichtigungen. Neue Einträge erscheinen ohne Neuladen und werden kurz hervorgehoben.
// Oben „Wartet auf dich“: die offenen Aufgaben aus `user:<id>` als Kurzliste (die volle Ansicht baut Task 4.5).
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { canEditStructure, useAuth } from "../api/client";
import { type InboxTask, useInbox } from "../layout/AppShell";
import type { WorkspaceData } from "../sync/core";
import { newId, submit, useChannel } from "../sync/store";
import { Icon, type IconName, relativeTime } from "../ui/icons";
import { toast } from "../ui/toasts";

type Item = {
  id: string; title?: string; name?: string; key?: string; owner?: unknown;
  updated_at?: string | null; latest_version?: number | null;
};

/** IDs, die nach dem ersten Laden neu dazukommen (für die Hervorhebung). */
function useNewIds(items: Item[] | undefined): Set<string> {
  const known = useRef<Set<string> | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!items) return;
    if (known.current === null) {
      known.current = new Set(items.map((i) => i.id));
      return;
    }
    const added = items.filter((i) => !known.current!.has(i.id)).map((i) => i.id);
    added.forEach((id) => known.current!.add(id));
    if (added.length) {
      setFresh(new Set(added));
      const t = setTimeout(() => setFresh(new Set()), 2000);
      return () => clearTimeout(t);
    }
  }, [items]);
  return fresh;
}

function ListCard({ title, icon, items, link, meta, empty }: {
  title: string; icon: IconName; items: Item[] | undefined; link: (i: Item) => string;
  meta: (i: Item) => ReactNode; empty: string;
}) {
  const fresh = useNewIds(items);
  const id = `card-${title.toLowerCase()}`;
  return (
    <section className="card" aria-labelledby={id}>
      <h2 id={id}>
        <span className="card-title"><Icon name={icon} />{title}</span>
        {items && items.length > 0 && <span className="count">{items.length}</span>}
      </h2>
      {!items ? (
        <div className="skeleton-list" aria-label="Lädt …">
          <span /><span /><span />
        </div>
      ) : items.length === 0 ? (
        <p className="empty">{empty}</p>
      ) : (
        <ul>
          {items.map((i) => (
            <li key={i.id} className={fresh.has(i.id) ? "flash" : ""}>
              <Link to={link(i)}>
                <span className="item-title">{i.title || i.name || "Ohne Titel"}</span>
                {meta(i)}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function isDueSoon(t: InboxTask): boolean {
  if (!t.due_at) return false;
  return Date.parse(t.due_at) - Date.now() < 24 * 3600 * 1000;
}

function WaitingForYou() {
  const { loading, openTasks } = useInbox();
  const shown = openTasks.slice(0, 4);
  return (
    <section className="panel" aria-labelledby="waiting">
      <div className="panel-head">
        <h2 id="waiting">Wartet auf dich</h2>
        {openTasks.length > 0 && <Link to="/inbox/tasks">Alle Aufgaben</Link>}
      </div>
      {loading ? (
        <div className="skeleton-list"><span /><span /></div>
      ) : shown.length === 0 ? (
        <p className="empty empty-done">
          <span className="empty-icon"><Icon name="check" size={18} strokeWidth={2.4} /></span>
          Alles erledigt, keine offenen Aufgaben.
        </p>
      ) : (
        <ul className="task-list">
          {shown.map((t) => {
            const due = isDueSoon(t);
            return (
              <li key={t.id}>
                <Link to="/inbox/tasks" className="task-row">
                  <span className={`task-icon ${due ? "warn" : ""}`}><Icon name={due ? "clock" : "file"} size={18} strokeWidth={1.8} /></span>
                  <span className="task-body">
                    <span className="task-title">Schritt „{t.step ?? "Aufgabe"}“</span>
                    <span className="task-meta">{relativeTime(t.created_at) ?? "offen"}</span>
                  </span>
                  {t.due_at ? (
                    <span className={`pill ${due ? "pill-warn" : ""}`}>fällig {relativeTime(t.due_at)}</span>
                  ) : (
                    <span className="pill">Offen</span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function Home() {
  const user = useAuth((s) => s.user);
  const ws = useChannel("workspace");
  const data = ws?.view as WorkspaceData | undefined;
  const { openTasks, unread } = useInbox();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const mayEdit = canEditStructure(user);

  async function createDocument() {
    const id = newId("doc");
    setCreating(true);
    try {
      await submit([
        { op: "doc.create", id, title: "Neues Dokument", blocks: [{ id: newId("blk"), type: "paragraph", props: { content: [] } }] } as never,
      ]);
      navigate(`/documents/${id}`);
    } catch (e) {
      toast(`Dokument konnte nicht angelegt werden: ${(e as Error).message}`, "error");
    } finally {
      setCreating(false);
    }
  }

  const docs = data?.documents as Item[] | undefined;
  const sortedDocs = docs && [...docs].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Hallo {user?.name?.split(" ")[0]}</h1>
          <p className="muted">
            <Link to="/inbox/tasks">{openTasks.length} offene {openTasks.length === 1 ? "Aufgabe" : "Aufgaben"}</Link>
            {" · "}
            {unread} ungelesene {unread === 1 ? "Benachrichtigung" : "Benachrichtigungen"}
          </p>
        </div>
        {mayEdit && (
          <div className="actions">
            <button className="primary" onClick={createDocument} disabled={creating}>
              <Icon name="plus" />
              {creating ? "Lege an …" : "Neues Dokument"}
            </button>
          </div>
        )}
      </div>
      {ws?.status === "error" && (
        <p className="alert" role="alert"><Icon name="alert" />Arbeitsbereich nicht verfügbar: {ws.error?.message}. Lade die Seite neu.</p>
      )}
      <WaitingForYou />
      <div className="home-grid">
        <ListCard
          title="Dokumente"
          icon="file"
          items={sortedDocs}
          link={(d) => `/documents/${d.id}`}
          meta={(d) =>
            d.owner ? <span className="chip">Schritt</span> : d.updated_at ? <span className="item-meta">{relativeTime(d.updated_at)}</span> : null
          }
          empty={mayEdit ? "Noch keine Dokumente. Lege oben das erste an." : "Noch keine Dokumente."}
        />
        <ListCard
          title="Tabellen"
          icon="table"
          items={data?.tables as Item[] | undefined}
          link={(t) => `/tables/${t.id}`}
          meta={(t) => t.key && <span className="chip" translate="no">{t.key}</span>}
          empty="Noch keine Tabellen."
        />
        <ListCard
          title="Workflows"
          icon="flow"
          items={data?.workflows as Item[] | undefined}
          link={(w) => `/workflows/${w.id}`}
          meta={(w) =>
            w.latest_version ? <span className="chip chip-success">v{w.latest_version}</span> : <span className="chip">Entwurf</span>
          }
          empty="Noch keine Workflows."
        />
      </div>
    </>
  );
}
