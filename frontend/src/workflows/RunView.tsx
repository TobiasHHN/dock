// Run-Ansicht `/runs/:id` (Task 4.6, L 5.5, L 5.10, T 5.6):
// Live-Graph (Knoten ändern ihre Farbe live), Aufgabenleiste, ausgewähltes Schritt-Dokument (bearbeitbar oder schreibgeschützt) und Verlauf.
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Op } from "../api";
import { useAuth, workflowApi } from "../api/client";
import { DocumentView } from "../documents/DocumentView";
import { canAct } from "../forms/formModel";
import { formatCandidates, formatDue, runStatusLabel, useChannelInvalidate } from "../inbox/inboxModel";
import { BatchRejected, submit, useChannel } from "../sync/store";
import { actorLabel, useUsers } from "../ui/actors";
import { confirmDialog } from "../ui/confirm";
import { Icon, relativeTime } from "../ui/icons";
import { toast } from "../ui/toasts";
import { canCancelRun } from "./layout";
import { RunTimeline } from "./RunTimeline";
import { WorkflowGraph } from "./WorkflowGraph";

export function RunPage() {
  const { id } = useParams();
  return <RunView runId={id!} />;
}

export function RunView({ runId }: { runId: string }) {
  const me = useAuth((s) => s.user);
  const users = useUsers();
  const qc = useQueryClient();
  const runCh = useChannel(`run:${runId}`);
  const wsCh = useChannel("workspace");
  const wsRoles = wsCh?.view?.roles as { id: string; key: string }[] | undefined;

  const { data: run, isLoading, isError, error } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => workflowApi.run(runId),
  });

  useChannelInvalidate(`run:${runId}`, [["run", runId]]);

  const wfId = typeof run?.workflow?.id === "string" ? run.workflow.id : undefined;
  const wfName = typeof run?.workflow?.name === "string" ? run.workflow.name : "";
  const wfVersion = run?.workflow?.version != null ? String(run.workflow.version) : "";
  const { data: workflow } = useQuery({
    queryKey: ["workflow", wfId],
    queryFn: () => workflowApi.workflow(wfId!),
    enabled: !!wfId,
  });

  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const lastActiveStep = useRef<string | null>(null);
  const [busyOp, setBusyOp] = useState<string | null>(null);

  // Beim ersten Laden oder beim automatischen Schritt-Fortschritt auf den neuen aktiven Schritt springen
  useEffect(() => {
    const active = run?.current?.step ?? null;
    if (selectedStep === null) {
      const initial = active ?? run?.steps[0]?.step ?? workflow?.draft.steps[0]?.key ?? null;
      if (initial) setSelectedStep(initial);
    } else if (active && lastActiveStep.current && active !== lastActiveStep.current && selectedStep === lastActiveStep.current) {
      setSelectedStep(active);
    }
    lastActiveStep.current = active;
  }, [run?.current?.step, run?.steps, workflow?.draft.steps, selectedStep]);

  if (isLoading) {
    return (
      <div className="doc-skeleton" role="status" aria-label="Ablauf wird geladen …">
        <span className="sk sk-title" />
        <div className="doc-body"><span className="sk" /><span className="sk sk-short" /></div>
      </div>
    );
  }

  if (isError || !run) {
    return (
      <p className="alert" role="alert">
        <Icon name="alert" />
        Ablauf konnte nicht geladen werden: {(error as Error | undefined)?.message ?? "Nicht gefunden"}.{" "}
        <Link to="/inbox/requests">Zu Meine Anträge</Link>
      </p>
    );
  }

  const openTask = runCh?.view?.task;
  const activeStep = run.current?.step ?? null;
  const currentStepDef = workflow?.draft.steps.find((s) => s.key === selectedStep);
  const currentStepStatus = run.steps.find((s) => s.step === selectedStep);
  const stepEditable = run.status === "active" && !!selectedStep && selectedStep === activeStep;

  const mayCancel = canCancelRun(run, workflow?.draft, me, wsRoles);
  const due = run.current?.due_at ? formatDue(run.current.due_at) : null;
  const canClaim =
    run.status === "active" && openTask && !openTask.claimed_by && canAct(openTask, me);
  const canRelease =
    run.status === "active" &&
    openTask &&
    !!openTask.claimed_by &&
    !!me &&
    (openTask.claimed_by.id === me.id || me.roles.includes("einkauf"));

  async function doTaskOp(op: "task.claim" | "task.release") {
    if (!openTask?.id || busyOp) return;
    setBusyOp(op);
    try {
      await submit([{ op, task: openTask.id } as Op]);
      await qc.invalidateQueries({ queryKey: ["run", runId] });
      toast(op === "task.claim" ? "Aufgabe übernommen" : "Aufgabe freigegeben");
    } catch (e) {
      const msg = e instanceof BatchRejected ? e.error.message : (e as Error).message;
      toast(`Aktion fehlgeschlagen: ${msg}`, "error");
    } finally {
      setBusyOp(null);
    }
  }

  async function cancelRun() {
    if (busyOp) return;
    const ok = await confirmDialog({
      title: `Ablauf „${run!.title}“ abbrechen?`,
      message: "Offene Aufgaben werden geschlossen. Bereits gespeicherte Tabellendaten bleiben erhalten.",
      confirmLabel: "Ablauf abbrechen",
      danger: true,
    });
    if (!ok) return;
    setBusyOp("run.cancel");
    try {
      await submit([{ op: "run.cancel", run: runId } as Op]);
      await qc.invalidateQueries({ queryKey: ["run", runId] });
      toast("Ablauf abgebrochen");
    } catch (e) {
      const msg = e instanceof BatchRejected ? e.error.message : (e as Error).message;
      toast(`Abbrechen fehlgeschlagen: ${msg}`, "error");
    } finally {
      setBusyOp(null);
    }
  }

  const statusTone =
    run.status === "completed" ? "pill-success" : run.status === "cancelled" ? "pill-danger" : "pill-accent";
  const statusText =
    run.status === "completed"
      ? run.result?.label || "Abgeschlossen"
      : run.status === "cancelled"
        ? "Abgebrochen"
        : run.current?.label || runStatusLabel(run.status);

  return (
    <div>
      <nav className="breadcrumb" aria-label="Brotkrumen">
        <Link to="/inbox/requests">Meine Anträge</Link>
        <Icon name="chevronRight" size={14} />
        <Link to={`/workflows/${wfId ?? ""}`}>{wfName}</Link>
        <Icon name="chevronRight" size={14} />
        <span aria-current="page">{run.title}</span>
      </nav>

      <div className="page-head">
        <div>
          <div className="run-title-row">
            <h1>{run.title}</h1>
            <span className={`pill ${statusTone}`}>{statusText}</span>
            {wfVersion && <span className="chip">v{wfVersion}</span>}
          </div>
          <p className="muted small">
            Gestartet von <strong>{actorLabel(run.started_by, users)}</strong> · {relativeTime(run.started_at) ?? "gerade eben"}
          </p>
        </div>
        {mayCancel && (
          <div className="actions">
            <button type="button" className="danger" disabled={busyOp !== null} onClick={cancelRun}>
              Abbrechen
            </button>
          </div>
        )}
      </div>

      {run.status === "active" && run.current && (
        <div className="panel run-task-bar">
          <div className="run-task-info">
            <strong>Aktueller Schritt: {run.current.label || run.current.step}</strong>
            <span className="muted small">
              {run.current.claimed_by
                ? `In Bearbeitung von ${run.current.claimed_by.name ?? run.current.claimed_by.id}`
                : `Zuständig: ${formatCandidates(run.current.candidates) || "Niemand"}`}
            </span>
            {due && (
              <span className={`pill ${due.tone === "danger" ? "pill-danger" : due.tone === "warn" ? "pill-warn" : ""}`}>
                {due.text}
              </span>
            )}
          </div>
          <div className="inbox-actions">
            {canClaim && (
              <button type="button" disabled={busyOp !== null} onClick={() => doTaskOp("task.claim")}>
                Übernehmen
              </button>
            )}
            {canRelease && (
              <button type="button" disabled={busyOp !== null} onClick={() => doTaskOp("task.release")}>
                Freigeben
              </button>
            )}
          </div>
        </div>
      )}

      <section className="panel wf-graph-panel" aria-label="Ablauf-Graph">
        <div className="panel-head">
          <h2>Ablauf</h2>
          <div className="wf-legend small muted">
            <span><i className="wf-dot wf-dot-done" /> Erledigt</span>
            <span><i className="wf-dot wf-dot-active" /> Aktuell</span>
            <span><i className="wf-dot wf-dot-pending" /> Offen</span>
          </div>
        </div>

        {workflow ? (
          <WorkflowGraph
            definition={workflow.draft}
            steps={run.steps}
            current={run.current}
            runStatus={run.status}
            selectedStep={selectedStep}
            onSelectStep={setSelectedStep}
          />
        ) : (
          <div className="skeleton-list" style={{ padding: "16px" }}><span /><span /></div>
        )}

        <div className="wf-step-tabs" role="tablist" aria-label="Schritte">
          {run.steps.map((s) => (
            <button
              key={s.step}
              type="button"
              role="tab"
              aria-selected={selectedStep === s.step}
              className={`wf-step-tab wf-step-tab-${s.state} ${selectedStep === s.step ? "active" : ""}`}
              onClick={() => setSelectedStep(s.step)}
            >
              {s.name}
            </button>
          ))}
        </div>
      </section>

      <div className="run-layout">
        <section className="panel run-step-panel" aria-label="Schritt-Dokument">
          <div className="panel-head">
            <div>
              <h2>{currentStepStatus?.name ?? currentStepDef?.name ?? selectedStep ?? "Schritt"}</h2>
              {currentStepStatus?.state === "done" && (
                <p className="muted small">
                  Erledigt{currentStepStatus.label ? `: ${currentStepStatus.label}` : ""}
                  {currentStepStatus.by ? ` · von ${currentStepStatus.by}` : ""}
                  {currentStepStatus.at ? ` · ${relativeTime(currentStepStatus.at)}` : ""}
                </p>
              )}
              {currentStepStatus?.state === "active" && <p className="muted small">Aktueller Schritt</p>}
              {currentStepStatus?.state === "pending" && <p className="muted small">Noch nicht erreicht (schreibgeschützt)</p>}
            </div>
          </div>

          {currentStepDef ? (
            <DocumentView
              key={`${runId}:${currentStepDef.document}:${selectedStep}`}
              docId={currentStepDef.document}
              run={runId}
              stepKey={selectedStep ?? undefined}
              readOnly={!stepEditable}
            />
          ) : (
            <p className="empty">Wähle einen Schritt im Graph aus.</p>
          )}
        </section>

        <RunTimeline runId={runId} events={run.events} />
      </div>
    </div>
  );
}
