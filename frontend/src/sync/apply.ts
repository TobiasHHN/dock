// Ops auf den lokalen Zustand anwenden (T 5.3): TypeScript-Spiegel der Backend-Handler
// (backend/app/ops/memory.py + memory_documents.py). Zustand wie in spec/fixtures:
//   { tables: [{ id, key, name, display_column, version, columns: [...], rows: [{ id, position, version, values }] }],
//     documents: [{ id, title, owner?, version, blocks: [{ id, parent_id, position, type, props, version }] }] }
// `applyOps` ist atomar: der übergebene Zustand bleibt unverändert, bei einem Fehler wird `OpError` geworfen.
// Ops ohne Spiegel (draft.*, form.submit, workflow.*, run.*, task.*, …) werfen `UnsupportedOp`; der Sync-Store
// wendet sie nicht optimistisch an, sondern wartet auf den Server (L 7.4).

import { generateKeyBetween } from "fractional-indexing";
import { applyEdit } from "./textOt";
import {
  DomainError, type Json, checkColumnDefinition, checkKey, convertValues, findDuplicates, inUseError,
  prepareValues, resolveDefault, typeDict, validationError,
} from "./tableRules";

export type State = { tables: Json[]; documents: Json[] };

export class OpError extends Error {
  constructor(
    public code: string,
    message: string,
    public fields: Record<string, string> = {},
    public details: Record<string, Json> = {},
  ) {
    super(message);
  }
}

export class UnsupportedOp extends Error {}

type Handler = (m: Mem, op: Json) => void;
const HANDLERS: Record<string, Handler> = {};
const MAX_LISTED = 5;

export function isMirrored(opName: string): boolean {
  return opName in HANDLERS;
}

/** Position echt zwischen a und b (null = offenes Ende), wie domain/positions.py. */
export const between = (a: string | null, b: string | null): string => generateKeyBetween(a, b);

const byPos = (a: Json, b: Json) => (a.position < b.position ? -1 : a.position > b.position ? 1 : 0);

class Mem {
  touched = new Set<string>();
  created = new Set<string>();
  deleted = new Set<string>();
  docBumped = new Set<string>();

  constructor(public state: State) {
    state.tables ??= [];
    state.documents ??= [];
  }

  touch(kind: string, id: string, opts: { created?: boolean; deleted?: boolean } = {}) {
    const k = `${kind}:${id}`;
    this.touched.add(k);
    if (opts.created) this.created.add(k);
    if (opts.deleted) this.deleted.add(k);
  }

  table(ref: string): Json {
    const t = this.state.tables.find((x) => x.id === ref || x.key === ref);
    if (!t) throw new DomainError("NOT_FOUND", `Tabelle '${ref}' wurde nicht gefunden`);
    t.rows ??= [];
    t.columns ??= [];
    return t;
  }

  column(table: Json, ref: string): Json {
    const c = table.columns.find((x: Json) => x.id === ref || x.key === ref);
    if (!c) throw new DomainError("NOT_FOUND", `Spalte '${ref}' wurde nicht gefunden`);
    return c;
  }

  row(table: Json, rowId: string): Json {
    const r = table.rows.find((x: Json) => x.id === rowId);
    if (!r) throw new DomainError("NOT_FOUND", `Zeile '${rowId}' wurde in Tabelle „${table.name}“ nicht gefunden`);
    return r;
  }

  valuesById(table: Json, values: Record<string, Json>): Record<string, Json> {
    return Object.fromEntries(Object.entries(values).map(([k, v]) => [this.column(table, k).id, v]));
  }

  *allRows(): Generator<[Json, Json]> {
    for (const t of this.state.tables) for (const r of t.rows ?? []) yield [t, r];
  }

  *refColumns(): Generator<[Json, Json]> {
    for (const t of this.state.tables) for (const c of t.columns ?? []) if (c.type.kind === "reference") yield [t, c];
  }

  positionAfter(items: Json[], after: string | null | undefined, noneIsEnd: boolean, moving?: string): string {
    const ordered = [...items].sort(byPos).filter((i) => i.id !== moving);
    if (after === null || after === undefined) {
      if (!ordered.length) return between(null, null);
      return noneIsEnd ? between(ordered[ordered.length - 1].position, null) : between(null, ordered[0].position);
    }
    const index = ordered.findIndex((i) => i.id === after);
    if (index < 0) throw new DomainError("NOT_FOUND", `'${after}' (after) gehört nicht zu dieser Tabelle`);
    return between(ordered[index].position, ordered[index + 1]?.position ?? null);
  }

