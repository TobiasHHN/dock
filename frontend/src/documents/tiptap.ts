// TipTap-Schema für einen Textblock (T 5.4: eine schlanke Instanz pro Block) und die Übersetzung
// Inline[] (L 3.3) <-> ProseMirror <-> Einheiten (Positionen von text.edit, siehe sync/textOt.ts).
import { Node, type Editor, type JSONContent } from "@tiptap/react";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import StarterKit from "@tiptap/starter-kit";
import { Fragment, type Node as PMNode, type Schema, Slice } from "@tiptap/pm/model";
import { TextSelection } from "@tiptap/pm/state";
import type { Json } from "../sync/tableRules";
import { type Edit, MARK_ORDER, type Mark, type Unit, cpLength, fromUnits, toUnits } from "../sync/textOt";

/** Ein Textblock enthält genau einen Absatz; Überschrift/Listenpunkt ergibt sich aus dem Blocktyp. */
const OneParagraph = Node.create({ name: "doc", topNode: true, content: "paragraph" });

function formatValueDisplay(val: Json): string {
  if (val === true) return "Ja";
  if (val === false) return "Nein";
  return String(val);
}

/** Erwähnung (`mention`) und berechneter Wert (`value`): eine nicht teilbare Einheit. */
const InlineAtom = Node.create({
  name: "inlineAtom",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes: () => ({ kind: { default: "mention" }, value: { default: "" }, display: { default: null } }),
  parseHTML: () => [{ tag: "span[data-atom]" }],
  renderHTML: ({ node }) => [
    "span",
    { class: node.attrs.kind, "data-atom": node.attrs.kind, contenteditable: "false" },
    node.attrs.kind === "mention" ? `@${node.attrs.value}` : (node.attrs.display ?? node.attrs.value),
  ],
});

export function textExtensions(placeholder: string) {
  return [
    StarterKit.configure({
      document: false, heading: false, bulletList: false, orderedList: false, listItem: false, blockquote: false,
      codeBlock: false, horizontalRule: false, dropcursor: false, gapcursor: false,
    }),
    OneParagraph,
    InlineAtom,
    Link.configure({ openOnClick: false, autolink: false }),
    Placeholder.configure({ placeholder }),
  ];
}

// ── Inline[] <-> ProseMirror-JSON ────────────────────────────────────────────

function inlineNodes(content: Json[] | undefined): JSONContent[] {
  const out: JSONContent[] = [];
  const pushText = (text: string, marks: JSONContent["marks"]) => {
    text.split("\n").forEach((piece, i) => {
      if (i > 0) out.push({ type: "hardBreak" });
      if (piece) out.push({ type: "text", text: piece, ...(marks?.length ? { marks } : {}) });
    });
  };
  for (const part of content ?? []) {
    if (part.t === "text") pushText(part.text ?? "", (part.marks ?? []).map((m: string) => ({ type: m })));
    else if (part.t === "link") pushText(part.text ?? "", [{ type: "link", attrs: { href: part.href } }]);
    else if (part.t === "mention") out.push({ type: "inlineAtom", attrs: { kind: "mention", value: part.target } });
    else if (part.t === "value")
      out.push({
        type: "inlineAtom",
        attrs: {
          kind: "value",
          value: part.expr,
          display: part.value !== undefined && part.value !== null ? formatValueDisplay(part.value) : null,
        },
      });
  }
  return out;
}

export function inlineToDoc(content: Json[] | undefined): JSONContent {
  const nodes = inlineNodes(content);
  return { type: "doc", content: [{ type: "paragraph", ...(nodes.length ? { content: nodes } : {}) }] };
}

export function docToInline(doc: JSONContent): Json[] {
  const out: Json[] = [];
  for (const n of doc.content?.[0]?.content ?? []) {
    if (n.type === "text") {
      const link = n.marks?.find((m) => m.type === "link");
      if (link) out.push({ t: "link", text: n.text, href: link.attrs?.href ?? "" });
      else {
        const marks = MARK_ORDER.filter((m) => n.marks?.some((x) => x.type === m));
        out.push({ t: "text", text: n.text, marks });
      }
    } else if (n.type === "hardBreak") out.push({ t: "text", text: "\n", marks: [] });
    else if (n.type === "inlineAtom")
      out.push(n.attrs?.kind === "value" ? { t: "value", expr: n.attrs.value } : { t: "mention", target: n.attrs?.value });
  }
  return fromUnits(toUnits(out)); // Nachbarn zusammenfassen
}

export const editorUnits = (editor: Editor): Unit[] => toUnits(docToInline(editor.getJSON()));

// ── Einheiten <-> ProseMirror-Positionen (Code Points vs. UTF-16) ────────────

export function unitToPos(doc: PMNode, unit: number): number {
  const para = doc.firstChild!;
  let pos = 1;
  let rest = unit;
  for (let i = 0; i < para.childCount; i++) {
    const child = para.child(i);
    if (child.isText) {
      const cps = Array.from(child.text!);
      if (rest <= cps.length) return pos + cps.slice(0, rest).join("").length;
      rest -= cps.length;
    } else {
      if (rest === 0) return pos;
      rest -= 1;
    }
    pos += child.nodeSize;
  }
  return pos;
}

export function posToUnit(doc: PMNode, target: number): number {
  const para = doc.firstChild!;
  let pos = 1;
  let units = 0;
  for (let i = 0; i < para.childCount; i++) {
    const child = para.child(i);
    if (target <= pos) return units;
    if (child.isText) {
      if (target <= pos + child.nodeSize) return units + Array.from(child.text!.slice(0, target - pos)).length;
      units += cpLength(child.text!);
    } else units += 1;
    pos += child.nodeSize;
  }
  return units;
}

function unitsToFragment(schema: Schema, units: Unit[]): Fragment {
  return Fragment.fromArray(inlineNodes(fromUnits(units)).map((n) => schema.nodeFromJSON(n)));
}

/** Einheiten-Edit als Transaktion ohne Undo-Eintrag anwenden; der Cursor wird von ProseMirror mitverschoben. */
export function applyUnitsEdit(editor: Editor, edit: Edit, inserted: Unit[]) {
  const { state, view } = editor;
  const from = unitToPos(state.doc, edit.from);
  const to = unitToPos(state.doc, edit.to);
  const tr = state.tr.replace(from, to, new Slice(unitsToFragment(state.schema, inserted), 0, 0));
  tr.setMeta("addToHistory", false).setMeta("remote", true);
  view.dispatch(tr);
}

/** Inhalt vollständig ersetzen, Cursor-Position (in Einheiten) möglichst erhalten. */
export function setEditorUnits(editor: Editor, units: Unit[], remote = true) {
  const { state, view } = editor;
  const caret = posToUnit(state.doc, state.selection.from);
  const tr = state.tr.replaceWith(1, state.doc.firstChild!.nodeSize - 1, unitsToFragment(state.schema, units));
  tr.setSelection(TextSelection.create(tr.doc, unitToPos(tr.doc, Math.min(caret, units.length))));
  if (remote) tr.setMeta("addToHistory", false).setMeta("remote", true);
  view.dispatch(tr);
}

/** Einheiten am Ende anhängen (lokale Eingabe, z. B. beim Zusammenführen zweier Blöcke). */
export function appendUnits(editor: Editor, units: Unit[]): number {
  const { state, view } = editor;
  const len = posToUnit(state.doc, state.doc.firstChild!.nodeSize - 1);
  const end = state.doc.firstChild!.nodeSize - 1;
  view.dispatch(state.tr.insert(end, unitsToFragment(state.schema, units)));
  return len;
}

export type { Mark };
