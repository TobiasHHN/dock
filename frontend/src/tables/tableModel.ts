// Reine Logik des Tabellen-Editors (Task 3.1, L 2, L 3.4): Spalten und Zeilen ordnen, Werte anzeigen und
// eingeben, Filter- und Sortierangaben bauen, Ops erzeugen. Ohne React, damit sie testbar ist.
import type { Op } from "../api";
import { type Json, checkKey, coerceValue, typeDict } from "../sync/tableRules";

export type Col = { id: string; key: string; name: string; type: Json; required?: boolean; position: string; [k: string]: Json };
export type TRow = { id: string; position: string; values: Record<string, Json>; version?: number };
export type FilterOp = "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "contains" | "in" | "is_null";
export type FilterCond = { column: string; op: FilterOp; value?: Json };
export type SortSpec = { column: string; dir: "asc" | "desc" };

const byPos = (a: { position: string }, b: { position: string }) => (a.position < b.position ? -1 : a.position > b.position ? 1 : 0);

export const sortedColumns = (columns: Col[]): Col[] => [...columns].sort(byPos);
export const sortedRows = (rows: TRow[]): TRow[] => [...rows].sort(byPos);

/** Spalte per ID oder Key (Filter und Sortierung dürfen beides verwenden, L 1). */
export const findColumn = (columns: Col[], ref: string): Col | undefined =>
  columns.find((c) => c.id === ref) ?? columns.find((c) => c.key === ref);

// ── Spaltentypen ─────────────────────────────────────────────────────────────

export const TYPE_LABELS: Record<string, string> = {
  text: "Text", long_text: "Langer Text", integer: "Ganzzahl", number: "Zahl", currency: "Betrag", boolean: "Ja/Nein",
  date: "Datum", datetime: "Zeitpunkt", select: "Auswahl", user: "Nutzer", reference: "Verweis",
};

/** Typen, die der Editor beim Anlegen anbietet (Verweise brauchen eine Zielwahl und kommen später). */
export const CREATABLE_KINDS = ["text", "long_text", "integer", "number", "currency", "boolean", "date", "datetime", "select", "user"];

export type NewColumnForm = { name: string; kind: string; required: boolean; options: string; decimals: number };

/** Key aus dem Namen ableiten: klein, ohne Umlaute, ohne Leerzeichen und Punkte, nie mit `col_` beginnend. */
export function slugKey(name: string): string {
  const s = name
    .toLowerCase()
    .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return s.startsWith("col_") ? s.slice(4) : s;
}

/** Eindeutiger Key: hängt bei Kollision `_2`, `_3` … an. */
export function uniqueKey(base: string, taken: string[]): string {
  const b = base || "spalte";
  let key = b;
  for (let n = 2; taken.includes(key); n++) key = `${b}_${n}`;
  return key;
}

export function columnType(f: Pick<NewColumnForm, "kind" | "options" | "decimals">): Json {
  switch (f.kind) {
    case "number":
      return { kind: "number", decimals: f.decimals };
    case "currency":
      return { kind: "currency", currency: "EUR" };
    case "select": {
      const labels = f.options.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
      return { kind: "select", options: labels.map((label, i) => ({ id: slugKey(label) || `opt_${i + 1}`, label })) };
    }
    default:
      return { kind: f.kind };
  }
}

/** Neue Spalte als `column.add`-Op; liefert Fehlermeldungen pro Feld, wenn die Eingabe nicht passt. */
export function buildColumnAdd(
  table: { id: string; columns: Col[] }, form: NewColumnForm, newId: () => string,
): { op: Op } | { errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const name = form.name.trim();
  if (!name) errors.name = "Bitte einen Namen eingeben";
  const key = uniqueKey(slugKey(name), table.columns.map((c) => c.key));
  const keyMsg = name ? checkKey("column", key) : null;
  if (keyMsg) errors.name = keyMsg;
  const type = columnType(form);
  if (form.kind === "select") {
    const opts: { id: string }[] = type.options;
    if (!opts.length) errors.options = "Mindestens eine Option angeben";
    else if (new Set(opts.map((o) => o.id)).size !== opts.length) errors.options = "Optionen müssen sich im Namen unterscheiden";
  }
  if (Object.keys(errors).length) return { errors };
  const last = sortedColumns(table.columns).at(-1);
  return {
    op: {
      op: "column.add", table: table.id, ...(last ? { after: last.id } : {}),
      column: { id: newId(), key, name, type, required: form.required, unique: false },
    } as Op,
  };
}

