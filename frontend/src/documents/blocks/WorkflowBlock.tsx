// `workflow`-Block im Dokument (Task 4.6, F11, L 5.5):
// - mode === "launcher" (Standard): Startknopf (nur für Berechtigte!) + Live-Liste laufender/abgeschlossener Runs
// - mode === "run": kompakter Statusverweis auf einen konkreten Run
// - mode === "subflow": Startknopf/Verweis für einen Unter-Ablauf
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { Op } from "../../api";
import { useAuth, workflowApi } from "../../api/client";
import { formatCandidates, resultLabel, runStatusLabel, useChannelInvalidate } from "../../inbox/inboxModel";
import { BatchRejected, newId, submit, useChannel } from "../../sync/store";
import { Icon, relativeTime } from "../../ui/icons";
import { toast } from "../../ui/toasts";
import { canStartWorkflow } from "../../workflows/layout";
import type { FlatBlock } from "../blockOps";
import { useDoc } from "../docContext";
import { BLOCK_COMPONENTS } from "./registry";

function RunRefCard({ runId }: { runId: string }) {
  const { data: run, isLoading } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => workflowApi.run(runId),
  });
  useChannelInvalidate(`run:${runId}`, [["run", runId]]);

  if (isLoading) return <div className="wf-block"><span className="muted small">Ablauf wird geladen …</span></div>;
  if (!run) return <div className="wf-block"><Link to={`/runs/${runId}`}>Ablauf {runId}</Link></div>;

  const badgeClass =
    run.status === "completed" ? "pill-success" : run.status === "cancelled" ? "pill-danger" : "pill-accent";
  const badgeText =
    run.status === "active"
      ? run.current?.label || "Aktiv"
      : resultLabel(run.result) || runStatusLabel(run.status);

  return (
    <div className="wf-block">
      <div className="wf-block-head">
        <div className="wf-block-title">
          <Icon name="flow" size={16} />
          <Link to={`/runs/${run.id}`}><strong>{run.title}</strong></Link>
          <span className={`pill ${badgeClass}`}>{badgeText}</span>
        </div>
        <Link to={`/runs/${run.id}`} className="btn">Öffnen</Link>
      </div>
    </div>
  );
}

export function WorkflowBlock({ block }: { block: FlatBlock }) {
  const p = block.props;
  const doc = useDoc();
  const me = useAuth((s) => s.user);
  const navigate = useNavigate();
  const wsCh = useChannel("workspace");
  const wsRoles = wsCh?.view?.roles as { id: string; key: string }[] | undefined;
  const [starting, setStarting] = useState(false);

  const runProp = typeof p.run === "string" && p.run ? p.run : null;
  const wfRef = typeof p.workflow === "string" ? p.workflow : "";
  const mode = (p.mode as string | undefined) ?? (runProp ? "run" : "launcher");

  const { data: wf, isLoading: wfLoading } = useQuery({
    queryKey: ["workflow", wfRef],
    queryFn: () => workflowApi.workflow(wfRef),
    enabled: !!wfRef && !runProp,
  });

  const { data: runs } = useQuery({
    queryKey: ["runs", "workflow", wf?.id ?? wfRef],
    queryFn: () => workflowApi.runs({ workflow: wf?.id ?? wfRef, started_by: "any" }),
    enabled: !!wf && mode === "launcher",
  });

  useChannelInvalidate(me ? `user:${me.id}` : null, [["runs", "workflow", wf?.id ?? wfRef]]);
  useChannelInvalidate("workspace", [["workflow", wfRef]]);

  if (runProp) return <RunRefCard runId={runProp} />;
  if (!wfRef) return <div className="placeholder-block"><b>Workflow</b> · kein Workflow verknüpft</div>;
  if (wfLoading) return <div className="wf-block"><span className="muted small">Workflow wird geladen …</span></div>;
  if (!wf) return <div className="placeholder-block"><b>Workflow</b> · „{wfRef}“ nicht gefunden</div>;

  const mayStart = wf.latest_version != null && canStartWorkflow(wf.draft.starters, me, wsRoles);

  async function startRun() {
    if (starting) return;
    const runId = newId("run");
    setStarting(true);
    try {
      const parent = mode === "subflow" && doc.run && doc.stepKey
        ? { run: doc.run, step: doc.stepKey, block: block.id }
        : undefined;
      await submit([
        {
          op: "run.start",
          id: runId,
          workflow: wf!.id,
          input: (p.input as Record<string, unknown> | undefined) ?? {},
          ...(parent ? { parent } : {}),
        } as Op,
      ]);
      navigate(`/runs/${runId}`);
    } catch (e) {
      const msg = e instanceof BatchRejected ? e.error.message : (e as Error).message;
      toast(`Workflow konnte nicht gestartet werden: ${msg}`, "error");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="wf-block">
      <div className="wf-block-head">
        <div className="wf-block-title">
          <Icon name="flow" size={16} />
          <Link to={`/workflows/${wf.id}`}><strong>{wf.name}</strong></Link>
          {wf.latest_version != null ? (
            <span className="chip chip-success">v{wf.latest_version}</span>
          ) : (
            <span className="chip">Entwurf</span>
          )}
        </div>
        {mayStart && (
          <button type="button" className="primary" disabled={starting} aria-busy={starting} onClick={startRun}>
            {starting && <span className="spinner" aria-hidden="true" />}
            {mode === "subflow" ? "Unter-Workflow starten" : "Workflow starten"}
          </button>
        )}
      </div>

      {mode === "launcher" && runs && (
        runs.length === 0 ? (
          <p className="muted small" style={{ margin: "6px 0 0" }}>Noch keine Abläufe.</p>
        ) : (
          <ul className="wf-block-runs">
            {runs.slice(0, 6).map((r) => {
              const who = formatCandidates(r.candidates);
              const badgeClass =
                r.status === "completed" ? "pill-success" : r.status === "cancelled" ? "pill-danger" : "pill-accent";
              const badgeText =
                r.status === "active"
                  ? r.status_label || runStatusLabel(r.status)
                  : resultLabel(r.result) || runStatusLabel(r.status);
              return (
                <li key={r.id}>
                  <Link to={`/runs/${r.id}`} className="wf-block-run-row">
                    <span className="wf-block-run-title">{r.title}</span>
                    <span className="muted small">{relativeTime(r.started_at)}</span>
                    {r.status === "active" && who && <span className="muted small">· {who}</span>}
                    <span className={`pill ${badgeClass}`}>{badgeText}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )
      )}
    </div>
  );
}

BLOCK_COMPONENTS.workflow = WorkflowBlock;
