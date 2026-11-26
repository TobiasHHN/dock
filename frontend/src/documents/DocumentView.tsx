// Dokument-Ansicht (Task 2.4, L 3): Blockbaum aus dem Kanal `doc:<id>`, Blöcke einfügen/verschieben/löschen,
// Kennzeichnung des Autors (Mensch, Agent „im Auftrag von“, Workflow), Präsenz-Avatare (2.5).
// `DocumentView` ist eigenständig nutzbar (z. B. als Schritt-Dokument in der Run-Ansicht, Task 4.6).
import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { Actor } from "../api";
import { canEditDocument, useAuth, workflowApi } from "../api/client";
import { useChannelInvalidate } from "../inbox/inboxModel";
import { submit, sync, useChannel, useSync } from "../sync/store";
import { Avatar, actorLabel, useUsers } from "../ui/actors";
import { confirmDialog } from "../ui/confirm";
import { Icon } from "../ui/icons";
import { toast } from "../ui/toasts";
import {
  type FlatBlock, type NewBlock, childrenOf, deleteBlock, firstTextId, insertBlock, moveBlock, moveByDrop, renameDocument,
  templatesFor, updateBlock,
} from "./blockOps";
import "./blocks"; // trägt die Blocktypen aus P3/P4 in BLOCK_COMPONENTS ein
import { BLOCK_COMPONENTS } from "./blocks/registry";
import { DocContext, type DocContextValue, requestFocus, useDoc } from "./docContext";
import { EmbedDialog } from "./EmbedDialog";
import { EMBED_TYPES, type EmbedKind } from "./embedModel";
import { actorColor, scrollCorrection } from "./presenceModel";
import { SheetBar, type SheetLabel } from "./SheetBar";
import { WorkflowDetail } from "../workflows/WorkflowPage";
import { deleteWorkflow } from "../workflows/deleteWorkflow";
import { TableEditor } from "../tables/TableEditor";
import { type Sheet, activeSheet, collectSheets, sheetOfBlock, sheetParam } from "./workbookModel";
import { TextBlock } from "./TextBlock";

/** Erster (weitgehend) sichtbarer Block der obersten Ebene samt Abstand zum Fensterrand. */
function pickAnchor(): { id: string; top: number } | null {
  const topbar = 72;
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(".doc-body > .block"))) {
    const r = el.getBoundingClientRect();
    if (r.bottom > topbar) return { id: el.id, top: r.top };
  }
  return null;
}

type SheetRef = { id: string; key?: string; name?: string };
const fail = (what: string) => (e: Error) => toast(`${what}: ${e.message}`, "error");

export function DocumentPage() {
  const { id } = useParams();
  return <DocumentView docId={id!} />;
}

export function DocumentView({
  docId, readOnly = false, run, stepKey,
}: {
  docId: string; readOnly?: boolean; run?: string; stepKey?: string;
}) {
  if (run) return <RunDocumentView docId={docId} run={run} readOnly={readOnly} stepKey={stepKey} />;
  return <LiveDocumentView docId={docId} readOnly={readOnly} />;
}

function RunDocumentView({
  docId, run, readOnly, stepKey,
}: {
  docId: string; run: string; readOnly: boolean; stepKey?: string;
}) {
  const me = useAuth((s) => s.user);
  const users = useUsers();
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["run-doc", run, docId],
    queryFn: () => workflowApi.documentInRun(docId, run),
  });
  useChannelInvalidate(`run:${run}`, [["run-doc", run, docId]]);

  const blocks = useMemo(() => (data?.blocks ?? []) as FlatBlock[], [data?.blocks]);
  const owner = data?.document.owner ?? null;
  const ctx: DocContextValue = useMemo(
    () => ({
      docId,
      channel: "",
      blocks,
      editable: false,
      readOnly,
      me,
      users,
      authors: {},
      run,
      owner,
      stepKey: stepKey ?? owner?.step ?? null,
      lockedBy: () => null,
      setEditing: () => undefined,
    }),
    [docId, blocks, readOnly, me, users, run, owner, stepKey],
  );

  if (isLoading) return <DocSkeleton />;
  if (isError || !data) {
    return (
      <p className="alert" role="alert">
        <Icon name="alert" />
        Schritt-Dokument konnte nicht geladen werden: {(error as Error | undefined)?.message ?? "Unbekannter Fehler"}
      </p>
    );
  }

  return (
    <DocContext.Provider value={ctx}>
      <div className="doc-embedded">
        <div className={`doc-body doc-embedded-body ${ctx.editable ? "" : "doc-static"}`}>
          <BlockChildren parent={null} />
        </div>
      </div>
    </DocContext.Provider>
  );
}

