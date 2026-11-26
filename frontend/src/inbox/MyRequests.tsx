// „Meine Anträge“ (Task 4.5, L 5.10): gestartete bzw. sichtbare Runs mit Status, aktuellem Schritt und Zuständigen.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth, workflowApi } from "../api/client";
import { Icon, relativeTime } from "../ui/icons";
import { formatCandidates, runStatusLabel, useChannelInvalidate } from "./inboxModel";

type ScopeFilter = "me" | "any";
type StatusFilter = "all" | "active" | "completed" | "cancelled";

export function InboxRequestsPage() {
  const me = useAuth((s) => s.user);
  const [scope, setScope] = useState<ScopeFilter>("me");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["runs", scope, statusFilter],
    queryFn: () =>
      workflowApi.runs({
        started_by: scope,
        ...(statusFilter !== "all" ? { status: statusFilter } : {}),
      }),
    enabled: !!me,
  });

  useChannelInvalidate(me ? `user:${me.id}` : null, [["runs"]]);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Meine Anträge</h1>
          <p className="muted">Laufende und abgeschlossene Abläufe im Überblick.</p>
        </div>
        <div className="inbox-filters">
          <div className="segmented" role="tablist" aria-label="Sichtbarkeit">
            <button
              type="button"
              role="tab"
              aria-selected={scope === "me"}
              className={scope === "me" ? "active" : ""}
              onClick={() => setScope("me")}
            >
              Meine Anträge
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={scope === "any"}
              className={scope === "any" ? "active" : ""}
              onClick={() => setScope("any")}
            >
              Alle sichtbaren
            </button>
          </div>
          <select
            aria-label="Nach Status filtern"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          >
            <option value="all">Alle Status</option>
            <option value="active">Aktiv</option>
            <option value="completed">Abgeschlossen</option>
            <option value="cancelled">Abgebrochen</option>
          </select>
        </div>
      </div>

      {isError && (
        <p className="alert" role="alert">
          <Icon name="alert" />
          Anträge konnten nicht geladen werden: {(error as Error).message}
        </p>
      )}

      <section className="panel">
        {isLoading ? (
          <div className="skeleton-list" aria-label="Anträge werden geladen …">
            <span /><span /><span />
          </div>
        ) : !data || data.length === 0 ? (
          <p className="empty">Keine Anträge gefunden.</p>
        ) : (
          <ul className="inbox-list">
            {data.map((run) => {
              const who = formatCandidates(run.candidates);
              const badgeClass =
                run.status === "completed"
                  ? "pill-success"
                  : run.status === "cancelled"
                    ? "pill-danger"
                    : "pill-accent";
              const badgeText =
                run.status === "active"
                  ? run.status_label || runStatusLabel(run.status)
                  : run.status === "completed"
                    ? run.result?.label || runStatusLabel(run.status)
                    : runStatusLabel(run.status);

              return (
                <li key={run.id} className="inbox-card">
                  <div className="inbox-card-main">
                    <div className="inbox-card-title-row">
                      <Link to={`/runs/${run.id}`} className="inbox-card-title">
                        {run.title}
                      </Link>
                      <span className="chip">{run.workflow_name}</span>
                      <span className={`pill ${badgeClass}`}>{badgeText}</span>
                    </div>
                    <div className="inbox-card-meta muted small">
                      <span>Gestartet {relativeTime(run.started_at) ?? "gerade eben"}</span>
                      {run.status === "active" && who && <span> · Wartet auf: <strong>{who}</strong></span>}
                    </div>
                  </div>
                  <div className="inbox-actions">
                    <Link to={`/runs/${run.id}`} className="btn">
                      Status öffnen
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
