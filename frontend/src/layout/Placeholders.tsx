// Platzhalter-Seiten für Routen, deren Ansicht andere Tasks bauen (Routing selbst ist Task 2.1):
// Tabelle → 3.1, Workflow → 4.x, Run → 4.6, Posteingang → 4.5. Die Tabelle zeigt bis dahin eine einfache,
// schreibgeschützte Live-Ansicht aus dem Kanal `table:<id>`.
import { Link, useParams } from "react-router-dom";
import { useChannel } from "../sync/store";
import { Icon, type IconName } from "../ui/icons";
import { useInboxCounts } from "./AppShell";

export function TablePage() {
  const { id } = useParams();
  const ch = useChannel(`table:${id}`);
  const table = ch?.view?.tables?.[0];
  if (!ch || ch.status === "loading") return <p className="muted" role="status">Tabelle wird geladen …</p>;
  if (ch.status === "error")
    return <p className="alert" role="alert"><Icon name="alert" />Tabelle nicht verfügbar: {ch.error?.message}. <Link to="/">Zur Übersicht</Link></p>;
  if (!table) return <Pending icon="table" title="Tabelle gelöscht" text="Diese Tabelle gibt es nicht mehr." />;
  const columns = [...table.columns].sort((a: { position: string }, b: { position: string }) => (a.position < b.position ? -1 : 1));
  const rows = [...table.rows].sort((a: { position: string }, b: { position: string }) => (a.position < b.position ? -1 : 1));
  return (
    <>
      <nav className="breadcrumb" aria-label="Brotkrumen">
        <Link to="/">Tabellen</Link>
        <Icon name="chevronRight" size={14} />
        <span aria-current="page">{table.title ?? table.name}</span>
      </nav>
      <div className="page-head">
        <div>
          <h1>{table.title ?? table.name}</h1>
          <p className="muted">
            {rows.length} {rows.length === 1 ? "Eintrag" : "Einträge"} · schreibgeschützte Vorschau, der Editor folgt mit Task 3.1
          </p>
        </div>
      </div>
      <div className="table-wrap">
      <table className="simple">
        <thead>
          <tr>{columns.map((c: { id: string; name: string }) => <th key={c.id} scope="col">{c.name}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r: { id: string; values: Record<string, unknown> }) => (
            <tr key={r.id}>
              {columns.map((c: { id: string; key: string }) => {
                const v = r.values?.[c.key] ?? r.values?.[c.id];
                return <td key={c.id}>{v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {rows.length === 0 && <p className="empty">Noch keine Zeilen.</p>}
    </>
  );
}

function Pending({ icon, title, text }: { icon: IconName; title: string; text: string }) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon"><Icon name={icon} size={22} /></span>
      <h1>{title}</h1>
      <p className="muted">{text}</p>
      <Link to="/">Zur Übersicht</Link>
    </div>
  );
}

export const WorkflowPage = () => <Pending icon="flow" title="Workflow" text="Diese Ansicht entsteht mit Task 4.6." />;
export const RunPage = () => <Pending icon="flow" title="Ablauf" text="Diese Ansicht entsteht mit Task 4.6." />;

export function InboxTasksPage() {
  const counts = useInboxCounts();
  return (
    <Pending
      icon="tasks"
      title={`Aufgaben (${counts.tasks} offen)`}
      text="Die Aufgabenliste mit Öffnen, Übernehmen und Freigeben entsteht mit Task 4.5."
    />
  );
}

export const InboxRequestsPage = () => (
  <Pending icon="inbox" title="Meine Anträge" text="Die Übersicht deiner Anträge entsteht mit Task 4.5." />
);
