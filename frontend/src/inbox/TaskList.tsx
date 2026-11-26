// „Meine Aufgaben“ (Task 4.5, L 5.9, T 5.7): Öffnen, Übernehmen (`task.claim`), Freigeben (`task.release`).
// Aktualisiert sich über den Kanal `user:<id>` live ohne Neuladen.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Op, TaskListItem } from "../api";
import { useAuth, workflowApi } from "../api/client";
import { BatchRejected, submit } from "../sync/store";
import { Icon, relativeTime } from "../ui/icons";
import { toast } from "../ui/toasts";
import { canClaimTask, canReleaseTask, formatDue, useChannelInvalidate } from "./inboxModel";

function useFreshIds(ids: string[] | undefined): Set<string> {
  const known = useRef<Set<string> | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!ids) return;
    if (known.current === null) {
      known.current = new Set(ids);
      return;
    }
    const added = ids.filter((id) => !known.current!.has(id));
    added.forEach((id) => known.current!.add(id));
    if (added.length > 0) {
      setFresh(new Set(added));
      const t = setTimeout(() => setFresh(new Set()), 2000);
      return () => clearTimeout(t);
    }
  }, [ids]);
  return fresh;
}

export function InboxTasksPage() {
  const me = useAuth((s) => s.user);
  const qc = useQueryClient();
  const [status, setStatus] = useState<"open" | "done">("open");
  const [busyId, setBusyId] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["tasks", status],
    queryFn: () => workflowApi.tasks({ status }),
    enabled: !!me,
  });

  useChannelInvalidate(me ? `user:${me.id}` : null, [["tasks"]]);

  const fresh = useFreshIds(data?.map((item) => item.task.id));

  async function act(item: TaskListItem, op: "task.claim" | "task.release") {
    if (busyId) return;
    setBusyId(item.task.id);
    try {
      await submit([{ op, task: item.task.id } as Op]);
      await qc.invalidateQueries({ queryKey: ["tasks"] });
      toast(op === "task.claim" ? `Aufgabe „${item.step_name}“ übernommen` : `Aufgabe „${item.step_name}“ freigegeben`);
    } catch (e) {
      const msg = e instanceof BatchRejected ? e.error.message : (e as Error).message;
      toast(`Aktion fehlgeschlagen: ${msg}`, "error");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Meine Aufgaben</h1>
          <p className="muted">Aufgaben, die dir oder deiner Rolle zugewiesen sind.</p>
        </div>
        <div className="segmented" role="tablist" aria-label="Aufgabenstatus">
          <button
            type="button"
            role="tab"
            aria-selected={status === "open"}
            className={status === "open" ? "active" : ""}
            onClick={() => setStatus("open")}
          >
            Offen
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={status === "done"}
            className={status === "done" ? "active" : ""}
            onClick={() => setStatus("done")}
          >
            Erledigt
          </button>
        </div>
      </div>

      {isError && (
        <p className="alert" role="alert">
          <Icon name="alert" />
          Aufgaben konnten nicht geladen werden: {(error as Error).message}
        </p>
      )}

      <section className="panel">
        {isLoading ? (
          <div className="skeleton-list" aria-label="Aufgaben werden geladen …">
            <span /><span /><span />
          </div>
        ) : !data || data.length === 0 ? (
          status === "open" ? (
            <p className="empty empty-done">
              <span className="empty-icon"><Icon name="check" size={18} strokeWidth={2.4} /></span>
              Alles erledigt, keine offenen Aufgaben.
            </p>
          ) : (
            <p className="empty">Noch keine erledigten Aufgaben.</p>
          )
        ) : (
          <ul className="inbox-list">
            {data.map((item) => {
              const t = item.task;
              const due = t.status === "open" ? formatDue(t.due_at) : null;
              const claimedByMe = !!t.claimed_by && t.claimed_by.id === me?.id;
              const claimable = canClaimTask(item);
              const releasable = canReleaseTask(t, me);
              const isBusy = busyId === t.id;

              return (
                <li key={t.id} className={`inbox-card ${fresh.has(t.id) ? "flash" : ""}`}>
                  <div className="inbox-card-main">
                    <div className="inbox-card-title-row">
                      <Link to={`/runs/${t.run_id}`} className="inbox-card-title">
                        {item.run_title}
                      </Link>
                      <span className="chip">{item.workflow_name}</span>
                      {due && (
                        <span className={`pill ${due.tone === "danger" ? "pill-danger" : due.tone === "warn" ? "pill-warn" : ""}`}>
                          {due.text}
                        </span>
                      )}
                      {t.claimed_by && (
                        <span className={`pill ${claimedByMe ? "pill-accent" : ""}`}>
                          {claimedByMe
                            ? "Von dir übernommen"
                            : `In Bearbeitung von ${item.claimed_by_name ?? t.claimed_by.name ?? t.claimed_by.id}`}
                        </span>
                      )}
                      {t.status === "done" && t.outcome && (
                        <span className="pill pill-success">{t.outcome}</span>
                      )}
                    </div>
                    <div className="inbox-card-meta muted small">
                      <span>Schritt: <strong>{item.step_name}</strong></span>
                      <span> · {relativeTime(t.completed_at ?? t.created_at) ?? "gerade eben"}</span>
                    </div>
                  </div>
                  <div className="inbox-actions">
                    {claimable && (
                      <button
                        type="button"
                        disabled={busyId !== null}
                        aria-busy={isBusy}
                        onClick={() => act(item, "task.claim")}
                      >
                        {isBusy && <span className="spinner" aria-hidden="true" />}
                        Übernehmen
                      </button>
                    )}
                    {releasable && (
                      <button
                        type="button"
                        disabled={busyId !== null}
                        aria-busy={isBusy}
                        onClick={() => act(item, "task.release")}
                      >
                        {isBusy && <span className="spinner" aria-hidden="true" />}
                        Freigeben
                      </button>
                    )}
                    <Link to={`/runs/${t.run_id}`} className="btn btn-primary">
                      Öffnen
                    </Link>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