  usages(kind: "table" | "column", target: Json, table: Json): Json[] {
    const names = kind === "column"
      ? new Set([target.id, target.key, `${table.key}.${target.key}`])
      : new Set([table.id, table.key]);
    const found: Json[] = [];
    for (const doc of this.state.documents) {
      for (const block of doc.blocks ?? []) {
        const props = block.props ?? {};
        const onTable = props.table === table.id || props.table === table.key;
        if (block.type === "table_view" && onTable) {
          if (kind === "table") found.push({ source_kind: "block", source_id: block.id, via: "table_view" });
          else {
            if ((props.columns ?? []).some((c: string) => names.has(c)))
              found.push({ source_kind: "block", source_id: block.id, via: "table_view" });
            if ((props.filter ?? []).some((f: Json) => names.has(f.column)) || (props.sort ?? []).some((s: Json) => names.has(s.column)))
              found.push({ source_kind: "block", source_id: block.id, via: "filter" });
          }
        }
        if (kind === "column" && block.type === "field" && names.has(props.column))
          found.push({ source_kind: "block", source_id: block.id, via: "field.column" });
      }
    }
    if (kind === "table")
      for (const [t, c] of this.refColumns())
        if (c.type.table === table.id && t.id !== table.id)
          found.push({ source_kind: "column", source_id: c.id, via: "reference_column" });
    return found;
  }
}

function register(name: string, fn: Handler) {
  HANDLERS[name] = fn;
}

/** Wendet `ops` atomar an und gibt den neuen Zustand zurück (der übergebene bleibt unverändert). */
export function applyOps(state: State, ops: Json[]): State {
  const mem = new Mem(structuredClone(state));
  try {
    for (const op of ops) {
      const handler = HANDLERS[op.op];
      if (!handler) throw new UnsupportedOp(`Operation '${op.op}' hat noch keine Fassung im Frontend`);
      handler(mem, op);
    }
  } catch (e) {
    if (e instanceof DomainError) throw new OpError(e.code, e.message, e.fields, e.details);
    throw e;
  }
  bumpVersions(mem);
  return mem.state;
}

function bumpVersions(mem: Mem) {
  for (const k of mem.touched) {
    if (mem.created.has(k) || mem.deleted.has(k)) continue;
    const [kind, id] = [k.slice(0, k.indexOf(":")), k.slice(k.indexOf(":") + 1)];
    const pool = kind === "table" ? mem.state.tables : kind === "row" ? [...mem.allRows()].map(([, r]) => r) : [];
    for (const item of pool) if (item.id === id) item.version = (item.version ?? 1) + 1;
  }
}

// ── Hilfen Tabellen ──────────────────────────────────────────────────────────

const COLUMN_KEYS = ["id", "key", "name", "type", "required", "unique", "default", "position"];

function cleanColumn(col: Json): Json {
  const out: Json = Object.fromEntries(COLUMN_KEYS.map((k) => [k, structuredClone(col[k] ?? null)]));
  out.type = typeDict(out.type);
  out.required = Boolean(out.required);
  out.unique = Boolean(out.unique);
  return out;
}

function normalizeDefault(col: Json): Json {
  const d = col.default;
  if (d === null || d === undefined) return null;
  if (typeof d === "string" && d.trim().startsWith("{{")) return d.trim();
  return resolveDefault(d, col.type);
}

function checkDefinition(mem: Mem, col: Json, prefix: string, ownTable: string | null): Record<string, string> {
  const errors = checkColumnDefinition(col, prefix);
  const t = typeDict(col.type);
  if (t.kind === "reference") {
    if (col.default != null) errors[`${prefix}default`] = "Referenzspalten können keinen Standardwert haben";
    if (t.table !== ownTable && !mem.state.tables.some((tb) => tb.id === t.table))
      errors[`${prefix}type`] = `Die Zieltabelle „${t.table}“ der Referenz existiert nicht`;
  }
  return errors;
}

function resolveType(mem: Mem, type: Json, ownIds: Record<string, string> = {}): Json {
  const t = { ...type };
  if (t.kind === "reference") t.table = ownIds[t.table] ?? mem.table(t.table).id;
  return t;
}

function checkReferences(mem: Mem, columns: Json[], values: Record<string, Json>): Record<string, string> {
  const errors: Record<string, string> = {};
  const byId = new Map(columns.map((c) => [c.id, c]));
  for (const [colId, value] of Object.entries(values)) {
    const col = byId.get(colId);
    if (!col || value === null || value === undefined || col.type.kind !== "reference") continue;
    const target = mem.state.tables.find((t) => t.id === col.type.table);
    if (!target || !(target.rows ?? []).some((r: Json) => r.id === value))
      errors[col.key] = `${col.name}: Die verwiesene Zeile „${value}“ existiert nicht in der Zieltabelle`;
  }
  return errors;
}

