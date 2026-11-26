// Tabellen-Editor (Task 3.1, F5, L 2, L 3.4): Spalten und Typen anlegen, Zeilen hinzufügen und löschen, Zellen sofort
// speichern, Filter und Sortierung, neue Zeilen kurz hervorheben. Alles Live über den Kanal `table:<id>`.
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { canEditStructure, useAuth } from "../api/client";
import { newId, submit } from "../sync/store";
import { useUsers } from "../ui/actors";
import { confirmDialog } from "../ui/confirm";
import { Icon } from "../ui/icons";
import { toast } from "../ui/toasts";
import { TableGrid, useNewRows, useTableData } from "./TableGrid";
import {
  CREATABLE_KINDS, type Col, type FilterRow, type NewColumnForm, OP_LABELS, type SortSpec, TYPE_LABELS, activeFilters,
  buildColumnAdd, findColumn, opsFor,
} from "./tableModel";

export function TableEditorPage() {
  const { id } = useParams();
  return <TableEditor tableId={id!} />;
}

export function TableEditor({ tableId }: { tableId: string }) {
  const me = useAuth((s) => s.user);
  const navigate = useNavigate();
  const users = useUsers();
  const [filterRows, setFilterRows] = useState<FilterRow[]>([]);
  const [sort, setSort] = useState<SortSpec[]>([]);
  const [panel, setPanel] = useState<"filter" | "column" | null>(null);
  const newRows = useNewRows(tableId);

  // Filter erst anwenden, wenn die Spalten bekannt sind; die Abfrage nutzt Spalten-IDs
  const first = useTableData(tableId, [], []);
  const conds = useMemo(() => activeFilters(filterRows, first.allColumns), [filterRows, first.allColumns]);
  const data = useTableData(tableId, conds, sort);
  const { table, columns, rows, query } = data;
  const mayStructure = canEditStructure(me);

  if (data.status === "loading") return <p className="muted" role="status">Tabelle wird geladen …</p>;
  if (data.status === "error")
    return <p className="alert" role="alert"><Icon name="alert" />Tabelle nicht verfügbar: {data.errorMessage}. <Link to="/">Zur Übersicht</Link></p>;
  if (!table)
    return (
      <div className="empty-state">
        <span className="empty-state-icon"><Icon name="table" size={22} /></span>
        <h1>Tabelle gelöscht</h1>
        <p className="muted">Diese Tabelle gibt es nicht mehr.</p>
        <Link to="/">Zur Übersicht</Link>
      </div>
    );

  const total = query.total ?? table.rows.length;
  const filtered = conds.length > 0;
  const sortDir = (col: Col) => sort.find((s) => findColumn(columns, s.column)?.id === col.id)?.dir;
  const cycleSort = (col: Col) => {
    const cur = sortDir(col);
    setSort(cur === undefined ? [{ column: col.id, dir: "asc" }] : cur === "asc" ? [{ column: col.id, dir: "desc" }] : []);
  };

  const deleteColumn = async (col: Col) => {
    const ok = await confirmDialog({
      title: `Spalte „${col.name}“ löschen?`, message: "Die Werte dieser Spalte gehen verloren.",
      confirmLabel: "Spalte löschen", danger: true,
    });
    if (!ok) return;
    submit([{ op: "column.delete", table: table.id, column: col.id } as never]).catch(() => undefined);
  };

  const deleteTable = async () => {
    const ok = await confirmDialog({
      title: `Tabelle „${table.name}“ löschen?`,
      message: `Die Tabelle und ${total === 1 ? "ihr Eintrag" : `alle ${total} Einträge`} werden entfernt. Wird sie noch verwendet, ist das Löschen nicht möglich.`,
      confirmLabel: "Tabelle löschen", danger: true,
    });
    if (!ok) return;
    try {
      await submit([{ op: "table.delete", table: table.id } as never]);
      toast(`Tabelle „${table.name}“ gelöscht`);
      navigate("/");
    } catch (err) {
      // z. B. IN_USE: Die Meldung nennt, wo die Tabelle noch verwendet wird
      const msg = (err as { error?: { message: string } })?.error?.message ?? (err as Error).message;
      toast(`Löschen nicht möglich: ${msg}`, "error");
    }
  };

  return (
    <>
      <nav className="breadcrumb" aria-label="Brotkrumen">
        <Link to="/">Tabellen</Link>
        <Icon name="chevronRight" size={14} />
        <span aria-current="page">{table.name}</span>
      </nav>
      <div className="page-head">
        <div>
          <h1>{table.name}</h1>
          <p className="muted" aria-live="polite">
            {filtered ? `${rows.length} von ${total} Einträgen` : `${rows.length} ${rows.length === 1 ? "Eintrag" : "Einträge"}`}
            {query.loading && " · lädt …"}
          </p>
        </div>
        <div className="actions">
          <button onClick={() => setPanel(panel === "filter" ? null : "filter")} aria-expanded={panel === "filter"}>
            Filter{filtered ? ` (${conds.length})` : ""}
          </button>
          {mayStructure && (
            <button onClick={() => setPanel(panel === "column" ? null : "column")} aria-expanded={panel === "column"}>
              <Icon name="plus" size={14} />Spalte
            </button>
          )}
          {mayStructure && (
            <button className="danger" onClick={deleteTable}>
              <Icon name="trash" size={14} />Tabelle löschen
            </button>
          )}
        </div>
      </div>

      {panel === "filter" && <FilterPanel columns={data.allColumns} rows={filterRows} onChange={setFilterRows} />}
      {panel === "column" && mayStructure && <ColumnForm table={table} onDone={() => setPanel(null)} />}
      {query.error && <p className="alert" role="alert"><Icon name="alert" />{query.error}</p>}

      <TableGrid
        tableId={table.id}
        columns={columns}
        allColumns={data.allColumns}
        rows={rows}
        users={users}
        editable
        allowAdd
        allowDelete
        newRows={newRows}
        headerExtra={(c) => (
          <span className="th-tools">
            <button
              className="ghost" title="Sortieren" aria-label={`Nach ${c.name} sortieren`}
              aria-pressed={sortDir(c) !== undefined} onClick={() => cycleSort(c)}
            >
              <Icon name={sortDir(c) === "desc" ? "arrowDown" : "arrowUp"} size={13} />
            </button>
            {mayStructure && (
              <button className="ghost danger" title="Spalte löschen" aria-label={`Spalte ${c.name} löschen`} onClick={() => deleteColumn(c)}>
                <Icon name="trash" size={13} />
              </button>
            )}
            <span className="chip">{TYPE_LABELS[c.type.kind] ?? c.type.kind}</span>
          </span>
        )}
      />
    </>
  );
}

