// `table_view` im Dokument (Task 3.1, L 3.4): zeigt eine vorhandene Tabelle, ohne eigene Daten. Filter, Sortierung,
// Spaltenauswahl und die Schalter editable / allow_add / allow_delete kommen aus den Block-Props. Änderungen an Zellen
// werden sofort gespeichert (kein Speichern-Button).
import { Link } from "react-router-dom";
import { useChannel } from "../../sync/store";
import { TableGrid, useNewRows, useTableData } from "../../tables/TableGrid";
import type { FilterCond, SortSpec } from "../../tables/tableModel";
import { useUsers } from "../../ui/actors";
import { Icon } from "../../ui/icons";
import type { FlatBlock } from "../blockOps";
import { BLOCK_COMPONENTS } from "./registry";

/** `props.table` darf ID oder Key sein; Keys löst der Workspace-Kanal auf. `loading`, solange dieser noch lädt. */
export function useTableId(ref: string | undefined): { id: string | null; loading: boolean } {
  const ws = useChannel("workspace");
  if (!ref) return { id: null, loading: false };
  if (ref.startsWith("tbl_")) return { id: ref, loading: false };
  const id = ws?.view?.tables?.find((t: { key: string; id: string }) => t.key === ref)?.id ?? null;
  return { id, loading: !id && (!ws || ws.status === "loading") };
}

const EMPTY: never[] = [];

export function TableView({ block }: { block: FlatBlock }) {
  const p = block.props;
  const { id: tableId, loading: resolving } = useTableId(p.table);
  const users = useUsers();
  const newRows = useNewRows(tableId);
  const data = useTableData(tableId, (p.filter ?? EMPTY) as FilterCond[], (p.sort ?? EMPTY) as SortSpec[], p.columns?.length ? p.columns : undefined);

  if (resolving) return <p className="muted" role="status">Tabelle wird geladen …</p>;
  if (!tableId || data.status === "gone")
    return <div className="placeholder-block"><b>Tabellenansicht</b> · Tabelle „{String(p.table ?? "")}“ nicht gefunden</div>;
  if (data.status === "loading") return <p className="muted" role="status">Tabelle wird geladen …</p>;
  if (data.status === "error") return <p className="alert" role="alert"><Icon name="alert" />Tabelle nicht verfügbar: {data.errorMessage}</p>;

  return (
    <div className="table-view">
      <div className="table-view-head">
        <Link to={`/tables/${tableId}`} className="table-view-title"><Icon name="table" size={14} />{data.table?.name}</Link>
        <span className="muted small">{data.rows.length} {data.rows.length === 1 ? "Eintrag" : "Einträge"}</span>
      </div>
      {data.query.error && <p className="alert" role="alert"><Icon name="alert" />{data.query.error}</p>}
      <TableGrid
        tableId={tableId}
        columns={data.columns}
        allColumns={data.allColumns}
        rows={data.rows}
        users={users}
        editable={!!p.editable}
        allowAdd={!!p.allow_add}
        allowDelete={!!p.allow_delete}
        newRows={newRows}
      />
    </div>
  );
}

BLOCK_COMPONENTS.table_view = TableView;