function checkUnique(table: Json, values: Record<string, Json>, exclude = ""): Record<string, string> {
  const errors: Record<string, string> = {};
  const byId = new Map(table.columns.map((c: Json) => [c.id, c]));
  for (const [colId, value] of Object.entries(values)) {
    const col: Json = byId.get(colId);
    if (!col || value === null || value === undefined || !col.unique) continue;
    const other = table.rows.find((r: Json) => r.id !== exclude && r.values[colId] === value);
    if (other)
      errors[col.key] = `${col.name}: Der Wert „${value}“ ist schon vergeben (Zeile ${other.id}), die Spalte verlangt eindeutige Werte`;
  }
  return errors;
}

function rowErrors(errors: Record<string, string>, index: number, total: number): Record<string, string> {
  return total === 1 ? errors : Object.fromEntries(Object.entries(errors).map(([k, v]) => [`rows[${index}].${k}`, v]));
}

const isEmpty = (o: object) => Object.keys(o).length === 0;

// ── table.* ──────────────────────────────────────────────────────────────────

register("table.create", (mem, op) => {
  const errors: Record<string, string> = {};
  const keyMsg = checkKey("table", op.key);
  if (keyMsg) errors.key = keyMsg;
  if (!String(op.name ?? "").trim()) errors.name = "Der Tabellenname darf nicht leer sein";
  if (mem.state.tables.some((t) => t.id === op.id)) errors.id = `Die Tabellen-ID „${op.id}“ existiert bereits`;
  if (mem.state.tables.some((t) => t.key === op.key)) errors.key = `Es gibt schon eine Tabelle mit dem Key „${op.key}“`;
  const own = { [op.key]: op.id, [op.id]: op.id };
  const columns: Json[] = [];
  let previous: string | null = null;
  (op.columns ?? []).forEach((raw: Json, i: number) => {
    const prefix = `columns[${i}].`;
    const col = cleanColumn({ ...raw, type: resolveType(mem, typeDict(raw.type), own) });
    Object.assign(errors, checkDefinition(mem, col, prefix, op.id));
    if (columns.some((c) => c.key === col.key)) errors[`${prefix}key`] = `Der Spalten-Key „${col.key}“ kommt mehrfach vor`;
    if (columns.some((c) => c.id === col.id)) errors[`${prefix}id`] = `Die Spalten-ID „${col.id}“ kommt mehrfach vor`;
    col.position = col.position || between(previous, null);
    previous = col.position;
    columns.push(col);
  });
  let display = op.display_column;
  if (display) {
    display = columns.find((c) => c.id === display || c.key === display)?.id ?? null;
    if (!display) errors.display_column = "Die Anzeigespalte muss eine Spalte dieser Tabelle sein";
  } else if (columns.length) display = columns[0].id;
  if (!isEmpty(errors)) throw validationError(errors, `Die Tabelle „${op.name}“`);
  for (const col of columns) col.default = normalizeDefault(col);
  mem.state.tables.push({ id: op.id, key: op.key, name: op.name, display_column: display ?? null, version: 1, columns, rows: [] });
  mem.touch("table", op.id, { created: true });
});

register("table.update", (mem, op) => {
  const table = mem.table(op.table);
  const errors: Record<string, string> = {};
  if ("name" in op && (op.name === null || !String(op.name).trim())) errors.name = "Der Tabellenname darf nicht leer sein";
  if (op.key != null) {
    const msg = checkKey("table", op.key);
    if (msg) errors.key = msg;
    else if (mem.state.tables.some((t) => t.key === op.key && t.id !== table.id))
      errors.key = `Es gibt schon eine Tabelle mit dem Key „${op.key}“`;
  }
  let display: string | null = null;
  if (op.display_column != null) {
    display = table.columns.find((c: Json) => c.id === op.display_column || c.key === op.display_column)?.id ?? null;
    if (!display) errors.display_column = "Die Anzeigespalte muss eine Spalte dieser Tabelle sein";
  }
  if (!isEmpty(errors)) throw validationError(errors, `Die Tabelle „${table.name}“`);
  if (op.name != null) table.name = op.name;
  if (op.key != null) table.key = op.key;
  if (display) table.display_column = display;
  mem.touch("table", table.id);
});

register("table.delete", (mem, op) => {
  const table = mem.table(op.table);
  const usages = mem.usages("table", table, table);
  if (usages.length) throw inUseError(`Die Tabelle „${table.name}“`, usages);
  mem.state.tables = mem.state.tables.filter((t) => t !== table);
  mem.touch("table", table.id, { deleted: true });
});

