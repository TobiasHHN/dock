// Tabellenregeln (L 2.2): Typumwandlung, Pflicht/Unique/Min/Max, on_delete.
// TypeScript-Spiegel von backend/app/domain/tables.py. Meldungen und Fehlerpfade wie dort, damit
// spec/fixtures in pytest und vitest gleich ausgehen. Weicht etwas ab, gewinnt der Server (T 5.3).

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Json = any;
export type ColumnTypeDict = { kind: string; [k: string]: Json };

export class DomainError extends Error {
  constructor(
    public code: string,
    message: string,
    public fields: Record<string, string> = {},
    public details: Record<string, Json> = {},
  ) {
    super(message);
  }
}

export function validationError(fields: Record<string, string>, subject = "Die Eingabe"): DomainError {
  return new DomainError("VALIDATION", `${subject} ist ungültig: ` + Object.values(fields).join("; "), fields);
}

const KEY_PREFIXES: Record<string, string> = { table: "tbl_", column: "col_" };
const fmt = (v: Json) => `„${v}“`;

/** Spaltentyp mit Standardwerten (wie das Pydantic-Schema `ColumnType`). */
export function typeDict(t: Json): ColumnTypeDict {
  const out: ColumnTypeDict = { ...t };
  switch (t.kind) {
    case "integer":
      out.min = t.min ?? null;
      out.max = t.max ?? null;
      break;
    case "number":
      out.decimals = t.decimals ?? 2;
      break;
    case "currency":
      out.currency = t.currency ?? "EUR";
      break;
    case "reference":
      out.on_delete = t.on_delete ?? "restrict";
      break;
  }
  return out;
}

const TRUE = new Set(["true", "ja", "j", "yes", "y", "1", "wahr", "x", "an"]);
const FALSE = new Set(["false", "nein", "n", "no", "0", "falsch", "aus"]);
const CURRENCY_WORDS = /\b(eur|usd|chf|gbp)\b|[€$£]/gi;

