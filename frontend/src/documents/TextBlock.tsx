// Bearbeitbarer Textblock (Task 2.5, F15; T 5.4): heading, paragraph, list_item als eigene TipTap-Instanz.
//
// - Mehrere Personen können gleichzeitig im selben Block tippen: Eingaben gehen entprellt als `text.edit`,
//   fremde Edits werden per OT eingespielt (TextSync, L 7.5, T 2.6). Undo betrifft nur eigene Eingaben.
// - Strg+B / Strg+I / Strg+E (Code) / Strg+Shift+S (durchgestrichen), Umschalt+Enter = Zeilenumbruch.
// - Enter teilt den Block (Rest geht in einen neuen Block), Backspace am Anfang hängt den Text an den vorigen
//   Textblock an.
// - Fokus meldet `presence { editing }` (alle 20 s erneuert, Server-TTL 30 s). Andere Personen sehen
//   „X bearbeitet“, dürfen aber mitschreiben; Agenten bekommen dort BLOCK_IN_USE (L 7.5).
import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useLayoutEffect, useRef } from "react";
import type { Op } from "../api";
import { TEXT_TYPES } from "../sync/apply";
import { newId, submit, sync } from "../sync/store";
import { type Unit, diffUnits, fromUnits } from "../sync/textOt";
import { type FlatBlock, childrenOf } from "./blockOps";
import { requestFocus, takeFocusRequest, useDoc } from "./docContext";
import { TextSync } from "./textSync";
import { TypewriterExtension, cancelTyping, typeIn } from "./typewriter";
import {
  appendUnits, applyUnitsEdit, editorUnits, inlineToDoc, posToUnit, setEditorUnits, textExtensions, unitToPos,
} from "./tiptap";

const PRESENCE_EVERY = 20_000;
/** Fremder Text ab dieser Länge wird weich eingeblendet; kürzere Edits (anderer Mensch tippt Zeichen für Zeichen) erscheinen sofort. */
const TYPE_MIN = 24;
/** Live eingefügte Blöcke, die schon getippt wurden (Neu-Rendern/Verschieben soll nicht erneut tippen). */
const typedBlocks = new Set<string>();

const PLACEHOLDER: Record<string, string> = {
  heading: "Überschrift",
  paragraph: "Text eingeben …",
  list_item: "Listenpunkt",
};

/** Offene Textblöcke, damit Backspace am Blockanfang den Text an den vorigen Block anhängen kann. */
const openBlocks = new Map<string, { append: (units: Unit[]) => number; focus: (at: number | "start" | "end") => void }>();

const syncDeps = {
  submit: (ops: Op[], opts: { batchId: string }) => sync.submit(ops, opts),
  confirmedBlock: (channel: string, id: string) => sync.confirmedBlock(channel, id),
  channelSeq: (channel: string) => sync.store.getState().channels[channel]?.seq ?? null,
  listen: sync.listen,
  newId,
};

