// Platzhalter-Seiten für Routen, deren Ansicht Task 4.6 baut.
import { Link } from "react-router-dom";
import { Icon, type IconName } from "../ui/icons";

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