// ── column.* ─────────────────────────────────────────────────────────────────

register("column.add", (mem, op) => {
  const table = mem.table(op.table);
  const raw = op.column;
  const col = cleanColumn({ ...raw, type: resolveType(mem, typeDict(raw.type), { [table.key]: table.id }) });
  const errors = checkDefinition(mem, col, "column.", table.id);
  if (table.columns.some((c: Json) => c.key === col.key))
    errors["column.key"] = `Die Tabelle „${table.name}“ hat schon eine Spalte mit dem Key „${col.key}“`;
  if (mem.state.tables.some((t) => (t.columns ?? []).some((c: Json) => c.id === col.id)))
    errors["column.id"] = `Die Spalten-ID „${col.id}“ existiert bereits`;
  const count = table.rows.length;
  let fill: Json = null;
  if (isEmpty(errors)) {
    col.default = normalizeDefault(col);
    fill = col.default !== null ? resolveDefault(col.default, col.type) : null;
    if (count && col.required && fill === null)
      errors["column.required"] = `„${col.name}“ kann kein Pflichtfeld sein: die Tabelle hat schon ${count} Zeilen ohne Wert. Gib einen Standardwert an oder lege die Spalte zuerst als optional an`;
    if (count > 1 && col.unique && fill !== null)
      errors["column.unique"] = `„${col.name}“ kann nicht eindeutig sein: der Standardwert würde in ${count} Zeilen stehen`;
  }
  if (!isEmpty(errors)) throw validationError(errors, `Die Spalte „${col.name}“`);
  const after = op.after ? mem.column(table, op.after).id : null;
  col.position = col.position || mem.positionAfter(table.columns, after, true);
  table.columns.push(col);
  if (fill !== null) for (const row of table.rows) row.values[col.id] = fill;
  mem.touch("table", table.id);
});

register("column.update", (mem, op) => {
  const table = mem.table(op.table);
  const col = mem.column(table, op.column);
  const patch = op.patch ?? {};
  const next: Json = structuredClone(col);
  const errors: Record<string, string> = {};
  if (patch.key != null) {
    next.key = patch.key;
    if (table.columns.some((c: Json) => c.key === patch.key && c.id !== col.id))
      errors["patch.key"] = `Die Tabelle „${table.name}“ hat schon eine Spalte mit dem Key „${patch.key}“`;
  }
  if (patch.name != null) next.name = patch.name;
  if (patch.type != null) next.type = resolveType(mem, typeDict(patch.type), { [table.key]: table.id });
  for (const flag of ["required", "unique"]) if (patch[flag] != null) next[flag] = patch[flag];
  if ("default" in patch) next.default = patch.default;
  for (const [path, msg] of Object.entries(checkDefinition(mem, next, "patch.", table.id))) errors[path] ??= msg;
  if (!isEmpty(errors)) throw validationError(errors, `Die Spalte „${col.name}“`);
  next.default = normalizeDefault(next);

  const typeChanged = JSON.stringify(typeDict(col.type)) !== JSON.stringify(typeDict(next.type));
  const oldVals: Record<string, Json> = Object.fromEntries(table.rows.map((r: Json) => [r.id, r.values[col.id] ?? null]));
  const final = { ...oldVals };
  let lost: Record<string, string> = {};
  if (typeChanged) {
    const [converted, l] = convertValues(oldVals, next.type);
    lost = l;
    if (next.type.kind === "reference") {
      const target = mem.state.tables.find((t) => t.id === next.type.table);
      const known = new Set((target?.rows ?? []).map((r: Json) => r.id));
      for (const [rowId, value] of Object.entries(converted))
        if (value !== null && !known.has(value)) {
          converted[rowId] = null;
          lost[rowId] = `Zeile „${value}“ existiert nicht in der Zieltabelle`;
        }
    }
    Object.assign(final, converted);
  }
  if (next.required && (typeChanged || !col.required)) {
    const empty = Object.entries(final).filter(([, v]) => v === null || v === undefined).map(([r]) => r);
    if (empty.length) {
      const listed = empty.slice(0, MAX_LISTED).map((r) => `${r} (${lost[r] || "leer"})`).join(", ");
      const more = empty.length > MAX_LISTED ? ` und ${empty.length - MAX_LISTED} weitere` : "";
      const what = typeChanged ? "Die Typänderung" : "Die Änderung zum Pflichtfeld";
      throw new DomainError(
        "VALIDATION",
        `${what} wird abgelehnt: „${next.name}“ ist ein Pflichtfeld, aber ${empty.length} Zeilen hätten keinen Wert: ${listed}${more}. Korrigiere diese Zeilen zuerst.`,
        { [typeChanged ? "patch.type" : "patch.required"]: `${empty.length} Zeilen ohne Wert: ${listed}${more}` },
        { rows: Object.fromEntries(empty.map((r) => [r, lost[r] || "leer"])) },
      );
    }
  }
  if (next.unique && (typeChanged || !col.unique)) {
    const dup = Object.entries(findDuplicates(final));
    if (dup.length) {
      const [value, ids] = dup[0];
      const msg = `„${next.name}“ kann nicht eindeutig sein: der Wert „${value}“ steht in ${ids.slice(0, MAX_LISTED).join(", ")}`;
      throw new DomainError("VALIDATION", msg, { "patch.unique": msg }, { rows: Object.fromEntries(ids.map((r) => [r, `doppelt: ${value}`])) });
    }
  }
  for (const k of ["key", "name", "type", "required", "unique", "default"]) col[k] = next[k];
  for (const row of table.rows) {
    const value = final[row.id];
    if (value === null || value === undefined) delete row.values[col.id];
    else row.values[col.id] = value;
  }
  mem.touch("table", table.id);
});

