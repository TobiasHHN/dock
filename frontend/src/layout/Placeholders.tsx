// Platzhalter-Seiten für Routen, deren Ansicht andere Tasks bauen (Routing selbst ist Task 2.1):
// Tabelle → 3.1, Workflow → 4.x, Run → 4.6, Posteingang → 4.5. Die Tabelle zeigt bis dahin eine einfache,
// schreibgeschützte Live-Ansicht aus dem Kanal `table:<id>`.
import { Link, useParams } from "react-router-dom";
import { useChannel } from "../sync/store";
import { useInboxCounts } from "./AppShell";

export function TablePage() {
  const { id } = useParams();
  const ch = useChannel(`table:${id}`);
  const table = ch?.view?.tables?.[0];
  if (!ch || ch.status === "loading") return <p className="muted">Tabelle wird geladen …</p>;
  if (ch.status === "error") return <p className="error-text">Tabelle nicht verfügbar: {ch.error?.message}</p>;
  if (!table) return <p className="muted">Diese Tabelle wurde gelöscht. <Link to="/">Zur Übersicht</Link></p>;
  const columns = [...table.columns].sort((a: { position: string }, b: { position: string }) => (a.position < b.position ? -1 : 1));
  const rows = [...table.rows].sort((a: { position: string }, b: { position: string }) => (a.position < b.position ? -1 : 1));
  return (
    <>
      <h1>{table.title ?? table.name}</h1>
      <p className="small muted">Schreibgeschützte Vorschau, die bearbeitbare Tabellenansicht folgt mit Task 3.1.</p>
      <table className="simple">
        <thead>
          <tr>{columns.map((c: { id: string; name: string }) => <th key={c.id}>{c.name}</th>)}</tr>
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
    </>
  );
}

function Pending({ title, task }: { title: string; task: string }) {
  return (
    <>
      <h1>{title}</h1>
      <p className="muted">Diese Ansicht entsteht mit Task {task}.</p>
      <Link to="/">Zur Übersicht</Link>
    </>
  );
}

export const WorkflowPage = () => <Pending title="Workflow" task="4.6" />;
export const RunPage = () => <Pending title="Ablauf" task="4.6" />;

export function InboxTasksPage() {
  const counts = useInboxCounts();
  return <Pending title={`Aufgaben (${counts.tasks} offen)`} task="4.5" />;
}

export const InboxRequestsPage = () => <Pending title="Anfragen" task="4.5" />;
