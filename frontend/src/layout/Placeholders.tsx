// Platzhalter-Seiten für Routen, deren Ansicht andere Tasks bauen (Routing selbst ist Task 2.1):
// Workflow → 4.x, Run → 4.6, Posteingang → 4.5. (Die Tabellen-Ansicht ist der Editor aus Task 3.1, src/tables.)
import { Link } from "react-router-dom";
import { Icon, type IconName } from "../ui/icons";
import { useInboxCounts } from "./AppShell";

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