register("column.move", (mem, op) => {
  const table = mem.table(op.table);
  const col = mem.column(table, op.column);
  const after = op.after ? mem.column(table, op.after).id : null;
  if (after !== col.id) col.position = mem.positionAfter(table.columns, after, false, col.id);
  mem.touch("table", table.id);
});

register("column.delete", (mem, op) => {
  const table = mem.table(op.table);
  const col = mem.column(table, op.column);
  const usages = mem.usages("column", col, table);
  if (usages.length) throw inUseError(`Die Spalte „${col.name}“`, usages);
  table.columns = table.columns.filter((c: Json) => c !== col);
  if (table.display_column === col.id) table.display_column = [...table.columns].sort(byPos)[0]?.id ?? null;
  for (const row of table.rows) delete row.values[col.id];
  mem.touch("table", table.id);
});

// ── row.* ────────────────────────────────────────────────────────────────────

register("row.insert", (mem, op) => {
  const table = mem.table(op.table);
  const total = op.rows.length;
  op.rows.forEach((newRow: Json, index: number) => {
    const subject = total === 1 ? "Die Zeile" : `Zeile ${index + 1}`;
    let values: Record<string, Json>;
    try {
      values = prepareValues(table.columns, mem.valuesById(table, newRow.values ?? {}), { insert: true, subject });
    } catch (e) {
      if (e instanceof DomainError) throw new DomainError(e.code, e.message, rowErrors(e.fields, index, total));
      throw e;
    }
    const errors = { ...checkReferences(mem, table.columns, values), ...checkUnique(table, values) };
    if ([...mem.allRows()].some(([, r]) => r.id === newRow.id)) errors.id = `Die Zeilen-ID „${newRow.id}“ existiert bereits`;
    if (!isEmpty(errors)) throw validationError(rowErrors(errors, index, total), subject);
    const position = mem.positionAfter(table.rows, newRow.after, true);
    table.rows.push({ id: newRow.id, position, version: 1, values });
    mem.touch("row", newRow.id, { created: true });
  });
});

register("row.update", (mem, op) => {
  const table = mem.table(op.table);
  const row = mem.row(table, op.row);
  let changes = prepareValues(table.columns, mem.valuesById(table, op.values ?? {}), { insert: false });
  changes = Object.fromEntries(Object.entries(changes).filter(([k, v]) => v !== (row.values[k] ?? null)));
  const errors = { ...checkReferences(mem, table.columns, changes), ...checkUnique(table, changes, row.id) };
  if (!isEmpty(errors)) throw validationError(errors, "Die Zeile");
  for (const [colId, value] of Object.entries(changes)) {
    if (value === null || value === undefined) delete row.values[colId];
    else row.values[colId] = value;
  }
  mem.touch("row", row.id);
});

register("row.move", (mem, op) => {
  const table = mem.table(op.table);
  const row = mem.row(table, op.row);
  const after = op.after ?? null;
  if (after !== row.id) row.position = mem.positionAfter(table.rows, after, false, row.id);
  mem.touch("row", row.id);
});

