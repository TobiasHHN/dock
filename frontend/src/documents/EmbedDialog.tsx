// Dialog „Tabelle einbetten“ / „Workflow einbetten“ (Task 3.F5, B5). Liefert über `onInsert` einen fertigen Block;
// das Einfügen selbst übernimmt die Dokument-Ansicht. Weitere Einbettungs-Typen bekommen einen eigenen Zweig.
import { useEffect, useState } from "react";
import { newId, submit, useChannel } from "../sync/store";
import { FilterPanel } from "../tables/TableEditor";
import { useTableData } from "../tables/TableGrid";
import { type FilterRow, type SortSpec, sortedColumns } from "../tables/tableModel";
import { Icon } from "../ui/icons";
import { toast } from "../ui/toasts";
import type { NewBlock } from "./blockOps";
import { type EmbedKind, buildTableViewProps, newTableOp, tableViewBlock, workflowBlock } from "./embedModel";

type Named = { id: string; key: string; name?: string; title?: string };
const label = (x: Named) => x.name ?? x.title ?? x.key;

export function EmbedDialog({ kind, onInsert, onClose }: { kind: EmbedKind; onInsert: (b: NewBlock) => void; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal embed-dialog" role="dialog" aria-modal="true" aria-labelledby="embed-title">
        {kind === "table_view" ? <TablePicker onInsert={onInsert} onClose={onClose} /> : <WorkflowPicker onInsert={onInsert} onClose={onClose} />}
      </div>
    </div>
  );
}

function Head({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <div className="modal-head">
      <h2 id="embed-title">{title}</h2>
      <button className="ghost" onClick={onClose} aria-label="Schließen"><Icon name="close" size={16} /></button>
    </div>
  );
}

function WorkflowPicker({ onInsert, onClose }: { onInsert: (b: NewBlock) => void; onClose: () => void }) {
  const ws = useChannel("workspace");
  const workflows = (ws?.view?.workflows ?? []) as Named[];
  return (
    <>
      <Head title="Workflow einbetten" onClose={onClose} />
      {workflows.length === 0 ? (
        <p className="muted">Es gibt noch keine Workflows.</p>
      ) : (
        <ul className="embed-list">
          {workflows.map((w) => (
            <li key={w.id}>
              <button className="ghost" onClick={() => onInsert(workflowBlock(newId("blk"), w.id))}>
                <Icon name="flow" size={14} />{label(w)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function TablePicker({ onInsert, onClose }: { onInsert: (b: NewBlock) => void; onClose: () => void }) {
  const ws = useChannel("workspace");
  const tables = (ws?.view?.tables ?? []) as Named[];
  const [tableId, setTableId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);

  const createTable = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    try {
      const id = newId("tbl");
      await submit([newTableOp(id, name, tables.map((t) => t.key), newId("col"))]);
      setTableId(id);
    } catch (err) {
      const msg = (err as { error?: { message: string } })?.error?.message ?? (err as Error).message;
      toast(`Tabelle nicht angelegt: ${msg}`, "error");
    } finally {
      setBusy(false);
    }
  };

  if (tableId) return <TableConfig tableId={tableId} name={label(tables.find((t) => t.id === tableId) ?? { id: tableId, key: tableId })} onBack={() => setTableId(null)} onInsert={onInsert} onClose={onClose} />;

  return (
    <>
      <Head title="Tabelle einbetten" onClose={onClose} />
      <h3 className="embed-sub">Bestehende Tabelle</h3>
      {tables.length === 0 ? (
        <p className="muted small">Es gibt noch keine Tabellen.</p>
      ) : (
        <ul className="embed-list">
          {tables.map((t) => (
            <li key={t.id}>
              <button className="ghost" onClick={() => setTableId(t.id)}><Icon name="table" size={14} />{label(t)}</button>
            </li>
          ))}
        </ul>
      )}
      <h3 className="embed-sub">Neue Tabelle</h3>
      <form className="embed-new" onSubmit={createTable}>
        <input aria-label="Name der neuen Tabelle" placeholder="Name, z. B. Lieferanten" value={newName} onChange={(e) => setNewName(e.target.value)} />
        <button type="submit" disabled={busy || !newName.trim()} aria-busy={busy}><Icon name="plus" size={14} />Anlegen</button>
      </form>
    </>
  );
}

function TableConfig({ tableId, name, onBack, onInsert, onClose }: {
  tableId: string; name: string; onBack: () => void; onInsert: (b: NewBlock) => void; onClose: () => void;
}) {
  const data = useTableData(tableId, [], []);
  const columns = sortedColumns(data.allColumns);
  const [hidden, setHidden] = useState<string[]>([]);
  const [filterRows, setFilterRows] = useState<FilterRow[]>([]);
  const [sort, setSort] = useState<SortSpec | null>(null);
  const [editable, setEditable] = useState(false);
  const [allowAdd, setAllowAdd] = useState(false);
  const [allowDelete, setAllowDelete] = useState(false);

  const toggle = (id: string) => setHidden(hidden.includes(id) ? hidden.filter((h) => h !== id) : [...hidden, id]);
  const insert = () =>
    onInsert(tableViewBlock(newId("blk"), buildTableViewProps({
      table: tableId, allColumns: columns, selected: columns.map((c) => c.id).filter((id) => !hidden.includes(id)),
      filterRows, sort: sort ? [sort] : [], editable, allowAdd, allowDelete,
    })));

  return (
    <>
      <Head title={`Tabelle „${name}“ einbetten`} onClose={onClose} />
      {!data.ready ? (
        <p className="muted" role="status">Spalten werden geladen …</p>
      ) : (
        <>
          <fieldset className="embed-group">
            <legend>Spalten</legend>
            <div className="embed-cols">
              {columns.map((c) => (
                <label className="check" key={c.id}>
                  <input type="checkbox" checked={!hidden.includes(c.id)} onChange={() => toggle(c.id)} />{c.name}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="embed-group">
            <legend>Filter</legend>
            <FilterPanel columns={columns} rows={filterRows} onChange={setFilterRows} />
          </fieldset>
          <fieldset className="embed-group">
            <legend>Sortierung</legend>
            <div className="filter-row">
              <select aria-label="Sortieren nach" value={sort?.column ?? ""} onChange={(e) => setSort(e.target.value ? { column: e.target.value, dir: sort?.dir ?? "asc" } : null)}>
                <option value="">Keine</option>
                {columns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              {sort && (
                <select aria-label="Richtung" value={sort.dir} onChange={(e) => setSort({ ...sort, dir: e.target.value as SortSpec["dir"] })}>
                  <option value="asc">aufsteigend</option>
                  <option value="desc">absteigend</option>
                </select>
              )}
            </div>
          </fieldset>
          <fieldset className="embed-group">
            <legend>Bearbeitung im Dokument</legend>
            <label className="check"><input type="checkbox" checked={editable} onChange={(e) => setEditable(e.target.checked)} />Zellen bearbeitbar</label>
            <label className="check"><input type="checkbox" disabled={!editable} checked={allowAdd} onChange={(e) => setAllowAdd(e.target.checked)} />Zeilen hinzufügen erlauben</label>
            <label className="check"><input type="checkbox" disabled={!editable} checked={allowDelete} onChange={(e) => setAllowDelete(e.target.checked)} />Zeilen löschen erlauben</label>
          </fieldset>
        </>
      )}
      <div className="modal-foot">
        <button onClick={onBack}>Zurück</button>
        <button className="primary" disabled={!data.ready} onClick={insert}>Einbetten</button>
      </div>
    </>
  );
}