// ── Werte anzeigen und eingeben ──────────────────────────────────────────────

const nf = (decimals: number) => new Intl.NumberFormat("de-DE", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

/** Lesbare Darstellung eines Zellwerts (Zahlen deutsch, Datum als TT.MM.JJJJ, Auswahl mit Label). */
export function displayValue(value: Json, type: Json, users: Record<string, { name: string }> = {}): string {
  if (value === null || value === undefined || value === "") return "";
  const t = typeDict(type);
  switch (t.kind) {
    case "boolean":
      return value ? "Ja" : "Nein";
    case "integer":
      return typeof value === "number" ? nf(0).format(value) : String(value);
    case "number":
      return typeof value === "number" ? nf(t.decimals).format(value) : String(value);
    case "currency":
      return typeof value === "number" ? `${nf(2).format(value)} ${t.currency === "EUR" ? "€" : t.currency}` : String(value);
    case "date": {
      const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
      return m ? `${m[3]}.${m[2]}.${m[1]}` : String(value);
    }
    case "datetime": {
      const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(value));
      return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : String(value);
    }
    case "select":
      return (t.options ?? []).find((o: { id: string }) => o.id === value)?.label ?? String(value);
    case "user":
      return users[String(value)]?.name ?? String(value);
    default:
      return typeof value === "object" ? JSON.stringify(value) : String(value);
  }
}

/** Text für das Eingabefeld (ohne Tausendertrennzeichen, mit Dezimalkomma). */
export function inputText(value: Json, type: Json): string {
  if (value === null || value === undefined) return "";
  const t = typeDict(type);
  if (["integer", "number", "currency"].includes(t.kind) && typeof value === "number") return String(value).replace(".", ",");
  if (t.kind === "date") return String(value).slice(0, 10);
  if (t.kind === "datetime") return String(value).slice(0, 16);
  return String(value);
}

/** Eingabetext in den Spaltentyp umwandeln. `{ error }` bei Fehlern, damit die Zelle den Grund zeigen kann. */
export function parseInput(text: Json, type: Json): { value: Json } | { error: string } {
  try {
    return { value: coerceValue(text, type) };
  } catch (e) {
    return { error: (e as Error).message };
  }
}

// ── Sortierung (lokal, wenn kein Filter aktiv ist) ───────────────────────────

const isEmptyValue = (v: Json) => v === null || v === undefined || v === "";

function compareValues(a: Json, b: Json, type: Json): number {
  const kind = typeDict(type).kind;
  if (["integer", "number", "currency"].includes(kind)) return Number(a) - Number(b);
  if (kind === "boolean") return Number(!!a) - Number(!!b);
  return String(a).localeCompare(String(b), "de", { numeric: true, sensitivity: "base" });
}

/** Stabil nach mehreren Spalten sortiert; Leere stehen immer hinten. Ohne `sort` bleibt die Reihenfolge erhalten. */
export function sortRows(rows: TRow[], columns: Col[], sort: SortSpec[]): TRow[] {
  const specs = sort.flatMap((s) => {
    const col = findColumn(columns, s.column);
    return col ? [{ col, sign: s.dir === "desc" ? -1 : 1 }] : [];
  });
  if (!specs.length) return rows;
  return [...rows].sort((x, y) => {
    for (const { col, sign } of specs) {
      const a = x.values[col.id];
      const b = y.values[col.id];
      const ae = isEmptyValue(a);
      const be = isEmptyValue(b);
      if (ae || be) {
        if (ae !== be) return ae ? 1 : -1;
        continue;
      }
      const c = compareValues(a, b, col.type);
      if (c !== 0) return c * sign;
    }
    return 0;
  });
}