/** Zahlen in deutscher und englischer Schreibweise (siehe parse_decimal im Backend). */
export function parseDecimal(value: Json): number | null {
  if (typeof value === "boolean") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  let s = value.replace(CURRENCY_WORDS, "").replace(/[  ']/g, "");
  if (!s) return null;
  const comma = (s.match(/,/g) ?? []).length;
  const dot = (s.match(/\./g) ?? []).length;
  if (comma && dot) {
    const dec = s.lastIndexOf(",") > s.lastIndexOf(".") ? "," : ".";
    const thousands = dec === "," ? "." : ",";
    s = s.split(thousands).join("").replace(dec, ".");
  } else if (comma) {
    s = comma > 1 ? s.split(",").join("") : s.replace(",", ".");
  } else if (dot > 1) {
    s = s.split(".").join("");
  } else if (dot === 1 && /^[+-]?[1-9]\d{0,2}\.\d{3}$/.test(s)) {
    s = s.replace(".", "");
  }
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(s)) return null;
  return Number(s);
}

function quantize(n: number, decimals: number): number {
  const f = 10 ** decimals;
  return Math.sign(n) * Math.round(Math.abs(n) * f + 1e-9) / f;
}

const pad = (n: number, w = 2) => String(n).padStart(w, "0");

function validDate(y: number, m: number, d: number): boolean {
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

function parseDate(value: Json): string | null {
  if (typeof value !== "string") return null;
  const s = value.trim();
  let m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(s);
  if (m) return validDate(+m[3], +m[2], +m[1]) ? `${m[3]}-${pad(+m[2])}-${pad(+m[1])}` : null;
  m = /^(\d{4})-(\d{2})-(\d{2})([T ].*)?$/.exec(s);
  if (m) return validDate(+m[1], +m[2], +m[3]) ? `${m[1]}-${m[2]}-${m[3]}` : null;
  return null;
}

function parseDatetime(value: Json): string | null {
  if (typeof value !== "string") return null;
  const s = value.trim();
  const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/.exec(s);
  if (m) {
    if (!validDate(+m[3], +m[2], +m[1])) return null;
    return `${m[3]}-${pad(+m[2])}-${pad(+m[1])}T${pad(+(m[4] ?? 0))}:${pad(+(m[5] ?? 0))}:${pad(+(m[6] ?? 0))}`;
  }
  if (/^\d{4}-\d{2}-\d{2}([T ]|$)/.test(s)) {
    const d = parseDate(s.slice(0, 10));
    if (!d) return null;
    const rest = s.slice(11);
    if (!rest) return `${d}T00:00:00`;
    const t = /^(\d{2}):(\d{2})(?::(\d{2}))?(.*)$/.exec(rest);
    return t ? `${d}T${t[1]}:${t[2]}:${t[3] ?? "00"}${t[4]}` : null;
  }
  return null;
}

/** Wandelt in den Spaltentyp um. Wirft Error mit Meldung pro Feld (wie ValueError im Backend). */
export function coerceValue(value: Json, type: Json): Json {
  const t = typeDict(type);
  const kind = t.kind;
  const textKind = kind === "text" || kind === "long_text";
  if (value === null || value === undefined || (typeof value === "string" && !value.trim() && !textKind)) return null;
  if (textKind) {
    if (typeof value === "boolean") return value ? "ja" : "nein";
    if (typeof value === "number") return String(value);
    if (typeof value === "string") return value;
    throw new Error(`${fmt(value)} ist kein Text`);
  }
  if (kind === "integer") {
    const d = parseDecimal(value);
    if (d === null) throw new Error(`${fmt(value)} ist keine ganze Zahl`);
    if (!Number.isInteger(d)) throw new Error(`${fmt(value)} ist keine ganze Zahl (Nachkommastellen sind nicht erlaubt)`);
    if (t.min !== null && t.min !== undefined && d < t.min) throw new Error(`${d} ist zu klein, erlaubt ist mindestens ${t.min}`);
    if (t.max !== null && t.max !== undefined && d > t.max) throw new Error(`${d} ist zu groß, erlaubt ist höchstens ${t.max}`);
    return d;
  }
  if (kind === "number" || kind === "currency") {
    const d = parseDecimal(value);
    if (d === null) throw new Error(`${fmt(value)} ist ${kind === "currency" ? "kein gültiger Betrag" : "keine gültige Zahl"}`);
    return quantize(d, kind === "currency" ? 2 : Number(t.decimals ?? 2));
  }
  if (kind === "boolean") {
    if (typeof value === "boolean") return value;
    if (value === 0 || value === 1) return Boolean(value);
    if (typeof value === "string") {
      const s = value.trim().toLowerCase();
      if (TRUE.has(s)) return true;
      if (FALSE.has(s)) return false;
    }
    throw new Error(`${fmt(value)} ist weder ja noch nein`);
  }
  if (kind === "date") {
    const d = parseDate(value);
    if (!d) throw new Error(`${fmt(value)} ist kein gültiges Datum (erwartet JJJJ-MM-TT oder TT.MM.JJJJ)`);
    return d;
  }
  if (kind === "datetime") {
    const d = parseDatetime(value);
    if (!d) throw new Error(`${fmt(value)} ist keine gültige Zeitangabe (erwartet z. B. 2026-03-01T14:30)`);
    return d;
  }
  if (kind === "select") {
    const options: { id: string; label: string }[] = t.options ?? [];
    if (typeof value === "string") {
      const s = value.trim();
      const byId = options.find((o) => o.id === s);
      if (byId) return byId.id;
      const byLabel = options.find((o) => o.label.toLowerCase() === s.toLowerCase());
      if (byLabel) return byLabel.id;
    }
    throw new Error(`${fmt(value)} ist keine gültige Auswahl (erlaubt: ${options.map((o) => o.label).join(", ")})`);
  }
  if (kind === "user") {
    if (typeof value === "string" && value.startsWith("usr_") && value.length > 4) return value;
    throw new Error(`${fmt(value)} ist keine gültige Nutzer-ID`);
  }
  if (kind === "reference") {
    if (typeof value === "string" && value.trim()) return value.trim();
    throw new Error(`${fmt(value)} ist kein gültiger Verweis auf eine Zeile`);
  }
  throw new Error(`Unbekannter Spaltentyp '${kind}'`);
}

export function checkKey(kind: "table" | "column", key: string): string | null {
  const label = kind === "table" ? "Tabellen" : "Spalten";
  if (!key || key !== key.trim() || /[\s.]/.test(key))
    return `Der ${label}-Key ${fmt(key)} darf nicht leer sein und keine Leerzeichen oder Punkte enthalten`;
  if (key.startsWith(KEY_PREFIXES[kind]))
    return `Der ${label}-Key ${fmt(key)} darf nicht mit ${fmt(KEY_PREFIXES[kind])} beginnen (das Präfix ist für IDs reserviert)`;
  return null;
}

export function resolveDefault(def: Json, type: Json, userId: string | null = null): Json {
  if (def === null || def === undefined) return null;
  const t = typeDict(type);
  if (typeof def === "string" && def.trim().startsWith("{{")) {
    const expr = def.trim();
    if (expr === "{{now}}") {
      const now = new Date().toISOString();
      if (t.kind === "date") return now.slice(0, 10);
      if (["datetime", "text", "long_text"].includes(t.kind)) return now;
      throw new Error("{{now}} passt nur zu Datum, Zeitpunkt oder Text");
    }
    if (expr === "{{user.id}}") {
      if (!["user", "text"].includes(t.kind)) throw new Error("{{user.id}} passt nur zu Nutzer oder Text");
      return userId;
    }
    throw new Error(`Unbekannter Ausdruck ${fmt(expr)} (erlaubt: {{now}}, {{user.id}})`);
  }
  return coerceValue(def, t);
}

export function checkColumnDefinition(column: Json, prefix = ""): Record<string, string> {
  const errors: Record<string, string> = {};
  const keyMsg = checkKey("column", column.key);
  if (keyMsg) errors[`${prefix}key`] = keyMsg;
  if (!String(column.name ?? "").trim()) errors[`${prefix}name`] = "Der Spaltenname darf nicht leer sein";
  const t = typeDict(column.type);
  if (t.kind === "select") {
    const opts: { id: string; label: string }[] = t.options ?? [];
    const ids = opts.map((o) => o.id);
    if (!ids.length) errors[`${prefix}type`] = "Eine Auswahl-Spalte braucht mindestens eine Option";
    else if (new Set(ids).size !== ids.length || new Set(opts.map((o) => o.label.toLowerCase())).size !== ids.length)
      errors[`${prefix}type`] = "Die Optionen einer Auswahl-Spalte müssen eindeutige IDs und Namen haben";
  }
  if (t.kind === "integer" && t.min != null && t.max != null && t.min > t.max)
    errors[`${prefix}type`] = `Min (${t.min}) darf nicht größer sein als Max (${t.max})`;
  if (t.kind === "number" && !(t.decimals >= 0 && t.decimals <= 10))
    errors[`${prefix}type`] = "Die Nachkommastellen müssen zwischen 0 und 10 liegen";
  if (column.default != null && !(`${prefix}type` in errors)) {
    try {
      resolveDefault(column.default, t);
    } catch (e) {
      errors[`${prefix}default`] = `Standardwert: ${(e as Error).message}`;
    }
  }
  return errors;
}

const blank = (v: Json) => v === null || v === undefined || v === "";

/** Zeilenwerte (Schlüssel = Spalten-ID) umwandeln und Pflichtfelder prüfen (prepare_values im Backend). */
export function prepareValues(
  columns: Json[],
  values: Record<string, Json>,
  { insert, subject = "Die Zeile" }: { insert: boolean; subject?: string },
): Record<string, Json> {
  const byId = new Map(columns.map((c) => [c.id, c]));
  const errors: Record<string, string> = {};
  let out: Record<string, Json> = {};
  for (const [colId, raw] of Object.entries(values)) {
    const col = byId.get(colId);
    if (!col) {
      errors[colId] = `Unbekannte Spalte ${fmt(colId)}`;
      continue;
    }
    try {
      out[colId] = coerceValue(raw, col.type);
    } catch (e) {
      errors[col.key] = `${col.name}: ${(e as Error).message}`;
    }
  }
  if (insert) {
    for (const col of columns) {
      if (col.id in values) continue;
      let def: Json = null;
      try {
        def = resolveDefault(col.default, col.type);
      } catch {
        def = null;
      }
      if (def !== null && def !== undefined) out[col.id] = def;
    }
  }
  for (const col of columns) {
    if (!col.required || col.key in errors) continue;
    if ((insert || col.id in values) && blank(out[col.id]))
      errors[col.key] = `${col.name} ist ein Pflichtfeld und darf nicht leer sein`;
  }
  if (Object.keys(errors).length) throw validationError(errors, subject);
  if (insert) out = Object.fromEntries(Object.entries(out).filter(([, v]) => v !== null && v !== undefined));
  return out;
}

export function convertValues(values: Record<string, Json>, newType: Json): [Record<string, Json>, Record<string, string>] {
  const converted: Record<string, Json> = {};
  const lost: Record<string, string> = {};
  for (const [rowId, value] of Object.entries(values)) {
    if (value === null || value === undefined) continue;
    try {
      converted[rowId] = coerceValue(value, newType);
    } catch (e) {
      converted[rowId] = null;
      lost[rowId] = (e as Error).message;
    }
  }
  return [converted, lost];
}

export function findDuplicates(values: Record<string, Json>): Record<string, string[]> {
  const seen: Record<string, string[]> = {};
  for (const [rowId, value] of Object.entries(values)) {
    if (value === null || value === undefined) continue;
    (seen[String(value)] ??= []).push(rowId);
  }
  return Object.fromEntries(Object.entries(seen).filter(([, ids]) => ids.length > 1));
}

const SOURCE_LABELS: Record<string, string> = {
  "block/table_view": "Ansicht", "block/field.column": "Formularfeld", "block/filter": "Filter",
  "block/action.table": "Formular", "block/action.value": "Formular",
  "column/reference_column": "Referenzspalte", "row/reference_column": "Zeile",
};

export function describeUsages(usages: Json[]): string {
  return usages
    .map((u) => {
      const label = SOURCE_LABELS[`${u.source_kind}/${u.via}`] ?? u.source_kind[0].toUpperCase() + u.source_kind.slice(1);
      return `${label} ${u.source_id} (${u.via})`;
    })
    .join(", ");
}

export function inUseError(subject: string, usages: Json[]): DomainError {
  return new DomainError(
    "IN_USE",
    `${subject} wird noch verwendet von: ${describeUsages(usages)}. Entferne zuerst diese Verwendungen.`,
    {},
    { usages },
  );
}
