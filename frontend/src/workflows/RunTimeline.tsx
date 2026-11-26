// Chronologischer Verlauf eines Runs mit Akteur-Kennzeichnung („Agent im Auftrag von …“) und Kommentarfeld (Task 4.6, L 5.8, L 5.10).
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Op, RunStatusView } from "../api";
import { BatchRejected, submit } from "../sync/store";
import { useUsers } from "../ui/actors";
import { Icon, relativeTime } from "../ui/icons";
import { toast } from "../ui/toasts";
import { formatRunEvent } from "./layout";

export function RunTimeline({
  runId,
  events,
}: {
  runId: string;
  events: RunStatusView["events"];
}) {
  const users = useUsers();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function sendComment(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await submit([{ op: "run.comment", run: runId, text: trimmed } as Op]);
      setText("");
      await qc.invalidateQueries({ queryKey: ["run", runId] });
    } catch (err) {
      const msg = err instanceof BatchRejected ? err.error.message : (err as Error).message;
      toast(`Kommentar fehlgeschlagen: ${msg}`, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="run-timeline" aria-labelledby="timeline-heading">
      <h2 id="timeline-heading" className="timeline-heading">Verlauf</h2>

      {events.length === 0 ? (
        <p className="timeline-empty">Noch keine Ereignisse.</p>
      ) : (
        <ol className="timeline-list">
          {events.map((ev) => (
            <li key={ev.id} className={`timeline-item timeline-${ev.type}`}>
              <span className="timeline-dot" aria-hidden="true" />
              <div className="timeline-body">
                <span className="timeline-desc">{formatRunEvent(ev, users)}</span>
                {ev.text && <p className="timeline-comment">{ev.text}</p>}
              </div>
              <time className="timeline-time" dateTime={ev.at} title={new Date(ev.at).toLocaleString("de-DE")}>
                {relativeTime(ev.at) ?? "gerade eben"}
              </time>
            </li>
          ))}
        </ol>
      )}

      <form className="timeline-form" onSubmit={sendComment}>
        <input
          type="text"
          aria-label="Kommentar hinzufügen"
          placeholder="Kommentieren …"
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
        />
        {text.trim() && (
          <button type="submit" className="timeline-send" disabled={busy} aria-label="Kommentar senden" title="Senden (Enter)">
            <Icon name="arrowUp" size={14} />
          </button>
        )}
      </form>
    </section>
  );
}
