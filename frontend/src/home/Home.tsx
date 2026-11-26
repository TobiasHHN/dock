// Home (Task 2.6, B8): nur Dokumente live aus dem Kanal `workspace` (L 7.2); Tabellen und Workflows sind Blätter der Dokumente, „Neues Dokument“,
// Baum wie in Confluence: je Workflow das Übersichtsdokument, darunter aufklappbar seine Schritt-Dokumente (homeModel.ts),
// Zähler für Aufgaben und Benachrichtigungen. Neue Einträge erscheinen ohne Neuladen und werden kurz hervorgehoben.
// Aufgaben stehen nicht auf Home, dafür gibt es die eigene Seite /inbox/tasks.
import { type DragEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { canEditDocument, canEditStructure, useAuth } from "../api/client";
import type { WorkspaceData } from "../sync/core";
import { newId, submit, useChannel } from "../sync/store";
import { Icon, relativeTime } from "../ui/icons";
import { type HomeDoc, type HomeGroup, type HomeWorkflow, groupDocuments, loadExpanded, saveExpanded } from "./homeModel";
import { ImportDialog } from "../imports/ImportDialog";
import { checkFile } from "../imports/importModel";
import { toast } from "../ui/toasts";

type Item = { id: string };

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

function DocRow({ doc, fresh, child }: { doc: HomeDoc; fresh: Set<string>; child?: boolean }) {
  return (
    <li className={`${fresh.has(doc.id) ? "flash" : ""} ${child ? "tree-child" : ""}`}>
      <Link to={`/documents/${doc.id}`}>
        <span className="item-title"><Icon name="file" />{doc.title || "Ohne Titel"}</span>
        {doc.updated_at ? <span className="item-meta">{relativeTime(doc.updated_at)}</span> : null}
      </Link>
    </li>
  );
}

function WorkflowGroup({ group, open, onToggle, fresh }: {
  group: HomeGroup; open: boolean; onToggle: () => void; fresh: Set<string>;
}) {
  const { workflow, overview, children } = group;
  const title = overview?.title || workflow.name || "Workflow";
  const listId = `wf-docs-${workflow.id}`;
  return (
    <li className={`tree-group ${overview && fresh.has(overview.id) ? "flash" : ""}`}>
      <div className="tree-row">
        <button
          className="ghost tree-toggle" onClick={onToggle} disabled={children.length === 0}
          aria-expanded={open} aria-controls={listId}
          aria-label={`${open ? "Dokumente ausblenden" : "Dokumente anzeigen"}: ${title}`}
        >
          <span className={`tree-chevron ${open ? "open" : ""}`}><Icon name="chevronRight" /></span>
        </button>
        <Link to={overview ? `/documents/${overview.id}` : `/workflows/${workflow.id}`}>
          <span className="item-title"><Icon name="flow" />{title}</span>
          <span className="item-meta">{children.length} {children.length === 1 ? "Dokument" : "Dokumente"}</span>
        </Link>
      </div>
      {open && children.length > 0 && (
        <ul id={listId} className="tree-children">
          {children.map((d) => <DocRow key={d.id} doc={d} fresh={fresh} child />)}
        </ul>
      )}
    </li>
  );
}

function DocumentTree({ docs, workflows, empty, onImport }: {
  docs: HomeDoc[] | undefined; workflows: HomeWorkflow[]; empty: string; onImport?: () => void;
}) {
  const fresh = useNewIds(docs);
  const [expanded, setExpanded] = useState<Set<string>>(loadExpanded);
  const toggle = (id: string) => setExpanded((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    saveExpanded(next);
    return next;
  });
  const { groups, loose } = docs ? groupDocuments(docs, workflows) : { groups: [], loose: [] };
  const allOpen = groups.length > 0 && groups.every((g) => expanded.has(g.workflow.id));
  const setAll = (open: boolean) => {
    const next = open ? new Set(groups.map((g) => g.workflow.id)) : new Set<string>();
    saveExpanded(next);
    setExpanded(next);
  };
  return (
    <section className="card" aria-labelledby="card-dokumente">
      <h2 id="card-dokumente">
        <span className="card-title"><Icon name="file" />Dokumente</span>
        {docs && docs.length > 0 && <span className="count">{docs.length}</span>}
        <span className="card-actions">
          {groups.length > 0 && (
            <button className="ghost card-action" onClick={() => setAll(!allOpen)}>
              {allOpen ? "Alle zuklappen" : "Alle aufklappen"}
            </button>
          )}
          {onImport && <button className="ghost card-action" onClick={onImport}>Importieren</button>}
        </span>
      </h2>
      {!docs ? (
        <div className="skeleton-list" aria-label="Lädt …">
          <span /><span /><span />
        </div>
      ) : docs.length === 0 && groups.length === 0 ? (
        <p className="empty">{empty}</p>
      ) : (
        <ul className="doc-tree">
          {groups.map((g) => (
            <WorkflowGroup key={g.workflow.id} group={g} open={expanded.has(g.workflow.id)}
                           onToggle={() => toggle(g.workflow.id)} fresh={fresh} />
          ))}
          {loose.map((d) => <DocRow key={d.id} doc={d} fresh={fresh} />)}
        </ul>
      )}
    </section>
  );
}

export function Home() {
  const user = useAuth((s) => s.user);
  const ws = useChannel("workspace");
  const data = ws?.view as WorkspaceData | undefined;
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState<{ file: File | null } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const lastDoc = ((data?.documents ?? []) as HomeDoc[])
    .filter((d) => d.updated_at)
    .sort((a, b) => b.updated_at!.localeCompare(a.updated_at!))[0];
  const mayEdit = canEditStructure(user);
  const mayCreateDoc = canEditDocument(user);

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

  const hasFiles = (e: DragEvent<HTMLElement>) => mayEdit && !importing && Array.from(e.dataTransfer.types).includes("Files");

  return (
    <div
      className={dragOver ? "page-drop-over" : undefined}
      onDragOver={(e) => { if (hasFiles(e)) { e.preventDefault(); setDragOver(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragOver(false); }}
      onDrop={(e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        setDragOver(false);
        const f = e.dataTransfer.files[0];
        if (!f) return;
        const c = checkFile(f);
        if ("error" in c) toast(c.error, "error");
        else setImporting({ file: f });
      }}
    >
      <div className="page-head">
        <div>
          <h1 className="greeting">Hallo {user?.name?.split(" ")[0]}</h1>
          {lastDoc && (
            <Link to={`/documents/${lastDoc.id}`} className="resume">
              <span className="resume-label">Weiter mit</span>
              <span className="resume-title">{lastDoc.title || "Ohne Titel"}</span>
              <span className="resume-time">{relativeTime(lastDoc.updated_at!)}</span>
              <Icon name="chevronRight" />
            </Link>
          )}
        </div>
        {mayCreateDoc && (
          <div className="actions">
            {mayEdit && (
              <button onClick={() => setImporting({ file: null })}>
                <Icon name="arrowUp" />
                Importieren
              </button>
            )}
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
      <div className="home-grid">
        <DocumentTree
          docs={data?.documents as HomeDoc[] | undefined}
          workflows={(data?.workflows ?? []) as HomeWorkflow[]}
          empty={mayCreateDoc ? "Noch keine Dokumente. Lege oben das erste an." : "Noch keine Dokumente."}
          onImport={mayEdit ? () => setImporting({ file: null }) : undefined}
        />
      </div>
      {importing && <ImportDialog initialFile={importing.file} onClose={() => setImporting(null)} />}
    </div>
  );
}
