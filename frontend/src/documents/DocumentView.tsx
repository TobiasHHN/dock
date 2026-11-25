// Dokument-Ansicht (Task 2.4, L 3): Blockbaum aus dem Kanal `doc:<id>`, Blöcke einfügen/verschieben/löschen,
// Kennzeichnung des Autors (Mensch, Agent „im Auftrag von“, Workflow), Präsenz-Avatare (2.5).
// `DocumentView` ist eigenständig nutzbar (z. B. als Schritt-Dokument in der Run-Ansicht, Task 4.6).
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { Actor } from "../api";
import { canEditStructure, useAuth } from "../api/client";
import { sync, useChannel } from "../sync/store";
import { Avatar, actorLabel, useUsers } from "../ui/actors";
import { toast } from "../ui/toasts";
import {
  type FlatBlock, type NewBlock, childrenOf, deleteBlock, firstTextId, insertBlock, moveBlock, renameDocument,
  templatesFor, updateBlock,
} from "./blockOps";
import { BLOCK_COMPONENTS } from "./blocks/registry";
import { DocContext, type DocContextValue, requestFocus, useDoc } from "./docContext";
import { TextBlock } from "./TextBlock";

const fail = (what: string) => (e: Error) => toast(`${what}: ${e.message}`, "error");

export function DocumentPage() {
  const { id } = useParams();
  return <DocumentView docId={id!} />;
}

export function DocumentView({ docId, readOnly = false, run }: { docId: string; readOnly?: boolean; run?: string }) {
  const channel = `doc:${docId}`;
  const ch = useChannel(channel);
  const me = useAuth((s) => s.user);
  const users = useUsers();
  const doc = ch?.view?.documents?.[0];
  const blocks: FlatBlock[] = useMemo(() => doc?.blocks ?? [], [doc?.blocks]);
  const mayEdit = canEditStructure(me) && !readOnly;
  const isMe = (a: Actor) => a.type === "user" && a.id === me?.id;
  const presence = useMemo(() => ch?.presence ?? [], [ch?.presence]);
  const others = presence.filter((p) => !isMe(p.actor));

  const ctx: DocContextValue = useMemo(
    () => ({
      docId,
      channel,
      blocks,
      editable: mayEdit,
      me,
      users,
      authors: ch?.authors ?? {},
      run,
      lockedBy: (blockId) => {
        const entry = presence.find((p) => p.state?.editing === blockId && !(p.actor.type === "user" && p.actor.id === me?.id));
        return entry ? actorLabel(entry.actor, users) : null;
      },
      setEditing: (blockId) => sync.sendPresence(channel, { editing: blockId }),
    }),
    [docId, channel, blocks, mayEdit, me, users, ch?.authors, presence, run],
  );

  // Sprungmarke #blk_… (z. B. aus der Suche)
  useEffect(() => {
    if (!blocks.length || !location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [blocks.length]);

  if (!ch || ch.status === "loading") return <p className="muted">Dokument wird geladen …</p>;
  if (ch.status === "error") return <p className="error-text">Dokument nicht verfügbar: {ch.error?.message}</p>;
  if (!doc) return <p className="muted">Dieses Dokument wurde gelöscht. <Link to="/">Zur Übersicht</Link></p>;

  return (
    <DocContext.Provider value={ctx}>
      <div className="doc-head">
        <DocTitle docId={docId} title={doc.title} editable={mayEdit} />
        <div className="presence">
          {others.map((p, i) => (
            <Avatar key={`${p.actor.type}:${p.actor.id}:${i}`} actor={p.actor} users={users} />
          ))}
        </div>
      </div>
      {doc.owner && <p className="small muted">Schritt „{doc.owner.step}“ eines Workflows</p>}
      {!mayEdit && !readOnly && <div className="readonly-hint">Nur lesen: Dokumente ändern darf in der Demo die Rolle Einkauf.</div>}
      <div className="doc-body">
        <BlockChildren parent={null} />
        {mayEdit && <AddBlockButton />}
      </div>
    </DocContext.Provider>
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
  const top = childrenOf(blocks, null);
  return (
    <div className="add-block" style={{ position: "relative" }}>
      <button className="ghost muted" onClick={() => setOpen(!open)}>+ Block hinzufügen</button>
      {open && (
        <InsertMenu
          parentType={null}
          style={{ left: 0 }}
          onClose={() => setOpen(false)}
          onPick={(nb) => {
            setOpen(false);
            pickAndInsert(docId, null, top[top.length - 1]?.id, nb);
          }}
        />
      )}
    </div>
  );
}

function InsertMenu({ parentType, onPick, onClose, style }: {
  parentType: string | null; onPick: (b: NewBlock) => void; onClose: () => void; style?: React.CSSProperties;
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
      {templatesFor(parentType).map((t) => (
        <button key={t.key} onClick={() => onPick(t.make())}>{t.label}</button>
      ))}
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

/** Rahmen eines Blocks: Gutter (einfügen, verschieben, löschen), Sperre durch Präsenz, Autor, Hervorhebung. */
function BlockFrame({ block, children }: { block: FlatBlock; children: ReactNode }) {
  const ctx = useDoc();
  const [menu, setMenu] = useState(false);
  const flash = useFlashOnForeignChange(block);
  const locked = ctx.lockedBy(block.id);
  const author = ctx.authors[block.id];
  const parentType = ctx.blocks.find((b) => b.id === block.parent_id)?.type ?? null;

  return (
    <div id={block.id} className={`block ${locked ? "shared" : ""} ${flash ? "flash" : ""}`}>
      <div className="gutter">
        {ctx.editable && (
          <>
            <button className="ghost" title="Block darunter einfügen" onClick={() => setMenu(!menu)}>+</button>
            <button className="ghost" title="Nach oben" onClick={() => moveBlock(ctx.blocks, block, -1)?.catch(fail("Nicht verschoben"))}>↑</button>
            <button className="ghost" title="Nach unten" onClick={() => moveBlock(ctx.blocks, block, 1)?.catch(fail("Nicht verschoben"))}>↓</button>
            <button className="ghost danger" title="Löschen" disabled={!!locked} onClick={() => deleteBlock(block.id).catch(fail("Nicht gelöscht"))}>✕</button>
          </>
        )}
      </div>
      <div className="content">{children}</div>
      {locked ? (
        <span className="lock-badge">{locked} bearbeitet</span>
      ) : (
        author && <span className={`author-badge ${author.type}`}>{actorLabel(author, ctx.users)}</span>
      )}
      {menu && (
        <InsertMenu
          parentType={parentType}
          onClose={() => setMenu(false)}
          onPick={(nb) => {
            setMenu(false);
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