// ── Filter ───────────────────────────────────────────────────────────────────

export const OP_LABELS: Record<FilterOp, string> = {
  eq: "ist", ne: "ist nicht", gt: "größer als", gte: "mindestens", lt: "kleiner als", lte: "höchstens",
  contains: "enthält", in: "ist eines von", is_null: "ist leer",
};

/** Welche Operatoren zu einem Spaltentyp sinnvoll sind. */
export function opsFor(type: Json): FilterOp[] {
  const kind = typeDict(type).kind;
  if (["integer", "number", "currency", "date", "datetime"].includes(kind)) return ["eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null"];
  if (["boolean", "select", "user", "reference"].includes(kind)) return ["eq", "ne", "in", "is_null"];
  return ["eq", "ne", "contains", "in", "is_null"];
}

export const hasExpression = (v: Json): boolean =>
  (typeof v === "string" && v.includes("{{")) || (Array.isArray(v) && v.some(hasExpression));

/** Eingabefeld des Filters (Text) → Wert für die Abfrage. Ausdrücke `{{ }}` bleiben unverändert (der Server wertet sie aus). */
export function filterValue(op: FilterOp, text: string, type: Json): Json {
  if (op === "is_null") return null;
  if (hasExpression(text)) return text;
  const one = (s: string): Json => {
    const r = parseInput(s.trim(), type);
    return "value" in r && r.value !== null ? r.value : s.trim();
  };
  if (op === "in") return text.split(",").map((s) => s.trim()).filter(Boolean).map(one);
  if (op === "contains") return text;
  return one(text);
}

export type FilterRow = { column: string; op: FilterOp; text: string };

/** Filterzeilen des UI-Zustands → Abfrage; unvollständige Zeilen (kein Wert) werden ausgelassen. */
export function activeFilters(rows: FilterRow[], columns: Col[]): FilterCond[] {
  return rows.flatMap((r) => {
    const col = findColumn(columns, r.column);
    if (!col) return [];
    if (r.op !== "is_null" && !r.text.trim()) return [];
    return [{ column: col.id, op: r.op, value: filterValue(r.op, r.text, col.type) }];
  });
}

/** Ergebnis der Serverabfrage (Zeilen-IDs in Serverreihenfolge) auf den Live-Stand legen: gelöschte entfallen. */
export function overlayRows(serverIds: string[], live: TRow[]): TRow[] {
  const map = new Map(live.map((r) => [r.id, r]));
  return serverIds.flatMap((id) => (map.has(id) ? [map.get(id)!] : []));
}

/** Fehlermeldung bei scheiternder Abfrage. 422 = Filter ungültig, auch ein nicht auswertbarer Ausdruck `{{ }}` (der Server nennt den Grund). */
export function queryErrorText(status: number, message: string, conds: FilterCond[]): string {
  if (status === 422 && conds.some((c) => hasExpression(c.value))) return `Der Filter oder sein Ausdruck ist ungültig: ${message}`;
  if (status === 422) return `Der Filter ist ungültig: ${message}`;
  return `Die Zeilen konnten nicht gefiltert werden: ${message}`;
}

// ── Ops ──────────────────────────────────────────────────────────────────────

export const updateCellOp = (table: string, row: string, column: string, value: Json): Op =>
  ({ op: "row.update", table, row, values: { [column]: value } }) as Op;

export const insertRowOp = (table: string, id: string, values: Record<string, Json>, after?: string): Op =>
  ({ op: "row.insert", table, rows: [{ id, values, ...(after ? { after } : {}) }] }) as Op;

export const deleteRowOp = (table: string, row: string): Op => ({ op: "row.delete", table, rows: [row] }) as Op;

