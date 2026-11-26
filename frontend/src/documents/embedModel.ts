// Einbetten von Tabellen und Workflows in Dokumente (Task 3.F5, B5): reine Logik ohne React.
// Neue Einbettungs-Typen (z. B. Formular, Bild) tragen sich in EMBED_TYPES ein und bekommen einen Zweig in EmbedDialog.
import type { Op } from "../api";
import { type Col, type FilterRow, type SortSpec, activeFilters, slugKey, sortedColumns, uniqueKey } from "../tables/tableModel";
import type { Json } from "../sync/tableRules";
import type { NewBlock } from "./blockOps";

export type EmbedKind = "table_view" | "workflow";

/** Einträge im Abschnitt „Einbetten“ des Einfüge-Menüs. */
export const EMBED_TYPES: { kind: EmbedKind; label: string; icon: "table" | "flow" }[] = [
  { kind: "table_view", label: "Tabelle einbetten", icon: "table" },
  { kind: "workflow", label: "Workflow einbetten", icon: "flow" },
];

export type TableViewConfig = {
  table: string;
  allColumns: Col[];
  /** IDs der sichtbaren Spalten. */
  selected: string[];
  filterRows: FilterRow[];
  sort: SortSpec[];
  editable: boolean;
  allowAdd: boolean;
  allowDelete: boolean;
};

/** Props des `table_view`-Blocks. `columns` entfällt (null), wenn alle Spalten sichtbar sind. */
export function buildTableViewProps(c: TableViewConfig): Json {
  const ordered = sortedColumns(c.allColumns).filter((col) => c.selected.includes(col.id)).map((col) => col.id);
  const all = ordered.length === 0 || ordered.length === c.allColumns.length;
  return {
    table: c.table,
    columns: all ? null : ordered,
    filter: activeFilters(c.filterRows, c.allColumns),
    sort: c.sort.filter((s) => c.allColumns.some((col) => col.id === s.column)),
    editable: c.editable,
    allow_add: c.editable && c.allowAdd,
    allow_delete: c.editable && c.allowDelete,
  };
}

export const tableViewBlock = (id: string, props: Json): NewBlock => ({ id, type: "table_view", props });

export const workflowBlock = (id: string, workflow: string): NewBlock => ({
  id, type: "workflow", props: { workflow, mode: "launcher", wait: false },
});

/** `table.create`-Op für eine neue Tabelle mit einer Startspalte „Name“; der Key wird aus dem Namen abgeleitet und ist eindeutig. */
export function newTableOp(id: string, name: string, takenKeys: string[], colId: string): Op {
  const key = uniqueKey(slugKey(name), takenKeys);
  return {
    op: "table.create", id, key, name: name.trim(),
    columns: [{ id: colId, key: "name", name: "Name", type: { kind: "text" }, required: false, unique: false }],
  } as Op;
}