register("row.delete", (mem, op) => {
  const table = mem.table(op.table);
  const wanted: string[] = [...new Set<string>(op.rows)];
  const missing = wanted.filter((r) => !table.rows.some((x: Json) => x.id === r));
  if (missing.length) throw new DomainError("NOT_FOUND", `Zeile(n) ${missing.join(", ")} in Tabelle „${table.name}“ nicht gefunden`);
  const refCols = new Map<string, [Json, Json]>();
  for (const [t, c] of mem.refColumns()) refCols.set(c.id, [t, c]);

  // Plan entlang on_delete (plan_row_delete im Backend)
  const deleting = new Set<string>(wanted);
  const order = [...wanted];
  let frontier = new Set<string>(wanted);
  const setNull = new Map<string, [string, string]>();
  const restrict = new Map<string, [string, string, string]>();
  while (frontier.size) {
    const links: [string, string, string][] = [];
    for (const [, row] of mem.allRows())
      for (const colId of refCols.keys())
        if (frontier.has(row.values[colId])) links.push([row.id, colId, row.values[colId]]);
    frontier = new Set();
    for (const link of links) {
      const [fromRow, colId] = link;
      const mode = refCols.get(colId)![1].type.on_delete ?? "restrict";
      if (mode === "cascade") {
        if (!deleting.has(fromRow)) {
          deleting.add(fromRow);
          order.push(fromRow);
          frontier.add(fromRow);
        }
      } else if (mode === "set_null") setNull.set(`${fromRow}|${colId}`, [fromRow, colId]);
      else restrict.set(link.join("|"), link);
    }
  }
  const blocked = [...restrict.values()].filter(([f]) => !deleting.has(f));
  if (blocked.length) {
    const lines = blocked
      .map(([f, c, t]) => {
        const [tb, col] = refCols.get(c)!;
        return `Zeile ${f} (Tabelle „${tb.name}“, Spalte „${col.name}“) verweist auf ${t}`;
      })
      .join("; ");
    throw new DomainError(
      "IN_USE",
      `Die Zeile kann nicht gelöscht werden, weil sie noch verwendet wird: ${lines}. Lösche oder ändere zuerst diese Zeilen.`,
      {},
      { usages: blocked.map(([f, c, t]) => ({ source_kind: "row", source_id: f, via: "reference_column", column: c, target: t })) },
    );
  }
  for (const [fromRow, colId] of setNull.values()) {
    if (deleting.has(fromRow)) continue;
    const row = [...mem.allRows()].find(([, r]) => r.id === fromRow)![1];
    delete row.values[colId];
    mem.touch("row", fromRow);
  }
  for (const t of mem.state.tables) {
    const gone = (t.rows ?? []).filter((r: Json) => deleting.has(r.id));
    t.rows = (t.rows ?? []).filter((r: Json) => !deleting.has(r.id));
    for (const r of gone) mem.touch("row", r.id, { deleted: true });
  }
  void order;
});

// ── Dokumente (L 3) ──────────────────────────────────────────────────────────

const ALLOWED_CHILDREN: Record<string, Set<string>> = {
  list: new Set(["list_item"]),
  list_item: new Set(["list"]),
  quote: new Set(["paragraph", "heading", "list"]),
  form: new Set(["heading", "paragraph", "list", "quote", "code", "divider", "image", "table_view", "field", "line_items", "workflow"]),
};
const ONLY_INSIDE: Record<string, string> = { field: "form", line_items: "form", list_item: "list" };
export const TEXT_TYPES = new Set(["heading", "paragraph", "list_item"]);

/** Wirft Error, wenn childType unter parentType nicht erlaubt ist (check_nesting im Backend). */
export function checkNesting(parentType: string | null, childType: string): void {
  const only = ONLY_INSIDE[childType];
  if (parentType === null) {
    if (only) throw new Error(`'${childType}' darf nur innerhalb von '${only}' stehen, nicht auf oberster Ebene`);
    return;
  }
  if (ALLOWED_CHILDREN[parentType]?.has(childType)) return;
  if (only) throw new Error(`'${childType}' darf nur innerhalb von '${only}' stehen, nicht in '${parentType}'`);
  if (!ALLOWED_CHILDREN[parentType]) throw new Error(`'${parentType}' darf keine Kinder haben (hier: '${childType}')`);
  const allowed = [...ALLOWED_CHILDREN[parentType]].sort().join(", ");
  throw new Error(`'${childType}' ist in '${parentType}' nicht erlaubt (erlaubt: ${allowed})`);
}

const PROP_DEFAULTS: Record<string, Json> = {
  heading: { level: 1, content: [] },
  paragraph: { content: [] },
  list: { ordered: false },
  list_item: { content: [], checked: null },
  quote: {},
  code: { language: null, text: "" },
  divider: {},
  image: { alt: "" },
  table_view: { columns: null, filter: [], sort: [], editable: false, allow_add: false, allow_delete: false },
  form: { actions: [], buttons: null, reset_after_submit: null },
  field: { input: null, required: false, column: null, default: null, options: null, reference_table: null },
  line_items: { min_rows: null },
  workflow: { mode: "launcher", run: null, input: null, wait: false },
};