function LiveDocumentView({ docId, readOnly = false }: { docId: string; readOnly?: boolean }) {
  const channel = `doc:${docId}`;
  const ch = useChannel(channel);
  const me = useAuth((s) => s.user);
  const navigate = useNavigate();
  const users = useUsers();
  const doc = ch?.view?.documents?.[0];
  const blocks: FlatBlock[] = useMemo(() => doc?.blocks ?? [], [doc?.blocks]);
  const mayEdit = canEditDocument(me, doc?.owner) && !readOnly;
  const isMe = (a: Actor) => a.type === "user" && a.id === me?.id;
  const presence = useMemo(() => ch?.presence ?? [], [ch?.presence]);
  const others = presence.filter((p) => !isMe(p.actor));

  // Arbeitsmappe (B8): Blatt 1 = Dokument, dann eingebettete Tabellen und Workflows; aktives Blatt steht in `?sheet=`
  const [params, setParams] = useSearchParams();
  const wsView = useChannel("workspace")?.view as { tables?: SheetRef[]; workflows?: SheetRef[] } | undefined;
  const sheets = useMemo(
    () => collectSheets(blocks, wsView ? { tables: wsView.tables, workflows: wsView.workflows } : undefined),
    [blocks, wsView],
  );
  const sheetLabels: SheetLabel[] = sheets.map((sheet) => {
    const ref = (sheet.kind === "table" ? wsView?.tables : wsView?.workflows)?.find((x) => x.id === sheet.id);
    return { sheet, label: ref?.name ?? ref?.key ?? (sheet.kind === "table" ? "Tabelle" : "Workflow") };
  });
  const active = activeSheet(params.get("sheet"), sheets);
  const selectSheet = (s: Sheet | null) => {
    const next = new URLSearchParams(params);
    const v = sheetParam(s);
    if (v) next.set("sheet", v);
    else next.delete("sheet");
    setParams(next);
    window.scrollTo({ top: 0 });
  };
  const [embed, setEmbed] = useState<EmbedKind | null>(null);

  const ctx: DocContextValue = useMemo(
    () => ({
      docId,
      channel,
      blocks,
      editable: mayEdit,
      readOnly,
      me,
      users,
      authors: ch?.authors ?? {},
      lockedBy: (blockId) => {
        const entry = presence.find((p) => p.state?.editing === blockId && !(p.actor.type === "user" && p.actor.id === me?.id));
        return entry ? actorLabel(entry.actor, users) : null;
      },
      editorOf: (blockId) =>
        presence.find((p) => p.state?.editing === blockId && !(p.actor.type === "user" && p.actor.id === me?.id))?.actor ?? null,
      isSettled: () => settled.current,
      setEditing: (blockId) => sync.sendPresence(channel, { editing: blockId }),
    }),
    [docId, channel, blocks, mayEdit, readOnly, me, users, ch?.authors, presence],
  );

  // Erstes Laden abgeschlossen: danach neu erscheinende Blöcke blenden sanft ein
  const settled = useRef(false);
  useEffect(() => {
    if (!doc) return;
    const t = setTimeout(() => (settled.current = true), 300);
    return () => clearTimeout(t);
  }, [!!doc]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keine Sprünge: Ändert sich der Blockbaum über dem sichtbaren Bereich (z. B. fügt jemand anderes oben etwas ein),
  // bleibt der erste sichtbare Block an derselben Bildschirmposition.
  const anchor = useRef<{ id: string; top: number } | null>(null);
  useEffect(() => {
    let raf = 0;
    const record = () => {
      raf = 0;
      anchor.current = pickAnchor();
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(record);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    record();
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);
  useLayoutEffect(() => {
    const a = anchor.current;
    const el = a ? document.getElementById(a.id) : null;
    if (a && el) {
      const by = scrollCorrection(a.top, el.getBoundingClientRect().top, window.scrollY);
      if (by) window.scrollBy(0, by);
    }
    anchor.current = pickAnchor();
  }, [blocks]);

  // Sprungmarke #blk_… (z. B. aus der Suche)
  useEffect(() => {
    if (!blocks.length || !location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [blocks.length]);

  if (!ch || ch.status === "loading") return <DocSkeleton />;
  if (ch.status === "error")
    return <p className="alert" role="alert"><Icon name="alert" />Dokument nicht verfügbar: {ch.error?.message}. <Link to="/">Zur Übersicht</Link></p>;
  if (!doc)
    return (
      <div className="empty-state">
        <span className="empty-state-icon"><Icon name="file" size={22} /></span>
        <h1>Dokument gelöscht</h1>
        <p className="muted">Dieses Dokument gibt es nicht mehr.</p>
        <Link to="/">Zur Übersicht</Link>
      </div>
    );

  // Übersichtsdokument eines Workflows (owner.step null): Löschen heißt den ganzen Workflow löschen (B28)
  const overviewOf = doc.owner && !doc.owner.step ? (doc.owner.workflow as string) : null;
  const deleteDocument = async () => {
    if (overviewOf) {
      const workflows = (sync.store.getState().channels.workspace?.view?.workflows ?? []) as { id: string; key?: string; name?: string }[];
      const wf = workflows.find((w) => w.id === overviewOf || w.key === overviewOf) ?? { id: overviewOf, name: doc.title };
      if (await deleteWorkflow(wf)) navigate("/");
      return;
    }
    const ok = await confirmDialog({
      title: `Dokument „${doc.title || "Ohne Titel"}“ löschen?`,
      message: "Das Dokument mit allen Blöcken wird entfernt. Wird es noch verwendet, ist das Löschen nicht möglich.",
      confirmLabel: "Dokument löschen", danger: true,
    });
    if (!ok) return;
    try {
      await submit([{ op: "doc.delete", doc: docId } as never]);
      toast("Dokument gelöscht");
      navigate("/");
    } catch (err) {
      // z. B. IN_USE: Die Meldung nennt, wo das Dokument noch verwendet wird
      const msg = (err as { error?: { message: string } })?.error?.message ?? (err as Error).message;
      toast(`Löschen nicht möglich: ${msg}`, "error");
    }
  };

  return (
    <DocContext.Provider value={ctx}>
      <div className="doc-toolbar">
        <nav className="breadcrumb" aria-label="Brotkrumen">
          <Link to="/">Dokumente</Link>
          <Icon name="chevronRight" size={14} />
          <span aria-current="page">{doc.title || "Ohne Titel"}</span>
        </nav>
        <span className="spacer" />
        {mayEdit && <SaveState />}
        {mayEdit && (
          <button className="ghost quiet-danger" onClick={deleteDocument}>
            <Icon name="trash" size={14} />{overviewOf ? "Workflow löschen" : "Dokument löschen"}
          </button>
        )}
        {others.length > 0 && (
          <div className="presence" aria-label={`${others.length} weitere im Dokument`}>
            {others.map((p, i) => (
              <Avatar key={`${p.actor.type}:${p.actor.id}:${i}`} actor={p.actor} users={users} />
            ))}
          </div>
        )}
      </div>
      {active ? (
        <div className="sheet-pane" key={active.id}>
          {active.kind === "table" ? <TableEditor tableId={active.id} embedded /> : <WorkflowDetail workflowId={active.id} embedded />}
        </div>
      ) : (
        <>
          <div className="doc-head">
            {doc.owner?.step && <span className="pill pill-success">Schritt „{doc.owner.step}“ eines Workflows</span>}
            <DocTitle docId={docId} title={doc.title} editable={mayEdit} />
          </div>
          {!mayEdit && !readOnly && (
            <div className="readonly-hint"><Icon name="info" />Nur lesen: Schritt-Dokumente eines Workflows ändert in der Demo die Rolle Einkauf.</div>
          )}
          <div className={`doc-body ${mayEdit ? "" : "doc-static"}`}>
            <BlockChildren parent={null} />
            {mayEdit && <AddBlockButton />}
          </div>
        </>
      )}
      <SheetBar
        docLabel={doc.title || "Dokument"}
        sheets={sheetLabels}
        active={active}
        onSelect={selectSheet}
        onEmbed={mayEdit ? setEmbed : undefined}
      />
      {embed && (
        <EmbedDialog
          kind={embed}
          onClose={() => setEmbed(null)}
          onInsert={(nb) => {
            setEmbed(null);
            const top = childrenOf(blocks, null);
            insertBlock(docId, null, top[top.length - 1]?.id, nb).catch(fail("Block nicht eingefügt"));
            const target = sheetOfBlock(nb);
            if (target) selectSheet(target);
          }}
        />
      )}
    </DocContext.Provider>
  );
}

/** „Speichert …“, solange eigene Änderungen noch nicht vom Server bestätigt sind (ausstehende Batches im Sync-Store). */
function SaveState() {
  const pending = useSync((s) => s.pending.some((p) => !p.acked));
  const status = useSync((s) => s.status);
  const offline = status !== "open";
  return (
    <span className={`save-state ${pending ? "saving" : ""} ${offline ? "offline" : ""}`} role="status">
      {offline ? (
        <>Offline, Änderungen werden nachgereicht</>
      ) : pending ? (
        <>Speichert …</>
      ) : (
        <><Icon name="check" size={14} strokeWidth={2.4} />Gespeichert</>
      )}
    </span>
  );
}

function DocSkeleton() {
  return (
    <div className="doc-skeleton" aria-label="Dokument wird geladen …" role="status">
      <span className="sk sk-title" />
      <div className="doc-body">
        <span className="sk" /><span className="sk" /><span className="sk sk-short" />
      </div>
    </div>
  );
}

function DocTitle({ docId, title, editable }: { docId: string; title: string; editable: boolean }) {
  const [value, setValue] = useState(title);
  const editing = useRef(false);
  useEffect(() => {
    if (!editing.current) setValue(title);
  }, [title]);
  const commit = () => {
    editing.current = false;
    const t = value.trim();
    if (t && t !== title) renameDocument(docId, t).catch(fail("Titel nicht gespeichert"));
    else setValue(title);
  };
  return (
    <input
      className="doc-title"
      aria-label="Dokumenttitel"
      autoComplete="off"
      value={value}
      readOnly={!editable}
      onFocus={() => (editing.current = true)}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

/** Rendert die Kinder eines Blocks (oder die oberste Ebene) in Reihenfolge. Auch für Block-Komponenten aus P3/P4. */
export function BlockChildren({ parent }: { parent: string | null }) {
  const { blocks } = useDoc();
  return (
    <>
      {childrenOf(blocks, parent).map((b) => (
        <BlockFrame key={b.id} block={b}>
          <BlockContent block={b} />
        </BlockFrame>
      ))}
    </>
  );
}

function pickAndInsert(docId: string, parent: string | null, after: string | undefined, nb: NewBlock) {
  const focus = firstTextId(nb);
  if (focus) requestFocus(focus);
  insertBlock(docId, parent, after, nb).catch(fail("Block nicht eingefügt"));
}

function AddBlockButton() {
  const { docId, blocks } = useDoc();
  const [open, setOpen] = useState(false);
  const [embed, setEmbed] = useState<EmbedKind | null>(null);
  const top = childrenOf(blocks, null);
  const after = top[top.length - 1]?.id;
  return (
    <div className="add-block" style={{ position: "relative" }}>
      {embed && (
        <EmbedDialog
          kind={embed}
          onClose={() => setEmbed(null)}
          onInsert={(nb) => {
            setEmbed(null);
            pickAndInsert(docId, null, after, nb);
          }}
        />
      )}
      <button className="ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name="plus" size={14} />Block hinzufügen
      </button>
      {open && (
        <InsertMenu
          parentType={null}
          style={{ left: 0 }}
          onClose={() => setOpen(false)}
          onEmbed={(k) => {
            setOpen(false);
            setEmbed(k);
          }}
          onPick={(nb) => {
            setOpen(false);
            pickAndInsert(docId, null, after, nb);
          }}
        />
      )}
    </div>
  );
}

/** Einfüge-Menü: Abschnitt „Text“ (Vorlagen aus blockOps) und, auf oberster Ebene, „Einbetten“ (EMBED_TYPES). */
function InsertMenu({ parentType, onPick, onEmbed, onClose, style }: {
  parentType: string | null; onPick: (b: NewBlock) => void; onEmbed?: (k: EmbedKind) => void; onClose: () => void; style?: React.CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [onClose]);
  return (
    <div className="insert-menu" ref={ref} style={style}>
      <div className="insert-section">Text</div>
      {templatesFor(parentType).map((t) => (
        <button key={t.key} onClick={() => onPick(t.make())}>{t.label}</button>
      ))}
      {parentType === null && onEmbed && (
        <>
          <div className="insert-section">Einbetten</div>
          {EMBED_TYPES.map((t) => (
            <button key={t.kind} onClick={() => onEmbed(t.kind)}><Icon name={t.icon} size={14} />{t.label}</button>
          ))}
        </>
      )}
    </div>
  );
}

/** Blinkt kurz, wenn jemand anderes (Person, Agent, Workflow) den Block live geändert oder eingefügt hat. */
function useFlashOnForeignChange(block: FlatBlock): boolean {
  const { authors, me } = useDoc();
  const author = authors[block.id];
  const [flash, setFlash] = useState(false);
  const first = useRef(true);
  useEffect(() => {
    const foreign = !!author && !(author.type === "user" && author.id === me?.id);
    const initial = first.current;
    first.current = false;
    // Autoren kennt der Client nur aus Live-Ops; beim ersten Rendern blinken also nur gerade eingefügte Blöcke.
    if (!foreign || (initial && !author)) return;
    setFlash(true);
    const t = setTimeout(() => setFlash(false), 2000);
    return () => clearTimeout(t);
  }, [block.version, author, me?.id]);
  return flash;
}

/** Gerade gezogener Block (Drag & Drop, B6). Verschieben geht nur unter demselben Elternblock. */
let blockDrag: { id: string; parent: string | null } | null = null;

/** Kleines Menü am Griff: Aktionen für den Block. Schließt bei Klick daneben oder Esc. */
function BlockMenu({ items, onClose }: {
  items: { label: string; icon: "arrowUp" | "arrowDown" | "trash"; run: () => void; danger?: boolean; disabled?: boolean }[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node) && !(e.target as Element).closest(".grip")) onClose();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", key);
    };
  }, [onClose]);
  return (
    <div className="insert-menu block-menu" role="menu" ref={ref}>
      {items.map((it) => (
        <button
          key={it.label} role="menuitem" disabled={it.disabled} className={it.danger ? "quiet-danger-item" : ""}
          onClick={() => {
            onClose();
            it.run();
          }}
        ><Icon name={it.icon} size={14} />{it.label}</button>
      ))}
    </div>
  );
}

/** Rahmen eines Blocks: Gutter (einfügen, verschieben, löschen), Sperre durch Präsenz, Autor, Hervorhebung. */
function BlockFrame({ block, children }: { block: FlatBlock; children: ReactNode }) {
  const ctx = useDoc();
  const [menu, setMenu] = useState(false);
  const [embed, setEmbed] = useState<EmbedKind | null>(null);
  const flash = useFlashOnForeignChange(block);
  const locked = ctx.lockedBy(block.id);
  const editor = ctx.editorOf?.(block.id) ?? null;
  const enter = useRef(ctx.isSettled?.() ?? false).current; // live eingefügt: sanft einblenden
  const author = ctx.authors[block.id];
  const parentType = ctx.blocks.find((b) => b.id === block.parent_id)?.type ?? null;
  const parent = block.parent_id ?? null;
  const [grip, setGrip] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [dropSide, setDropSide] = useState<"before" | "after" | null>(null);
  const frame = useRef<HTMLDivElement>(null);

  // Abgebrochenes Ziehen (Esc, außerhalb losgelassen): Einfügemarke wieder ausblenden
  useEffect(() => {
    if (!dropSide) return;
    const reset = () => setDropSide(null);
    window.addEventListener("block-drag-end", reset);
    return () => window.removeEventListener("block-drag-end", reset);
  }, [dropSide]);

  const canDropHere = () => !!ctx.editable && !!blockDrag && blockDrag.parent === parent && blockDrag.id !== block.id;
  const onDragOver = (e: React.DragEvent) => {
    if (!canDropHere()) return;
    e.preventDefault();
    e.stopPropagation();
    const r = e.currentTarget.getBoundingClientRect();
    const side = e.clientY < r.top + r.height / 2 ? "before" : "after";
    if (side !== dropSide) setDropSide(side);
  };
  const onDrop = (e: React.DragEvent) => {
    if (!canDropHere()) return;
    e.preventDefault();
    e.stopPropagation();
    const dragged = ctx.blocks.find((b) => b.id === blockDrag!.id);
    const side = dropSide ?? "after";
    setDropSide(null);
    if (dragged) moveByDrop(ctx.blocks, dragged, block, side)?.catch(fail("Nicht verschoben"));
  };

  return (
    <div
      id={block.id}
      ref={frame}
      className={`block ${locked ? "shared" : ""} ${flash ? "flash" : ""} ${dragging ? "dragging" : ""} ${dropSide ? `drop-${dropSide}` : ""} ${enter ? "enter" : ""}`}
      style={editor ? ({ "--presence": actorColor(`${editor.type}:${editor.id}`) } as React.CSSProperties) : undefined}
      onDragOver={onDragOver}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropSide(null);
      }}
      onDrop={onDrop}
    >
      <div className={`gutter ${menu || grip ? "open" : ""}`}>
        {ctx.editable && (
          <>
            <button className="ghost" title="Block darunter einfügen" aria-label="Block darunter einfügen" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name="plus" size={14} /></button>
            <button
              className="ghost grip"
              title="Ziehen zum Verschieben, Klicken für Menü"
              aria-label="Block verschieben oder löschen"
              aria-haspopup="menu"
              aria-expanded={grip}
              draggable
              onClick={() => setGrip(!grip)}
              onDragStart={(e) => {
                blockDrag = { id: block.id, parent };
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", block.id);
                if (frame.current) e.dataTransfer.setDragImage(frame.current, 0, 0);
                setGrip(false);
                setDragging(true);
              }}
              onDragEnd={() => {
                blockDrag = null;
                setDragging(false);
                window.dispatchEvent(new Event("block-drag-end"));
              }}
            ><Icon name="grip" size={14} /></button>
          </>
        )}
      </div>
      {grip && (
        <BlockMenu
          onClose={() => setGrip(false)}
          items={[
            { label: "Nach oben", icon: "arrowUp", run: () => moveBlock(ctx.blocks, block, -1)?.catch(fail("Nicht verschoben")) },
            { label: "Nach unten", icon: "arrowDown", run: () => moveBlock(ctx.blocks, block, 1)?.catch(fail("Nicht verschoben")) },
            { label: "Löschen", icon: "trash", danger: true, disabled: !!locked, run: () => deleteBlock(block.id).catch(fail("Nicht gelöscht")) },
          ]}
        />
      )}
      <div className="content">{children}</div>
      {locked ? (
        <span className="lock-badge" role="status">
          {editor && <Avatar actor={editor} users={ctx.users} />}
          {locked} bearbeitet
        </span>
      ) : (
        author && <span className={`author-badge ${author.type}`}>{actorLabel(author, ctx.users)}</span>
      )}
      {menu && (
        <InsertMenu
          parentType={parentType}
          onClose={() => setMenu(false)}
          onEmbed={(k) => {
            setMenu(false);
            setEmbed(k);
          }}
          onPick={(nb) => {
            setMenu(false);
            pickAndInsert(ctx.docId, block.parent_id ?? null, block.id, nb);
          }}
        />
      )}
      {embed && (
        <EmbedDialog
          kind={embed}
          onClose={() => setEmbed(null)}
          onInsert={(nb) => {
            setEmbed(null);
            pickAndInsert(ctx.docId, block.parent_id ?? null, block.id, nb);
          }}
        />
      )}
    </div>
  );
}

function BlockContent({ block }: { block: FlatBlock }) {
  const Custom = BLOCK_COMPONENTS[block.type];
  if (Custom) return <Custom block={block} />;
  switch (block.type) {
    case "heading":
    case "paragraph":
      return <TextBlock block={block} />;
    case "list":
      return <ListBlock block={block} />;
    case "list_item":
      return <ListItemBlock block={block} index={0} ordered={false} />;
    case "quote":
      return (
        <blockquote className="quote-block">
          <BlockChildren parent={block.id} />
        </blockquote>
      );
    case "code":
      return <CodeBlock block={block} />;
    case "divider":
      return <hr className="divider-block" />;
    default:
      return <PlaceholderBlock block={block} />;
  }
}

function ListBlock({ block }: { block: FlatBlock }) {
  const { blocks } = useDoc();
  return (
    <div className="list-block">
      {childrenOf(blocks, block.id).map((item, i) => (
        <BlockFrame key={item.id} block={item}>
          <ListItemBlock block={item} index={i} ordered={!!block.props.ordered} />
        </BlockFrame>
      ))}
    </div>
  );
}

function ListItemBlock({ block, index, ordered }: { block: FlatBlock; index: number; ordered: boolean }) {
  const { blocks, editable } = useDoc();
  const checked = block.props.checked;
  const nested = childrenOf(blocks, block.id);
  return (
    <div>
      <div className="list-item">
        <span className="marker">
          {checked === true || checked === false ? (
            <input
              type="checkbox"
              aria-label="Erledigt"
              checked={checked}
              disabled={!editable}
              onChange={(e) => updateBlock(block.id, { checked: e.target.checked }).catch(fail("Nicht gespeichert"))}
            />
          ) : ordered ? `${index + 1}.` : "•"}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <TextBlock block={block} />
        </div>
      </div>
      {nested.length > 0 && (
        <div className="nested">
          {nested.map((n) => (
            <ListBlock key={n.id} block={n} />
          ))}
        </div>
      )}
    </div>
  );
}

function CodeBlock({ block }: { block: FlatBlock }) {
  const { editable, lockedBy, setEditing } = useDoc();
  const [text, setText] = useState<string>(block.props.text ?? "");
  const focused = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!focused.current) setText(block.props.text ?? "");
  }, [block.props.text]);
  const save = (value: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (value !== block.props.text) updateBlock(block.id, { text: value }).catch(fail("Code nicht gespeichert"));
  };
  return (
    <textarea
      className="code-block"
      value={text}
      readOnly={!editable || !!lockedBy(block.id)}
      spellCheck={false}
      rows={Math.max(2, text.split("\n").length)}
      onFocus={() => {
        focused.current = true;
        setEditing(block.id);
      }}
      onBlur={() => {
        focused.current = false;
        save(text);
        setEditing(null);
      }}
      onChange={(e) => {
        const v = e.target.value;
        setText(v);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => save(v), 500);
      }}
    />
  );
}

const PLACEHOLDER_LABEL: Record<string, string> = {
  table_view: "Tabellenansicht",
  form: "Formular",
  field: "Feld",
  line_items: "Zeilenliste",
  workflow: "Workflow",
  image: "Bild",
};

/** Platzhalter für Blocktypen anderer Tasks (3.1, 3.4, 4.6), bis sie sich in BLOCK_COMPONENTS eintragen. */
function PlaceholderBlock({ block }: { block: FlatBlock }) {
  const { blocks } = useDoc();
  const p = block.props;
  const detail = p.label ?? p.table ?? p.workflow ?? p.alt ?? "";
  const hasChildren = blocks.some((b) => b.parent_id === block.id);
  return (
    <div className="placeholder-block">
      <b>{PLACEHOLDER_LABEL[block.type] ?? block.type}</b>
      {detail && <span> · {String(detail)}</span>}
      {block.type === "field" && p.required && <span> *</span>}
      {hasChildren && (
        <div className="children">
          <BlockChildren parent={block.id} />
        </div>
      )}
    </div>
  );
}
