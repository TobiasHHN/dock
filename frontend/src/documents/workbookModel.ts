// Arbeitsmappe (Task 3.F5, B8): Ein Dokument zeigt unten Blätter wie in Excel. Blatt 1 ist das Dokument selbst,
// danach je ein Blatt pro eingebetteter Tabelle (`table_view`) und pro eingebettetem Workflow (`workflow`).
// Reine Logik ohne React.
import { type FlatBlock, childrenOf } from "./blockOps";

export type SheetKind = "table" | "workflow";
export type Sheet = { kind: SheetKind; id: string };
type Ref = { id: string; key?: string };

/** Blöcke in Dokumentreihenfolge (Tiefensuche über `parent_id` und `position`). */
export function inDocumentOrder(blocks: FlatBlock[]): FlatBlock[] {
  const out: FlatBlock[] = [];
  const walk = (parent: string | null) => {
    for (const b of childrenOf(blocks, parent)) {
      out.push(b);
      walk(b.id);
    }
  };
  walk(null);
  return out;
}

function resolve(ref: unknown, known?: Ref[]): string | null {
  if (typeof ref !== "string" || !ref) return null;
  if (!known) return ref;
  return known.find((k) => k.id === ref || (k.key && k.key === ref))?.id ?? null;
}

/**
 * Blätter hinter Blatt 1: erst alle Tabellen, dann alle Workflows, je in Dokumentreihenfolge und ohne Doppelte.
 * `props.table`/`props.workflow` darf ID oder Key sein; mit `known` werden Keys aufgelöst und unbekannte (gelöschte) Verweise weggelassen.
 */
export function collectSheets(blocks: FlatBlock[], known?: { tables?: Ref[]; workflows?: Ref[] }): Sheet[] {
  const tables: Sheet[] = [];
  const workflows: Sheet[] = [];
  const add = (list: Sheet[], kind: SheetKind, id: string | null) => {
    if (id && !list.some((s) => s.id === id)) list.push({ kind, id });
  };
  for (const b of inDocumentOrder(blocks)) {
    if (b.type === "table_view") add(tables, "table", resolve(b.props?.table, known?.tables));
    else if (b.type === "workflow") add(workflows, "workflow", resolve(b.props?.workflow, known?.workflows));
  }
  return [...tables, ...workflows];
}

/** Aktives Blatt aus dem URL-Parameter `sheet`; fehlt oder passt keins, ist es Blatt 1 (`null` = Dokument). */
export function activeSheet(param: string | null | undefined, sheets: Sheet[]): Sheet | null {
  return (param && sheets.find((s) => s.id === param)) || null;
}

/** Neuer Wert des URL-Parameters `sheet` (`null` = Parameter entfernen, also Dokument). */
export const sheetParam = (s: Sheet | null): string | null => s?.id ?? null;

/** Blatt, das nach dem Einbetten gezeigt werden soll (aus den Props des neuen Blocks). */
export function sheetOfBlock(b: { type: string; props: Record<string, unknown> }): Sheet | null {
  if (b.type === "table_view" && typeof b.props.table === "string") return { kind: "table", id: b.props.table };
  if (b.type === "workflow" && typeof b.props.workflow === "string") return { kind: "workflow", id: b.props.workflow };
  return null;
}
