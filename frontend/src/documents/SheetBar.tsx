// Blatt-Leiste am unteren Rand der Dokument-Ansicht (Task 3.F5, B8) und „In Dokument einbetten …“ für
// Tabellen und Workflows, die direkt über ihre eigene Adresse geöffnet wurden.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { canEditStructure, useAuth } from "../api/client";
import { newId, useChannel } from "../sync/store";
import { Icon } from "../ui/icons";
import { toast } from "../ui/toasts";
import { type FlatBlock, type NewBlock, childrenOf, insertBlock } from "./blockOps";
import { EMBED_TYPES, type EmbedKind, buildTableViewProps, tableViewBlock, workflowBlock } from "./embedModel";
import type { Sheet } from "./workbookModel";

export type SheetLabel = { sheet: Sheet; label: string };

/** Blätter wie in Excel: Blatt 1 = Dokument, dann Tabellen und Workflows; „+“ bettet neue ein (nur mit Schreibrecht). */
export function SheetBar({ docLabel, sheets, active, onSelect, onEmbed }: {
  docLabel: string;
  sheets: SheetLabel[];
  active: Sheet | null;
  onSelect: (s: Sheet | null) => void;
  onEmbed?: (kind: EmbedKind) => void;
}) {
  const [menu, setMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setMenu(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [menu]);

  return (
    <nav className="sheet-bar" aria-label="Blätter">
      <div className="sheet-tabs">
        <button className={`sheet-tab ${active ? "" : "active"}`} aria-current={active ? undefined : "page"} onClick={() => onSelect(null)}>
          <Icon name="file" size={14} /><span>{docLabel}</span>
        </button>
        {sheets.map(({ sheet, label }) => (
          <button
            key={sheet.id}
            className={`sheet-tab ${active?.id === sheet.id ? "active" : ""}`}
            aria-current={active?.id === sheet.id ? "page" : undefined}
            onClick={() => onSelect(sheet)}
          >
            <Icon name={sheet.kind === "table" ? "table" : "flow"} size={14} /><span>{label}</span>
          </button>
        ))}
      </div>
      {onEmbed && (
        <div className="sheet-add" ref={ref}>
          <button className="ghost" aria-label="Blatt hinzufügen" title="Tabelle oder Workflow hinzufügen" aria-expanded={menu} onClick={() => setMenu(!menu)}>
            <Icon name="plus" size={14} />
          </button>
          {menu && (
            <div className="insert-menu sheet-menu" role="menu">
              {EMBED_TYPES.map((t) => (
                <button key={t.kind} role="menuitem" onClick={() => { setMenu(false); onEmbed(t.kind); }}>
                  <Icon name={t.icon} size={14} />{t.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </nav>
  );
}

/** Block ohne weitere Einstellungen für „In Dokument einbetten“: alle Spalten, kein Filter, nur lesen. */
export function plainEmbedBlock(kind: Sheet["kind"], id: string): NewBlock {
  return kind === "table"
    ? tableViewBlock(newId("blk"), buildTableViewProps({
        table: id, allColumns: [], selected: [], filterRows: [], sort: [], editable: false, allowAdd: false, allowDelete: false,
      }))
    : workflowBlock(newId("blk"), id);
}

/** Wartet, bis das Dokument geladen ist, hängt den Block am Ende an und öffnet das neue Blatt. */
function AppendToDocument({ docId, sheet, onFailed }: { docId: string; sheet: Sheet; onFailed: () => void }) {
  const navigate = useNavigate();
  const ch = useChannel(`doc:${docId}`);
  const done = useRef(false);
  const doc = ch?.view?.documents?.[0];
  useEffect(() => {
    if (done.current || !doc) return;
    done.current = true;
    const blocks = (doc.blocks ?? []) as FlatBlock[];
    const top = childrenOf(blocks, null);
    insertBlock(docId, null, top[top.length - 1]?.id, plainEmbedBlock(sheet.kind, sheet.id))
      .then(() => {
        toast(`In „${doc.title || "Ohne Titel"}“ eingebettet`);
        navigate(`/documents/${docId}?sheet=${encodeURIComponent(sheet.id)}`);
      })
      .catch((e: Error) => {
        toast(`Nicht eingebettet: ${e.message}`, "error");
        onFailed();
      });
  }, [doc]); // eslint-disable-line react-hooks/exhaustive-deps
  return <p className="muted" role="status">Wird eingebettet …</p>;
}

/** Aktion „In Dokument einbetten …“ mit Dokumentauswahl (für `/tables/:id` und `/workflows/:id`). */
export function EmbedInDocumentButton({ sheet }: { sheet: Sheet }) {
  const me = useAuth((s) => s.user);
  const ws = useChannel("workspace");
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<string | null>(null);
  const docs = ((ws?.view?.documents ?? []) as { id: string; title?: string }[]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && !target && setOpen(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open, target]);
  if (!canEditStructure(me)) return null;
  const close = () => { setOpen(false); setTarget(null); };
  return (
    <>
      <button onClick={() => setOpen(true)}><Icon name="file" size={14} />In Dokument einbetten …</button>
      {open && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !target && close()}>
          <div className="modal embed-dialog" role="dialog" aria-modal="true" aria-labelledby="embed-doc-title">
            <div className="modal-head">
              <h2 id="embed-doc-title">In Dokument einbetten</h2>
              <button className="ghost" onClick={close} aria-label="Schließen"><Icon name="close" size={16} /></button>
            </div>
            {target ? (
              <AppendToDocument docId={target} sheet={sheet} onFailed={close} />
            ) : docs.length === 0 ? (
              <p className="muted">Es gibt noch keine Dokumente.</p>
            ) : (
              <ul className="embed-list">
                {docs.map((d) => (
                  <li key={d.id}>
                    <button className="ghost" onClick={() => setTarget(d.id)}><Icon name="file" size={14} />{d.title || "Ohne Titel"}</button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </>
  );
}

