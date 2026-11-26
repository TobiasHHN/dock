// Interaktiver Workflow-Graph mit @xyflow/react (Task 4.6, L 5.5, T 5.6):
// Knoten sind nach Zustand farbig (erledigt = grün, aktuell = Akzent, offen = gedämpft); Klick wählt einen Schritt.
import { useMemo } from "react";
import {
  Background, Controls, type Edge, Handle, MarkerType, type Node, type NodeProps, Position, ReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { RunStatusView } from "../api";
import { relativeTime } from "../ui/icons";
import { layoutWorkflow, type WorkflowDefinition } from "./layout";

type StatusStep = RunStatusView["steps"][number];
type StatusCurrent = NonNullable<RunStatusView["current"]>;

type StepNodeData = {
  label: string;
  state: "done" | "active" | "pending";
  outcomeLabel?: string | null;
  by?: string | null;
  statusLabel?: string | null;
  claimedBy?: string | null;
  dueAt?: string | null;
  selected: boolean;
};

type EndNodeData = {
  runStatus?: "active" | "completed" | "cancelled";
};

function StepNode({ data }: NodeProps<Node<StepNodeData>>) {
  const cls = [
    "wf-node",
    `wf-node-${data.state}`,
    data.selected ? "wf-node-selected" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cls}>
      <Handle type="target" position={Position.Left} className="wf-handle" />
      <div className="wf-node-head">
        <span className={`wf-dot wf-dot-${data.state}`} aria-hidden="true" />
        <span className="wf-node-title">{data.label}</span>
      </div>
      {data.state === "done" && (data.outcomeLabel || data.by) && (
        <div className="wf-node-meta">
          {data.outcomeLabel && <span className="wf-node-outcome">{data.outcomeLabel}</span>}
          {data.by && <span> · {data.by}</span>}
        </div>
      )}
      {data.state === "active" && (
        <div className="wf-node-meta">
          <span>{data.statusLabel || "Aktiv"}</span>
          {data.claimedBy && <span> · {data.claimedBy}</span>}
          {data.dueAt && <span> · fällig {relativeTime(data.dueAt)}</span>}
        </div>
      )}
      {data.state === "pending" && <div className="wf-node-meta">Offen</div>}
      <Handle type="source" position={Position.Right} className="wf-handle" />
    </div>
  );
}

function EndNode({ data }: NodeProps<Node<EndNodeData>>) {
  const tone =
    data.runStatus === "completed"
      ? "wf-node-done"
      : data.runStatus === "cancelled"
        ? "wf-node-cancelled"
        : "wf-node-pending";
  return (
    <div className={`wf-node wf-node-end ${tone}`}>
      <Handle type="target" position={Position.Left} className="wf-handle" />
      <span className="wf-node-title">Ende</span>
    </div>
  );
}

const NODE_TYPES = { step: StepNode, end: EndNode };

export function WorkflowGraph({
  definition,
  steps,
  current,
  runStatus,
  selectedStep,
  onSelectStep,
}: {
  definition: WorkflowDefinition;
  steps?: StatusStep[];
  current?: StatusCurrent | null;
  runStatus?: "active" | "completed" | "cancelled";
  selectedStep?: string | null;
  onSelectStep?: (stepKey: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const layout = layoutWorkflow(definition);
    const statusByKey = new Map((steps ?? []).map((s) => [s.step, s]));

    const rfNodes: Node[] = layout.nodes.map((n) => {
      if (n.kind === "end") {
        return {
          id: n.id,
          type: "end",
          position: { x: n.x, y: n.y },
          data: { runStatus } satisfies EndNodeData,
          selectable: false,
        };
      }
      const st = statusByKey.get(n.id);
      const isActive = st ? st.state === "active" : current?.step === n.id;
      const state: "done" | "active" | "pending" = st?.state ?? (isActive ? "active" : "pending");
      return {
        id: n.id,
        type: "step",
        position: { x: n.x, y: n.y },
        data: {
          label: n.label,
          state,
          outcomeLabel: st?.label,
          by: st?.by,
          statusLabel: isActive ? current?.label : undefined,
          claimedBy: isActive ? current?.claimed_by?.name : undefined,
          dueAt: isActive ? current?.due_at : undefined,
          selected: selectedStep === n.id,
        } satisfies StepNodeData,
      };
    });

    const rfEdges: Edge[] = layout.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label || undefined,
      type: e.isBackEdge ? "smoothstep" : "default",
      animated: current?.step === e.source && runStatus === "active",
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      style: e.isBackEdge ? { strokeDasharray: "5 4" } : undefined,
    }));

    return { nodes: rfNodes, edges: rfEdges };
  }, [definition, steps, current, runStatus, selectedStep]);

  return (
    <div className="wf-graph" aria-label="Workflow-Graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_ev, node) => {
          if (node.id !== "end") onSelectStep?.(node.id);
        }}
      >
        <Background gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