// ── Filter ───────────────────────────────────────────────────────────────────

function FilterPanel({ columns, rows, onChange }: { columns: Col[]; rows: FilterRow[]; onChange: (r: FilterRow[]) => void }) {
  const set = (i: number, patch: Partial<FilterRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="panel filter-panel">
      {rows.length === 0 && <p className="muted small">Noch kein Filter. Mehrere Bedingungen gelten zusammen („und“).</p>}
      {rows.map((r, i) => {
        const col = findColumn(columns, r.column) ?? columns[0];
        const ops = col ? opsFor(col.type) : [];
        return (
          <div className="filter-row" key={i}>
            <select aria-label="Spalte" value={col?.id} onChange={(e) => {
              const c = columns.find((x) => x.id === e.target.value)!;
              set(i, { column: c.id, op: opsFor(c.type).includes(r.op) ? r.op : "eq", text: "" });
            }}>
              {columns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <select aria-label="Bedingung" value={r.op} onChange={(e) => set(i, { op: e.target.value as FilterRow["op"] })}>
              {ops.map((o) => <option key={o} value={o}>{OP_LABELS[o]}</option>)}
            </select>
            {r.op !== "is_null" && (
              <input
                aria-label="Wert" value={r.text} placeholder={r.op === "in" ? "a, b, c" : "Wert oder {{ Ausdruck }}"}
                onChange={(e) => set(i, { text: e.target.value })}
              />
            )}
            <button className="ghost danger" aria-label="Bedingung entfernen" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
              <Icon name="trash" size={14} />
            </button>
          </div>
        );
      })}
      <div className="actions">
        <button
          disabled={!columns.length}
          onClick={() => onChange([...rows, { column: columns[0].id, op: "eq", text: "" }])}
        >
          <Icon name="plus" size={14} />Bedingung
        </button>
        {rows.length > 0 && <button className="ghost" onClick={() => onChange([])}>Zurücksetzen</button>}
      </div>
    </div>
  );
}

// ── Neue Spalte ──────────────────────────────────────────────────────────────

function ColumnForm({ table, onDone }: { table: { id: string; columns: Col[] }; onDone: () => void }) {
  const [form, setForm] = useState<NewColumnForm>({ name: "", kind: "text", required: false, options: "", decimals: 2 });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    const r = buildColumnAdd(table, form, () => newId("col"));
    if ("errors" in r) return setErrors(r.errors);
    setErrors({});
    setBusy(true);
    try {
      await submit([r.op]);
      toast(`Spalte „${form.name.trim()}“ angelegt`);
      onDone();
    } catch (err) {
      const msg = (err as { error?: { message: string } })?.error?.message ?? (err as Error).message;
      setErrors({ name: msg });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="panel column-form" onSubmit={save} noValidate>
      <label>
        Name
        <input value={form.name} autoFocus aria-invalid={!!errors.name || undefined} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        {errors.name && <span className="error-text small" role="alert">{errors.name}</span>}
      </label>
      <label>
        Typ
        <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          {CREATABLE_KINDS.map((k) => <option key={k} value={k}>{TYPE_LABELS[k]}</option>)}
        </select>
      </label>
      {form.kind === "number" && (
        <label>
          Nachkommastellen
          <input type="number" min={0} max={10} value={form.decimals} onChange={(e) => setForm({ ...form, decimals: Number(e.target.value) })} />
        </label>
      )}
      {form.kind === "select" && (
        <label>
          Optionen (mit Komma getrennt)
          <input value={form.options} aria-invalid={!!errors.options || undefined} placeholder="Offen, Erledigt" onChange={(e) => setForm({ ...form, options: e.target.value })} />
          {errors.options && <span className="error-text small" role="alert">{errors.options}</span>}
        </label>
      )}
      <label className="check">
        <input type="checkbox" checked={form.required} onChange={(e) => setForm({ ...form, required: e.target.checked })} />
        Pflichtfeld
      </label>
      <div className="actions">
        <button type="submit" className="primary" disabled={busy} aria-busy={busy}>Spalte anlegen</button>
        <button type="button" className="ghost" onClick={onDone}>Abbrechen</button>
      </div>
    </form>
  );
}
