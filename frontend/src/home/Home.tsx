// Home (Task 2.6): Dokumente, Tabellen, Workflows live aus dem Kanal `workspace` (L 7.2), „Neues Dokument“,
// Zähler für Aufgaben und Benachrichtigungen. Neue Einträge erscheinen ohne Neuladen und werden kurz hervorgehoben.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { canEditStructure, useAuth } from "../api/client";
import { useInboxCounts } from "../layout/AppShell";
import type { WorkspaceData } from "../sync/core";
import { newId, submit, useChannel } from "../sync/store";
import { toast } from "../ui/toasts";

type Item = { id: string; title?: string; name?: string; key?: string; owner?: unknown };

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

function ListCard({ title, items, link, empty, action }: {
  title: string; items: Item[] | undefined; link: (i: Item) => string; empty: string; action?: React.ReactNode;
}) {
  const fresh = useNewIds(items);
  return (
    <section className="card">
      <h2>
        <span>{title}</span>
        {action}
      </h2>
      {!items ? (
        <div className="muted small">Lädt …</div>
      ) : items.length === 0 ? (
        <div className="muted small">{empty}</div>
      ) : (
        <ul>
          {items.map((i) => (
            <li key={i.id} className={fresh.has(i.id) ? "flash" : ""}>
              <Link to={link(i)}>{i.title || i.name || "Ohne Titel"}</Link>
              {i.key && <span className="muted small">{i.key}</span>}
              {!!i.owner && <span className="muted small">Schritt</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Home() {
  const user = useAuth((s) => s.user);
  const ws = useChannel("workspace");
  const data = ws?.view as WorkspaceData | undefined;
  const counts = useInboxCounts();
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

  return (
    <>
      <h1>Hallo {user?.name?.split(" ")[0]}</h1>
      <p className="muted">
        <Link to="/inbox/tasks">{counts.tasks} offene Aufgaben</Link> · {counts.unread} ungelesene Benachrichtigungen
      </p>
      {ws?.status === "error" && <p className="error-text">Arbeitsbereich nicht verfügbar: {ws.error?.message}</p>}
      <div className="home-grid">
        <ListCard
          title="Dokumente"
          items={data?.documents}
          link={(d) => `/documents/${d.id}`}
          empty="Noch keine Dokumente"
          action={
            mayEdit && (
              <button className="primary" onClick={createDocument} disabled={creating}>
                {creating ? "Lege an …" : "Neues Dokument"}
              </button>
            )
          }
        />
        <ListCard title="Tabellen" items={data?.tables} link={(t) => `/tables/${t.id}`} empty="Noch keine Tabellen" />
        <ListCard title="Workflows" items={data?.workflows} link={(w) => `/workflows/${w.id}`} empty="Noch keine Workflows" />
      </div>
    </>
  );
}
