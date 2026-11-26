// Hinweis, dass Dock auch über einen KI-Assistenten (MCP) bedient werden kann: Erklärung und kopierbare Server-Adresse.
import { useEffect } from "react";
import { create } from "zustand";
import { Icon } from "../ui/icons";
import { toast } from "../ui/toasts";

const useMcpInfo = create<{ open: boolean }>(() => ({ open: false }));

export const openMcpInfo = () => useMcpInfo.setState({ open: true });
const close = () => useMcpInfo.setState({ open: false });

const mcpUrl = () => `${window.location.origin}/mcp`;

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast("In die Zwischenablage kopiert");
  } catch {
    toast("Kopieren nicht möglich, bitte markieren und von Hand kopieren", "error");
  }
}

export function McpInfoHost() {
  const open = useMcpInfo((s) => s.open);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;
  const url = mcpUrl();
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="modal mcp-info" role="dialog" aria-modal="true" aria-labelledby="mcp-title">
        <div className="modal-head">
          <h2 id="mcp-title">Mit einem KI-Assistenten arbeiten</h2>
          <button className="icon-button" onClick={close} aria-label="Schließen"><Icon name="close" size={16} /></button>
        </div>
        <p className="muted">
          Dock ist darauf ausgelegt, gemeinsam mit KI-Assistenten zu arbeiten, etwa beim Aufbau von Workflows, die ein
          Assistent für dich entwirft und anlegt. Verbinde dafür einen Assistenten wie Claude oder ChatGPT über{" "}
          <strong>MCP</strong>. Er erledigt Aufgaben für dich, mit genau deinen Rechten.
        </p>
        <ul className="mcp-list">
          <li><Icon name="file" size={16} />Dokumente, Tabellen und Abläufe anlegen und ändern</li>
          <li><Icon name="tasks" size={16} />Aufgaben ansehen, übernehmen und abschließen</li>
          <li><Icon name="inbox" size={16} />Den Stand deiner Vorgänge abfragen</li>
        </ul>
        <div className="mcp-url">
          <span className="mcp-url-label">Server-Adresse</span>
          <div className="mcp-url-row">
            <code>{url}</code>
            <button onClick={() => copy(url)}><Icon name="copy" />Kopieren</button>
          </div>
        </div>
        <p className="muted small">
          Zur Anmeldung braucht der Assistent ein persönliches Zugangs-Token (Header <code>Authorization: Bearer …</code>).
          Alles, was er ändert, erscheint im Verlauf als „Assistent im Auftrag von dir“.
        </p>
        <div className="modal-foot">
          <button className="primary" onClick={close}>Verstanden</button>
        </div>
      </div>
    </div>
  );
}
