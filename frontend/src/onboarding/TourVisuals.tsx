// Kleine Illustrationen für den Rundgang: nachgebaute Ausschnitte der echten Oberfläche.
import { Icon } from "../ui/icons";
import type { TourVisual } from "./tourModel";

export function Visual({ kind }: { kind: TourVisual }) {
  switch (kind) {
    case "welcome":
      return (
        <div className="tour-vis tour-vis-welcome">
          <span><Icon name="file" size={22} strokeWidth={1.6} /></span>
          <span><Icon name="table" size={22} strokeWidth={1.6} /></span>
          <span><Icon name="flow" size={22} strokeWidth={1.6} /></span>
        </div>
      );
    case "documents":
      return (
        <div className="tour-vis tour-mock-list">
          <div className="tour-mock-row"><Icon name="chevronRight" size={14} /><Icon name="flow" size={16} /><b>Bestellfreigabe</b><em>3 Dokumente</em></div>
          <div className="tour-mock-row child"><Icon name="file" size={16} /><span>Bestellung prüfen</span></div>
          <div className="tour-mock-row child"><Icon name="file" size={16} /><span>Freigabe Chef</span></div>
        </div>
      );
    case "tasks":
      return (
        <div className="tour-vis tour-mock-col">
          <div className="tour-mock-nav"><span>Zu erledigen</span><i className="badge">2</i></div>
          <div className="tour-mock-row"><Icon name="clock" size={16} /><span>Schritt „Prüfen“</span><em className="tour-pill">Übernehmen</em></div>
        </div>
      );
    case "requests":
      return (
        <div className="tour-vis tour-mock-col">
          <div className="tour-mock-steps"><i className="done" /><u className="done" /><i className="done" /><u /><i /></div>
          <div className="tour-mock-row"><span>Bestellung 4711</span><em className="tour-pill">In Prüfung · Anna</em></div>
        </div>
      );
    case "mcp":
      return (
        <div className="tour-vis tour-mock-col">
          <div className="tour-mock-bubble me">Lege eine Bestellung für 20 Monitore an</div>
          <div className="tour-mock-bubble ai"><Icon name="check" size={14} strokeWidth={2.4} />Erledigt, der Ablauf läuft</div>
        </div>
      );
    case "start":
      return (
        <div className="tour-vis tour-mock-col">
          <div className="tour-mock-title">Meine erste Bestellung<span className="tour-caret" /></div>
          <div className="tour-mock-line" /><div className="tour-mock-line short" />
        </div>
      );
    case "collab":
      return (
        <div className="tour-vis tour-mock-col">
          <div className="tour-mock-presence">
            <span className="tour-av a">AB</span><span className="tour-av b">BM</span><span className="tour-av agent">KI</span>
            <em>3 im Dokument</em>
          </div>
          <div className="tour-mock-block live"><span>Menge: 20 Monitore</span><i><b className="tour-av b">BM</b> schreibt …</i></div>
          <div className="tour-mock-block"><span>Lieferant: Beispiel GmbH</span><i className="agent">Assistent im Auftrag von Anna</i></div>
        </div>
      );
    case "sheets":
      return (
        <div className="tour-vis tour-mock-sheets">
          <span className="on"><Icon name="file" size={14} />Dokument</span>
          <span><Icon name="table" size={14} />Bestellungen</span>
          <span><Icon name="flow" size={14} />Freigabe</span>
          <span className="plus"><Icon name="plus" size={14} /></span>
        </div>
      );
    case "search":
      return (
        <div className="tour-vis tour-mock-search">
          <div className="tour-mock-field"><Icon name="search" size={16} /><span>Bestellung</span></div>
          <span className="tour-mock-bell"><Icon name="bell" size={18} /><i /></span>
        </div>
      );
  }
}
