// Tabellen-Raster (Task 3.1, L 3.4): wird vom Tabellen-Editor und vom `table_view`-Block gemeinsam genutzt.
// Zellen speichern sofort über den Sync-Store (optimistisch, kein Speichern-Button), neue Zeilen blinken kurz.
import { useEffect, useMemo, useState } from "react";
import type { UserOut } from "../api/client";
import { sync, newId, submit, useChannel } from "../sync/store";
import type { Json } from "../sync/tableRules";
import { Icon } from "../ui/icons";
import { toast } from "../ui/toasts";
import {
  type Col, type FilterCond, type SortSpec, type TRow, deleteRowOp, displayValue, fieldErrors, inputText, insertRowOp,
  insertedRowIds, overlayRows, parseInput, sortRows, sortedColumns, sortedRows, updateCellOp,
} from "./tableModel";
import { type RowQuery, useRowQuery } from "./useRowQuery";

export type TableData = {
  ready: boolean;
  status: "loading" | "ready" | "error" | "gone";
  errorMessage?: string;
  table: Json | undefined;
  columns: Col[];
  /** Alle Spalten der Tabelle (auch wenn der Block nur einen Teil zeigt). */
  allColumns: Col[];
  rows: TRow[];
  query: RowQuery;
  seq: number | null;
};

/** Live-Zeilen einer Tabelle: ohne Filter lokal sortiert aus `view`, mit Filter vom Server (auf Live-Stand gelegt). */
export function useTableData(tableId: string | null, filter: FilterCond[], sort: SortSpec[], only?: string[]): TableData {
  const ch = useChannel(tableId ? `table:${tableId}` : null);
  const table = ch?.view?.tables?.[0];
  const allColumns = useMemo(() => sortedColumns(table?.columns ?? []), [table?.columns]);
  const columns = useMemo(() => {
    if (!only?.length) return allColumns;
    const picked = only.flatMap((ref) => allColumns.filter((c) => c.id === ref || c.key === ref));
    return picked.length ? picked : allColumns;
  }, [allColumns, only]);
  const query = useRowQuery(tableId, filter, sort, ch?.seq ?? null);
  const rows = useMemo(() => {
    const live = sortedRows(table?.rows ?? []);
    if (filter.length) return query.ids ? overlayRows(query.ids, live) : [];
    return sortRows(live, allColumns, sort);
  }, [table?.rows, allColumns, filter.length, sort, query.ids]);
  const status = !ch || ch.status === "loading" ? "loading" : ch.status === "error" ? "error" : table ? "ready" : "gone";
  return {
    ready: status === "ready", status, errorMessage: ch?.error?.message, table, columns, allColumns, rows, query, seq: ch?.seq ?? null,
  };
}

/** Zeilen, die gerade neu eingefügt wurden (von wem auch immer), für ca. 2 Sekunden. */
export function useNewRows(tableId: string | null): Set<string> {
  const [ids, setIds] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!tableId) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const off = sync.listen(`table:${tableId}`, (e) => {
      if (e.type !== "ops") return;
      const fresh = insertedRowIds(e.ops);
      if (!fresh.length) return;
      setIds((s) => new Set([...s, ...fresh]));
      timers.push(setTimeout(() => setIds((s) => new Set([...s].filter((x) => !fresh.includes(x)))), 2200));
    });
    return () => {
      off();
      timers.forEach(clearTimeout);
    };
  }, [tableId]);
  return ids;
}

// ── Eingabe einer Zelle ──────────────────────────────────────────────────────

type InputProps = {
  col: Col; value: Json; users: Record<string, UserOut>; disabled?: boolean; invalid?: boolean; label: string;
  onCommit: (value: Json) => void;
  /** Wenn gesetzt, wird beim Verlassen nichts gespeichert, sondern nur gemeldet (Zeile „Neu“). */
  onText?: (text: string) => void;
  onError: (message: string | null) => void;
};

/** Eingabe passend zum Spaltentyp. Text wird beim Verlassen oder mit Enter gespeichert, Auswahl und Haken sofort. */
export function CellInput({ col, value, users, disabled, invalid, label, onCommit, onText, onError }: InputProps) {
  const kind: string = col.type.kind;
  const shown = inputText(value, col.type);
  const [text, setText] = useState(shown);
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused) setText(shown);
  }, [shown, focused]);

  if (kind === "boolean")
    return (
      <input
        type="checkbox" aria-label={label} checked={value === true} disabled={disabled}
        onChange={(e) => onCommit(e.target.checked)}
      />
    );

  if (kind === "select" || kind === "user") {
    const options: { id: string; label: string }[] =
      kind === "select" ? col.type.options ?? [] : Object.values(users).map((u) => ({ id: u.id, label: u.name }));
    return (
      <select aria-label={label} className="cell-input" disabled={disabled} value={value ?? ""} aria-invalid={invalid || undefined}
        onChange={(e) => onCommit(e.target.value === "" ? null : e.target.value)}>
        <option value="">–</option>
        {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    );
  }

  const commit = () => {
    setFocused(false);
    if (onText) return onText(text);
    if (text === shown) return onError(null);
    const r = parseInput(text, col.type);
    if ("error" in r) return onError(r.error);
    onError(null);
    onCommit(r.value);
  };
  const htmlType = kind === "date" ? "date" : kind === "datetime" ? "datetime-local" : "text";
  return (
    <input
      className={`cell-input ${["integer", "number", "currency"].includes(kind) ? "num" : ""}`}
      type={htmlType}
      aria-label={label}
      aria-invalid={invalid || undefined}
      inputMode={kind === "integer" ? "numeric" : kind === "number" || kind === "currency" ? "decimal" : undefined}
      autoComplete="off"
      disabled={disabled}
      value={text}
      onFocus={() => setFocused(true)}
      onChange={(e) => {
        setText(e.target.value);
        if (onText) onText(e.target.value);
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") {
          setText(shown);
          onError(null);
          (e.target as HTMLInputElement).blur();
        }
      }}
    />
  );
}

