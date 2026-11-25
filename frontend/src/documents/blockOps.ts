// Block-Operationen für die Dokument-Ansicht (L 6.1). Alle Änderungen laufen über den Sync-Store (ein Schreibweg).
import type { Op } from "../api";
import { newId, submit } from "../sync/store";
import type { Json } from "../sync/tableRules";

export type FlatBlock = { id: string; parent_id: string | null; position: string; type: string; props: Json; version: number };

const byPos = (a: FlatBlock, b: FlatBlock) => (a.position < b.position ? -1 : a.position > b.position ? 1 : 0);

export function childrenOf(blocks: FlatBlock[], parent: string | null): FlatBlock[] {
  return blocks.filter((b) => (b.parent_id ?? null) === parent).sort(byPos);
}

export type NewBlock = { id: string; type: string; props: Json; children?: NewBlock[] };

/** Vorlagen für das Einfüge-Menü. */
export const BLOCK_TEMPLATES: { key: string; label: string; make: () => NewBlock }[] = [
  { key: "paragraph", label: "Absatz", make: () => ({ id: newId("blk"), type: "paragraph", props: { content: [] } }) },
  { key: "h1", label: "Überschrift 1", make: () => ({ id: newId("blk"), type: "heading", props: { level: 1, content: [] } }) },
  { key: "h2", label: "Überschrift 2", make: () => ({ id: newId("blk"), type: "heading", props: { level: 2, content: [] } }) },
  { key: "h3", label: "Überschrift 3", make: () => ({ id: newId("blk"), type: "heading", props: { level: 3, content: [] } }) },
  {
    key: "list", label: "Aufzählung",
    make: () => ({ id: newId("blk"), type: "list", props: { ordered: false }, children: [{ id: newId("blk"), type: "list_item", props: { content: [] } }] }),
  },
  {
    key: "olist", label: "Nummerierte Liste",
    make: () => ({ id: newId("blk"), type: "list", props: { ordered: true }, children: [{ id: newId("blk"), type: "list_item", props: { content: [] } }] }),
  },
  {
    key: "quote", label: "Zitat",
    make: () => ({ id: newId("blk"), type: "quote", props: {}, children: [{ id: newId("blk"), type: "paragraph", props: { content: [] } }] }),
  },
  { key: "code", label: "Code", make: () => ({ id: newId("blk"), type: "code", props: { language: null, text: "" } }) },
  { key: "divider", label: "Trennlinie", make: () => ({ id: newId("blk"), type: "divider", props: {} }) },
  { key: "list_item", label: "Listenpunkt", make: () => ({ id: newId("blk"), type: "list_item", props: { content: [] } }) },
];

/** Welche Vorlagen unter einem Elterntyp erlaubt sind (L 3.2). */
export function templatesFor(parentType: string | null) {
  if (parentType === "list") return BLOCK_TEMPLATES.filter((t) => t.key === "list_item");
  if (parentType === "quote") return BLOCK_TEMPLATES.filter((t) => ["paragraph", "h1", "h2", "h3", "list", "olist"].includes(t.key));
  return BLOCK_TEMPLATES.filter((t) => t.key !== "list_item");
}

/** Erste Text-Block-ID eines neuen Blocks (für den Fokus nach dem Einfügen). */
export function firstTextId(b: NewBlock): string | null {
  if (["paragraph", "heading", "list_item"].includes(b.type)) return b.id;
  for (const c of b.children ?? []) {
    const id = firstTextId(c);
    if (id) return id;
  }
  return null;
}

export const insertBlock = (doc: string, parent: string | null, after: string | undefined, block: NewBlock) =>
  submit([{ op: "block.insert", doc, parent, ...(after ? { after } : {}), block } as Op]);

export const updateBlock = (block: string, props: Json) => submit([{ op: "block.update", block, props } as Op]);

export const deleteBlock = (block: string) => submit([{ op: "block.delete", block } as Op]);

export function moveBlock(blocks: FlatBlock[], block: FlatBlock, dir: -1 | 1) {
  const sibs = childrenOf(blocks, block.parent_id ?? null);
  const i = sibs.findIndex((s) => s.id === block.id);
  let after: string | undefined;
  if (dir === -1) {
    if (i <= 0) return;
    after = i >= 2 ? sibs[i - 2].id : "^";
  } else {
    if (i < 0 || i >= sibs.length - 1) return;
    after = sibs[i + 1].id;
  }
  return submit([{ op: "block.move", block: block.id, parent: block.parent_id ?? null, after } as Op]);
}

export const renameDocument = (doc: string, title: string) => submit([{ op: "doc.update", doc, title } as Op]);