export function TextBlock({ block }: { block: FlatBlock }) {
  const ctx = useDoc();
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx;
  const blockRef = useRef(block);
  blockRef.current = block;
  const liveForeign = useRef(
    !!ctx.isSettled?.() && !!ctx.authors[block.id] && !(ctx.authors[block.id].type === "user" && ctx.authors[block.id].id === ctx.me?.id),
  ).current;
  const textSync = useRef<TextSync | null>(null);
  const heartbeat = useRef<ReturnType<typeof setInterval> | null>(null);

  const editor = useEditor(
    {
      extensions: [...textExtensions(PLACEHOLDER[block.type] ?? ""), TypewriterExtension],
      content: inlineToDoc((ctx.channel ? sync.confirmedBlock(ctx.channel, block.id)?.props?.content : undefined) ?? block.props.content),
      editable: ctx.editable,
      shouldRerenderOnTransaction: false,
      editorProps: {
        attributes: { class: "text-block-editor", spellcheck: "true" },
        handleKeyDown: (_view, event) => {
          if (event.isComposing || !ctxRef.current.editable) return false;
          if (event.key === "Enter" && !event.shiftKey) {
            split();
            return true;
          }
          if (event.key === "Backspace") return mergeWithPrevious();
          return false;
        },
      },
      onUpdate: ({ transaction }) => {
        if (!transaction.getMeta("remote")) textSync.current?.changed();
      },
      onFocus: () => {
        ctxRef.current.setEditing(block.id);
        if (heartbeat.current) clearInterval(heartbeat.current);
        heartbeat.current = setInterval(() => ctxRef.current.setEditing(block.id), PRESENCE_EVERY);
      },
      onBlur: () => {
        textSync.current?.flush();
        if (heartbeat.current) clearInterval(heartbeat.current);
        heartbeat.current = null;
        ctxRef.current.setEditing(null);
      },
    },
    [block.id],
  );

  // Abgleich mit dem Server (nur wenn ein Live-Kanal aktiv ist; im Run-Dokument statisch/ausgewertet)
  useEffect(() => {
    if (!editor || !ctx.channel) return;
    const ts = new TextSync(block.id, ctx.channel, syncDeps);
    ts.attach({
      getUnits: () => editorUnits(editor),
      applyRemote: (edit, expected) => {
        const inserted = Array.from(edit.insert ?? "").length;
        applyUnitsEdit(editor, edit, expected.slice(edit.from, edit.from + inserted));
        if (JSON.stringify(fromUnits(editorUnits(editor))) !== JSON.stringify(fromUnits(expected))) setEditorUnits(editor, expected);
        else if (inserted >= TYPE_MIN && mayType()) typeIn(editor, block.id, edit.from, edit.from + inserted);
      },
      setUnits: (units) => {
        const cur = editorUnits(editor);
        const diff = diffUnits(cur, units);
        setEditorUnits(editor, units);
        const inserted = diff ? units.length - cur.length + (diff.to - diff.from) : 0;
        if (diff && inserted >= TYPE_MIN && mayType()) typeIn(editor, block.id, diff.from, diff.from + inserted);
      },
    });
    textSync.current = ts;
    openBlocks.set(block.id, {
      append: (units) => {
        const len = appendUnits(editor, units);
        ts.flush();
        return len;
      },
      focus: (at) => focusAt(at),
    });
    return () => {
      openBlocks.delete(block.id);
      ts.detach(!blockStillExists());
      textSync.current = null;
      if (heartbeat.current) clearInterval(heartbeat.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, block.id, ctx.channel]);

  // Fremd live eingefügter Block: Text weich einblenden
  useEffect(() => {
    if (!editor || !liveForeign || typedBlocks.has(block.id)) return;
    const len = editorUnits(editor).length;
    if (len > 0 && typeIn(editor, block.id, 0, len)) typedBlocks.add(block.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor]);

  useEffect(() => () => cancelTyping(block.id), [block.id]);

  useEffect(() => {
    if (!editor || ctx.channel) return;
    editor.commands.setContent(inlineToDoc(block.props.content), false);
  }, [editor, ctx.channel, block.props.content]);

  useEffect(() => {
    editor?.setEditable(ctx.editable);
  }, [editor, ctx.editable]);

  // Fokus nach Einfügen / Zusammenführen
  useLayoutEffect(() => {
    if (!editor) return;
    const at = takeFocusRequest(block.id);
    if (at !== null) focusAt(at);
  });

  /** Tippen nur, wenn der Nutzer nicht gerade selbst in diesem Block ist und das Dokument fertig geladen ist. */
  function mayType() {
    return !!editor && !editor.isFocused && !!ctxRef.current.isSettled?.();
  }

  function blockStillExists() {
    return !!sync.confirmedBlock(ctxRef.current.channel, block.id);
  }

  function focusAt(at: number | "start" | "end") {
    if (!editor) return;
    if (at === "start" || at === "end") editor.commands.focus(at);
    else editor.commands.focus(unitToPos(editor.state.doc, at));
  }

  function split() {
    if (!editor) return;
    if (!editor.state.selection.empty) editor.commands.deleteSelection();
    const { state } = editor;
    const caret = posToUnit(state.doc, state.selection.from);
    const units = editorUnits(editor);
    const tail = units.slice(caret);
    if (tail.length) {
      editor.view.dispatch(state.tr.delete(unitToPos(state.doc, caret), unitToPos(state.doc, units.length)));
      textSync.current?.flush();
    }
    const b = blockRef.current;
    const nb = { id: newId("blk"), type: b.type === "list_item" ? "list_item" : "paragraph", props: { content: fromUnits(tail) } };
    requestFocus(nb.id, "start");
    void submit([{ op: "block.insert", doc: ctxRef.current.docId, parent: b.parent_id ?? null, after: b.id, block: nb } as Op]).catch(
      () => undefined,
    );
  }

  function mergeWithPrevious(): boolean {
    if (!editor) return false;
    const { selection, doc } = editor.state;
    if (!selection.empty || posToUnit(doc, selection.from) !== 0) return false;
    const c = ctxRef.current;
    const b = blockRef.current;
    const sibs = childrenOf(c.blocks, b.parent_id ?? null);
    const prev = sibs[sibs.findIndex((s) => s.id === b.id) - 1];
    const units = editorUnits(editor);
    const target = prev && TEXT_TYPES.has(prev.type) ? openBlocks.get(prev.id) : undefined;
    if (target) {
      const len = target.append(units);
      textSync.current?.detach(true);
      target.focus(len);
      void submit([{ op: "block.delete", block: b.id } as Op]).catch(() => undefined);
      return true;
    }
    if (units.length === 0) {
      // leerer Block ohne Text-Vorgänger: löschen (letzter Listenpunkt → ganze Liste), außer er ist der einzige
      if (!b.parent_id && childrenOf(c.blocks, null).length === 1) return false;
      const parent = c.blocks.find((x) => x.id === b.parent_id);
      const id = b.type === "list_item" && sibs.length === 1 && parent ? parent.id : b.id;
      textSync.current?.detach(true);
      if (prev && TEXT_TYPES.has(prev.type)) openBlocks.get(prev.id)?.focus("end");
      void submit([{ op: "block.delete", block: id } as Op]).catch(() => undefined);
      return true;
    }
    return false;
  }

  const kind = block.type === "heading" ? `h${block.props.level ?? 1}` : block.type === "paragraph" ? "p" : "li";
  return <EditorContent editor={editor} className={`text-block tb-${kind}`} />;
}