function Cell({ table, row, col, users, editable }: { table: string; row: TRow; col: Col; users: Record<string, UserOut>; editable: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const value = row.values[col.id] ?? null;
  const save = (v: Json) => {
    if (v === value) return;
    submit([updateCellOp(table, row.id, col.id, v)]).catch((e) => setError(fieldErrors(e?.error).message));
  };
  if (!editable) return <td>{displayValue(value, col.type, users)}</td>;
  return (
    <td className={`cell ${error ? "cell-error" : ""}`} title={error ?? undefined}>
      <CellInput
        col={col} value={value} users={users} invalid={!!error}
        label={`${col.name}`}
        onCommit={(v) => {
          setError(null);
          save(v);
        }}
        onError={setError}
      />
      {error && <span className="cell-msg" role="alert">{error}</span>}
    </td>
  );
}

// ── Raster ───────────────────────────────────────────────────────────────────

type GridProps = {
  tableId: string;
  columns: Col[];
  allColumns: Col[];
  rows: TRow[];
  users: Record<string, UserOut>;
  editable: boolean;
  allowAdd: boolean;
  allowDelete: boolean;
  newRows: Set<string>;
  /** Zusätzlicher Inhalt in der Kopfzelle einer Spalte (Löschen, Sortieren). */
  headerExtra?: (col: Col) => React.ReactNode;
};

export function TableGrid({ tableId, columns, allColumns, rows, users, editable, allowAdd, allowDelete, newRows, headerExtra }: GridProps) {
  const actionsCol = editable && (allowAdd || allowDelete);
  return (
    <div className="table-wrap">
      <table className="simple grid">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.id} scope="col">
                <span className="th-inner">
                  <span>{c.name}{c.required ? <span className="req" title="Pflichtfeld"> *</span> : null}</span>
                  {headerExtra?.(c)}
                </span>
              </th>
            ))}
            {actionsCol && <th aria-label="Aktionen" className="col-actions" />}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className={newRows.has(r.id) ? "flash" : undefined}>
              {columns.map((c) => <Cell key={c.id} table={tableId} row={r} col={c} users={users} editable={editable} />)}
              {actionsCol && (
                <td className="col-actions">
                  {allowDelete && <button
                    className="ghost danger" title="Zeile löschen" aria-label="Zeile löschen"
                    onClick={() => submit([deleteRowOp(tableId, r.id)]).catch(() => undefined)}
                  >
                    <Icon name="trash" size={14} />
                  </button>}
                </td>
              )}
            </tr>
          ))}
          {allowAdd && editable && <NewRowLine tableId={tableId} columns={columns} allColumns={allColumns} users={users} lastRow={rows.at(-1)?.id} />}
        </tbody>
      </table>
      {rows.length === 0 && <p className="empty">Keine Zeilen.</p>}
    </div>
  );
}

/** Letzte Zeile: Werte eintragen, „Hinzufügen“ legt die Zeile an. Fehler stehen an der jeweiligen Spalte. */
function NewRowLine({ tableId, columns, allColumns, users, lastRow }: {
  tableId: string; columns: Col[]; allColumns: Col[]; users: Record<string, UserOut>; lastRow?: string;
}) {
  const [values, setValues] = useState<Record<string, string | Json>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const add = async () => {
    const out: Record<string, Json> = {};
    const local: Record<string, string> = {};
    for (const c of columns) {
      const raw = values[c.id];
      if (raw === undefined || raw === "") continue;
      const r = typeof raw === "string" ? parseInput(raw, c.type) : { value: raw };
      if ("error" in r) local[c.key] = r.error;
      else if (r.value !== null) out[c.id] = r.value;
    }
    const missing = allColumns.filter((c) => c.required && columns.includes(c) && out[c.id] === undefined && c.default == null);
    for (const c of missing) local[c.key] = `${c.name} ist ein Pflichtfeld und darf nicht leer sein`;
    if (Object.keys(local).length) return setErrors(local);
    setErrors({});
    setBusy(true);
    try {
      await submit([insertRowOp(tableId, newId("row"), out, lastRow)]);
      setValues({});
    } catch (e) {
      const { fields, message } = fieldErrors((e as { error?: { message: string; details?: Json } })?.error);
      setErrors(Object.keys(fields).length ? fields : { _: message });
      if (!Object.keys(fields).length) toast(`Zeile nicht hinzugefügt: ${message}`, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className="new-row">
      {columns.map((c) => (
        <td key={c.id} className={`cell ${errors[c.key] ? "cell-error" : ""}`}>
          <CellInput
            col={c} value={values[c.id] ?? null} users={users}
            label={`Neue Zeile: ${c.name}`} invalid={!!errors[c.key]}
            onCommit={(v) => setValues((s) => ({ ...s, [c.id]: v }))}
            onText={(t) => setValues((s) => ({ ...s, [c.id]: t }))}
            onError={() => undefined}
          />
          {errors[c.key] && <span className="cell-msg" role="alert">{errors[c.key]}</span>}
        </td>
      ))}
      <td className="col-actions">
        <button className="primary" onClick={add} disabled={busy} aria-busy={busy}>
          <Icon name="plus" size={14} />Hinzufügen
        </button>
      </td>
    </tr>
  );
}