/** Props mit Standardwerten auffüllen (vereinfachte Fassung von normalize_props, ohne Validierung). */
export function normalizeProps(type: string, props: Json): Json {
  if (!(type in PROP_DEFAULTS)) throw new DomainError("VALIDATION", `type: Unbekannter Blocktyp '${type}'`, { type: `Unbekannter Blocktyp '${type}'` });
  const out = { ...structuredClone(PROP_DEFAULTS[type]), ...structuredClone(props ?? {}) };
  if (TEXT_TYPES.has(type)) out.content = (out.content ?? []).map((p: Json) => (p.t === "text" ? { marks: [], ...p } : p));
  return out;
}

const invalid = (path: string, message: string) => new DomainError("VALIDATION", `${path}: ${message}`, { [path]: message });

function getDoc(mem: Mem, ref: string): Json {
  const doc = mem.state.documents.find((d) => d.id === ref);
  if (!doc) throw new DomainError("NOT_FOUND", `Dokument '${ref}' wurde nicht gefunden`);
  doc.blocks ??= [];
  return doc;
}

function getBlock(mem: Mem, ref: string): [Json, Json] {
  for (const doc of mem.state.documents)
    for (const block of doc.blocks ?? []) if (block.id === ref) return [doc, block];
  throw new DomainError("NOT_FOUND", `Block '${ref}' wurde nicht gefunden`);
}

function siblings(doc: Json, parent: string | null, exclude?: string): Json[] {
  return doc.blocks.filter((b: Json) => (b.parent_id ?? null) === parent && b.id !== exclude).sort(byPos);
}

function blockPosition(sibs: Json[], after: string | null | undefined): string {
  if (after === null || after === undefined) return between(sibs[sibs.length - 1]?.position ?? null, null);
  if (after === "^") return between(null, sibs[0]?.position ?? null);
  const i = sibs.findIndex((s) => s.id === after);
  if (i < 0) throw invalid("after", `'${after}' ist kein Geschwisterblock an dieser Stelle`);
  return between(sibs[i].position, sibs[i + 1]?.position ?? null);
}

function bumpDoc(mem: Mem, doc: Json, block?: Json) {
  if (!mem.docBumped.has(doc.id) && !mem.created.has(`document:${doc.id}`)) {
    doc.version = (doc.version ?? 1) + 1;
    mem.docBumped.add(doc.id);
  }
  if (block && !mem.docBumped.has(block.id) && !mem.created.has(`block:${block.id}`)) {
    block.version = (block.version ?? 1) + 1;
    mem.docBumped.add(block.id);
  }
}

type Node = { id: string; type: string; props: Json; children: Node[] };

function normalizeNodes(raw: Json[], path: string): Node[] {
  return (raw ?? []).map((n: Json, i: number) => {
    if (!n || typeof n.id !== "string" || typeof n.type !== "string") throw invalid(`${path}.${i}`, "Block braucht id und type");
    return { id: n.id, type: n.type, props: normalizeProps(n.type, n.props), children: normalizeNodes(n.children ?? [], `${path}.${i}.children`) };
  });
}

function validateTree(nodes: Node[], parentType: string | null, path: string): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  const visit = (items: Node[], parent: string | null, where: string) => {
    items.forEach((node, i) => {
      const here = `${where}[${i}]`;
      try {
        checkNesting(parent, node.type);
      } catch (e) {
        throw invalid(here, (e as Error).message);
      }
      if (seen.has(node.id)) throw invalid(`${here}.id`, `Block-ID '${node.id}' kommt mehrfach vor`);
      seen.add(node.id);
      ids.push(node.id);
      visit(node.children, node.type, `${here}.children`);
    });
  };
  visit(nodes, parentType, path);
  return ids;
}

function checkIds(mem: Mem, ids: string[]) {
  const taken = new Set(mem.state.documents.flatMap((d) => (d.blocks ?? []).map((b: Json) => b.id)));
  for (const id of ids) if (taken.has(id)) throw invalid("blocks", `Block-ID '${id}' existiert bereits`);
}

function addNodes(mem: Mem, doc: Json, parent: string | null, nodes: Node[], positions: string[]) {
  nodes.forEach((node, i) => {
    doc.blocks.push({ id: node.id, doc_id: doc.id, parent_id: parent, position: positions[i], type: node.type, props: node.props, version: 1 });
    mem.touch("block", node.id, { created: true });
    let prev: string | null = null;
    const keys = node.children.map(() => (prev = between(prev, null)));
    addNodes(mem, doc, node.id, node.children, keys);
  });
}