/** IDs der Zeilen, die ein Ereignis neu einfügt (für die kurze Hervorhebung). */
export function insertedRowIds(ops: Json[]): string[] {
  return ops.filter((o) => o.op === "row.insert").flatMap((o) => (o.rows ?? []).map((r: Json) => r.id as string));
}

/** Meldungen pro Spalten-Key aus einer abgelehnten Op (`details.errors`) plus die allgemeine Meldung. */
export function fieldErrors(error: { message: string; details?: Json } | undefined | null): { fields: Record<string, string>; message: string } {
  const e = error?.details?.errors;
  const fields = e && typeof e === "object" ? (e as Record<string, string>) : {};
  return { fields, message: error?.message ?? "Nicht gespeichert" };
}

// ── Excel-artige Bedienung: Spaltenbuchstaben, Einfügen aus der Zwischenablage, Tastatur ─────────────────────

/** Spaltenbuchstabe wie in Excel: 0 → A, 25 → Z, 26 → AA. */
export function columnLetter(index: number): string {
  let s = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}

/** Zwischenablage aus Excel/Sheets (Tabs und Zeilenumbrüche, Felder in Anführungszeichen) als Matrix. */
export function parseClipboard(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"' && cell === "") quoted = true;
    else if (ch === "\t") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += ch;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

/** Ist das ein Block aus mehreren Zellen (dann übernimmt das Raster das Einfügen)? */
export const isMultiCellPaste = (text: string): boolean => /[\t\n]/.test(text.replace(/[\r\n]+$/, ""));

/**
 * Ops für einen eingefügten Block ab Zelle (rowIndex, colIndex). Bestehende Zeilen werden aktualisiert,
 * überzählige Zeilen neu angehängt (nur mit `allowAdd`). Ungültige Werte werden übersprungen und gezählt.
 */
export function pasteOps(
  tableId: string, matrix: string[][], rows: TRow[], columns: Col[], rowIndex: number, colIndex: number,
  allowAdd: boolean, makeId: () => string,
): { ops: Op[]; skipped: number } {
  const ops: Op[] = [];
  let skipped = 0;
  let after = rows.at(-1)?.id;
  matrix.forEach((cells, i) => {
    const values: Record<string, Json> = {};
    cells.forEach((raw, j) => {
      const col = columns[colIndex + j];
      if (!col) return;
      const r = raw.trim() === "" ? { value: null } : parseInput(raw.trim(), col.type);
      if ("error" in r) skipped++;
      else values[col.id] = r.value;
    });
    const target = rows[rowIndex + i];
    if (target) {
      for (const [col, v] of Object.entries(values)) if ((target.values[col] ?? null) !== v) ops.push(updateCellOp(tableId, target.id, col, v));
    } else if (allowAdd) {
      const filled = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== null));
      if (!Object.keys(filled).length) return;
      const id = makeId();
      ops.push(insertRowOp(tableId, id, filled, after));
      after = id;
    }
  });
  return { ops, skipped };
}

/** Ziel einer Pfeil-/Enter-Taste im Raster, oder null, wenn die Taste dem Eingabefeld gehört. */
export function gridMove(
  key: string, shift: boolean, caret: { atStart: boolean; atEnd: boolean }, pos: { r: number; c: number }, size: { rows: number; cols: number },
): { r: number; c: number } | null {
  const clamp = (r: number, c: number) => ({ r: Math.max(0, Math.min(size.rows - 1, r)), c: Math.max(0, Math.min(size.cols - 1, c)) });
  switch (key) {
    case "ArrowUp": return clamp(pos.r - 1, pos.c);
    case "ArrowDown": return clamp(pos.r + 1, pos.c);
    case "Enter": return clamp(pos.r + (shift ? -1 : 1), pos.c);
    case "ArrowLeft": return caret.atStart ? clamp(pos.r, pos.c - 1) : null;
    case "ArrowRight": return caret.atEnd ? clamp(pos.r, pos.c + 1) : null;
    default: return null;
  }
}
