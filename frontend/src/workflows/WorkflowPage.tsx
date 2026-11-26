// Workflow-Detailseite `/workflows/:id` (Task 4.6, L 5.5): Graph, Startknopf nur für Berechtigte und Run-Liste.
import { EmbedInDocumentButton } from "../documents/SheetBar";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { Op } from "../api";
import { canEditStructure, useAuth, workflowApi } from "../api/client";
import { deleteWorkflow } from "./deleteWorkflow";
import { formatCandidates, resultLabel, runStatusLabel, useChannelInvalidate } from "../inbox/inboxModel";
import { BatchRejected, newId, submit, useChannel } from "../sync/store";
import { Icon, relativeTime } from "../ui/icons";
import { toast } from "../ui/toasts";
import { canStartWorkflow } from "./layout";
import { WorkflowGraph } from "./WorkflowGraph";

export function WorkflowPage() {
  const { id } = useParams();
  return <WorkflowDetail workflowId={id!} />;
}

export function WorkflowDetail({ workflowId, embedded = false }: { workflowId: string; embedded?: boolean }) {
  const me = useAuth((s) => s.user);
  const navigate = useNavigate();
  const wsCh = useChannel("workspace");
  const wsRoles = wsCh?.view?.roles as { id: string; key: string }[] | undefined;
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const { data: wf, isLoading, isError, error } = useQuery({
    queryKey: ["workflow", workflowId],
    queryFn: () => workflowApi.workflow(workflowId),
  });

  const { data: runs } = useQuery({
    queryKey: ["runs", "workflow", wf?.id ?? workflowId],
    queryFn: () => workflowApi.runs({ workflow: wf?.id ?? workflowId, started_by: "any" }),
    enabled: !!wf,
  });

  useChannelInvalidate(me ? `user:${me.id}` : null, [["runs", "workflow", wf?.id ?? workflowId]]);
  useChannelInvalidate("workspace", [["workflow", workflowId]]);

  if (isLoading) {
    return (
      <div className="doc-skeleton" role="status" aria-label="Workflow wird geladen …">
        <span className="sk sk-title" />
        <div className="doc-body"><span className="sk" /><span className="sk sk-short" /></div>
      </div>
    );
  }

  if (isError || !wf) {
    return (
      <p className="alert" role="alert">
        <Icon name="alert" />
        Workflow konnte nicht geladen werden: {(error as Error | undefined)?.message ?? "Nicht gefunden"}.
      </p>
    );
  }

  const mayStart = wf.latest_version != null && canStartWorkflow(wf.draft.starters, me, wsRoles);
  const stepDef = wf.draft.steps.find((s) => s.key === (selectedStep ?? wf.draft.start));

  async function startRun() {
    if (starting) return;
    const runId = newId("run");
    setStarting(true);
    try {
      await submit([{ op: "run.start", id: runId, workflow: wf!.id, input: {} } as Op]);
      navigate(`/runs/${runId}`);
    } catch (e) {
      const msg = e instanceof BatchRejected ? e.error.message : (e as Error).message;
      toast(`Start fehlgeschlagen: ${msg}`, "error");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div>
      {!embedded && (
        <nav className="breadcrumb" aria-label="Brotkrumen">
          <Link to="/">Home</Link>
          <Icon name="chevronRight" size={14} />
          <span aria-current="page">{wf.name}</span>
        </nav>
      )}

      <div className="page-head">
        <div>
          <div className="run-title-row">
            <h1>{wf.name}</h1>
            {wf.latest_version != null ? (
              <span className="chip chip-success">v{wf.latest_version}</span>
            ) : (
              <span className="chip">Entwurf</span>
            )}
          </div>
          <p className="muted small">Key: <span translate="no">{wf.key}</span> · {wf.draft.steps.length} Schritte</p>
        </div>
        <div className="actions">
          {canEditStructure(me) && (
            <button
              type="button" className="ghost quiet-danger"
              onClick={async () => { if (await deleteWorkflow(wf)) navigate("/"); }}
            >
              <Icon name="trash" size={14} />Workflow löschen
            </button>
          )}
          {!embedded && <EmbedInDocumentButton sheet={{ kind: "workflow", id: wf.id }} />}
          {mayStart && (
            <button type="button" className="primary" disabled={starting} aria-busy={starting} onClick={startRun}>
              {starting && <span className="spinner" aria-hidden="true" />}
              Ablauf starten
            </button>
          )}
        </div>
      </div>

      <section className="panel wf-graph-panel">
        <div className="panel-head">
          <h2>Aufbau</h2>
          {stepDef && (
            <Link to={`/documents/${stepDef.document}`} className="small">
              Dokument „{stepDef.name}“ öffnen →
            </Link>
          )}
        </div>
        <WorkflowGraph
          definition={wf.draft}
          selectedStep={selectedStep ?? wf.draft.start}
          onSelectStep={setSelectedStep}
        />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Abläufe</h2>
          {runs && <span className="count">{runs.length}</span>}
        </div>
        {!runs ? (
          <div className="skeleton-list" style={{ padding: "8px 12px" }}><span /><span /></div>
        ) : runs.length === 0 ? (
          <p className="empty">Noch keine Abläufe gestartet.</p>
        ) : (
          <ul className="inbox-list">
            {runs.map((r) => (
              <li key={r.id} className="inbox-card">
                <div className="inbox-card-main">
                  <div className="inbox-card-title-row">
                    <Link to={`/runs/${r.id}`} className="inbox-card-title">{r.title}</Link>
                    <span className={`pill ${r.status === "completed" ? "pill-success" : r.status === "cancelled" ? "pill-danger" : "pill-accent"}`}>
                      {r.status === "active"
                        ? r.status_label || runStatusLabel(r.status)
                        : resultLabel(r.result) || runStatusLabel(r.status)}
                    </span>
                  </div>
                  <div className="inbox-card-meta muted small">
                    <span>Gestartet {relativeTime(r.started_at) ?? "gerade eben"}</span>
                    {r.status === "active" && formatCandidates(r.candidates) && (
                      <span> · Wartet auf: <strong>{formatCandidates(r.candidates)}</strong></span>
                    )}
                  </div>
                </div>
                <div className="inbox-actions">
                  <Link to={`/runs/${r.id}`} className="btn">Öffnen</Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