register("doc.create", (mem, op) => {
  if (mem.state.documents.some((d) => d.id === op.id)) throw invalid("id", `Dokument-ID '${op.id}' existiert bereits`);
  if (op.markdown) throw new UnsupportedOp("doc.create mit Markdown wird nur vom Server ausgeführt");
  const nodes = normalizeNodes(op.blocks ?? [], "blocks");
  checkIds(mem, validateTree(nodes, null, "blocks"));
  const doc: Json = { id: op.id, title: op.title, version: 1, blocks: [] };
  if (op.owner) doc.owner = op.owner;
  mem.state.documents.push(doc);
  mem.touch("document", doc.id, { created: true });
  let prev: string | null = null;
  addNodes(mem, doc, null, nodes, nodes.map(() => (prev = between(prev, null))));
});

register("doc.update", (mem, op) => {
  const doc = getDoc(mem, op.doc);
  doc.title = op.title;
  bumpDoc(mem, doc);
});

register("doc.delete", (mem, op) => {
  const doc = getDoc(mem, op.doc);
  mem.state.documents = mem.state.documents.filter((d) => d !== doc);
});

register("block.insert", (mem, op) => {
  const doc = getDoc(mem, op.doc);
  const parent: string | null = op.parent ?? null;
  let parentType: string | null = null;
  if (parent) {
    const [owner, found] = getBlock(mem, parent);
    if (owner !== doc) throw invalid("parent", `Block '${parent}' liegt in einem anderen Dokument`);
    parentType = found.type;
  }
  const nodes = normalizeNodes([op.block], "block");
  checkIds(mem, validateTree(nodes, parentType, "block"));
  addNodes(mem, doc, parent, nodes, [blockPosition(siblings(doc, parent), op.after)]);
  bumpDoc(mem, doc);
});

register("block.update", (mem, op) => {
  const [doc, block] = getBlock(mem, op.block);
  const props = normalizeProps(block.type, { ...block.props, ...op.props });
  if (JSON.stringify(props) !== JSON.stringify(block.props)) {
    block.props = props;
    mem.touch("block", block.id);
    bumpDoc(mem, doc, block);
  }
});

// text.edit (L 7.5, T 2.6): wendet den vom Server bereits transformierten Edit an (Transformation: textOt.ts).
register("text.edit", (mem, op) => {
  const [doc, block] = getBlock(mem, op.block);
  if (!TEXT_TYPES.has(block.type))
    throw invalid("block", `'${block.type}' hat keinen Text, text.edit gilt nur für ${[...TEXT_TYPES].sort().join(", ")}`);
  const props = normalizeProps(block.type, { ...block.props, content: applyEdit(block.props.content ?? [], op) });
  if (JSON.stringify(props) !== JSON.stringify(block.props)) {
    block.props = props;
    mem.touch("block", block.id);
    bumpDoc(mem, doc, block);
  }
});

register("block.move", (mem, op) => {
  const [doc, block] = getBlock(mem, op.block);
  const parent: string | null = op.parent ?? null;
  let parentType: string | null = null;
  if (parent) {
    const [owner, found] = getBlock(mem, parent);
    if (owner !== doc) throw invalid("parent", `Block '${parent}' liegt in einem anderen Dokument`);
    parentType = found.type;
    let cursor: string | null = parent;
    while (cursor) {
      if (cursor === block.id) throw invalid("parent", "Ein Block kann nicht in sich selbst oder einen seiner Nachfahren verschoben werden");
      const c: string = cursor;
      cursor = doc.blocks.find((b: Json) => b.id === c)?.parent_id ?? null;
    }
  }
  try {
    checkNesting(parentType, block.type);
  } catch (e) {
    throw invalid("parent", (e as Error).message);
  }
  if (op.after === block.id) throw invalid("after", "Ein Block kann nicht hinter sich selbst stehen");
  block.position = blockPosition(siblings(doc, parent, block.id), op.after);
  block.parent_id = parent;
  mem.touch("block", block.id);
  bumpDoc(mem, doc, block);
});

register("block.delete", (mem, op) => {
  const [doc, block] = getBlock(mem, op.block);
  const doomed = new Set<string>([block.id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const b of doc.blocks)
      if (doomed.has(b.parent_id) && !doomed.has(b.id)) {
        doomed.add(b.id);
        grew = true;
      }
  }
  doc.blocks = doc.blocks.filter((b: Json) => !doomed.has(b.id));
  for (const id of doomed) mem.touch("block", id, { deleted: true });
  bumpDoc(mem, doc);
});

export { DomainError };
