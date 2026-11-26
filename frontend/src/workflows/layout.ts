// Reine Logik für Workflow-Graph-Layout, Berechtigungen, Timeline-Events und abgeschlossene Schritt-Werte (Task 4.6, L 5.5, T 5.6).
import type { Actor, RunStatusView, Workflow } from "../api";
import type { UserOut } from "../api/client";
import type { FlatBlock } from "../documents/blockOps";
import { actorLabel } from "../ui/actors";

export type WorkflowDefinition = Workflow["draft"];
export type RunEvent = RunStatusView["events"][number];

export type LayoutNode = {
  id: string;
  kind: "step" | "end";
  label: string;
  x: number;
  y: number;
  layer: number;
};

export type LayoutEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  isBackEdge: boolean;
  /** forward = Nachbar-Ebene, skip = überspringt Ebenen, back = Rücksprung. */
  route: EdgeRoute;
  /** Handle-IDs an Quell-/Zielknoten, damit Skip- und Rück-Kanten oben/unten um Kästen herum laufen. */
  sourceHandle: string;
  targetHandle: string;
};

export type EdgeRoute = "forward" | "skip" | "back";

/** Wählt Routing und Handles: Vorwärts rechts→links, Überspringen oben herum, Rücksprung unten herum. */
export function routeEdge(fromLayer: number, toLayer: number): Pick<LayoutEdge, "route" | "sourceHandle" | "targetHandle"> {
  if (toLayer <= fromLayer) return { route: "back", sourceHandle: "out-bottom", targetHandle: "in-bottom" };
  if (toLayer - fromLayer > 1) return { route: "skip", sourceHandle: "out-top", targetHandle: "in-top" };
  return { route: "forward", sourceHandle: "out-right", targetHandle: "in-left" };
}

const COL_GAP = 320;
const ROW_GAP = 150;

/**
 * Deterministisches Links-nach-Rechts-Layout für Workflow-Graphen ohne externe Layout-Library.
 * Respektiert explizite Koordinaten in `definition.layout`, falls vorhanden.
 * Behandelt Rücksprünge / Schleifen (Rework) sicher ohne Endlosschleife.
 */
export function layoutWorkflow(def: WorkflowDefinition): { nodes: LayoutNode[]; edges: LayoutEdge[] } {
  const stepMap = new Map(def.steps.map((s) => [s.key, s]));
  const hasEnd = def.transitions.some((t) => t.to === "end");

  // Adjazenzliste nur für gültige Schritte
  const adj = new Map<string, string[]>();
  for (const s of def.steps) adj.set(s.key, []);
  for (const t of def.transitions) {
    if (adj.has(t.from) && (stepMap.has(t.to) || t.to === "end")) {
      adj.get(t.from)!.push(t.to);
    }
  }

  // Zyklensichere BFS / längster Pfad über DAG-Kanten
  const layer = new Map<string, number>();
  const visiting = new Set<string>();
  const bfsQueue: string[] = [];

  if (stepMap.has(def.start)) {
    layer.set(def.start, 0);
    bfsQueue.push(def.start);
  }

  // 1. BFS-Abstand vom Start als Basis
  while (bfsQueue.length > 0) {
    const cur = bfsQueue.shift()!;
    const curLayer = layer.get(cur) ?? 0;
    for (const next of adj.get(cur) ?? []) {
      if (next === "end") continue;
      if (!layer.has(next)) {
        layer.set(next, curLayer + 1);
        bfsQueue.push(next);
      }
    }
  }

  // Nicht erreichbare Schritte (z. B. Entwurf) trotzdem einordnen
  let maxStepLayer = 0;
  for (const l of layer.values()) maxStepLayer = Math.max(maxStepLayer, l);
  for (const s of def.steps) {
    if (!layer.has(s.key)) {
      maxStepLayer += 1;
      layer.set(s.key, maxStepLayer);
    }
  }

  // 2. Vorwärtskanten entspannen (Bellman-Ford-artig, max |V| Iterationen, Rücksprünge über BFS-Ordnung ignorieren)
  const forwardEdges = def.transitions.filter(
    (t) => t.to !== "end" && stepMap.has(t.from) && stepMap.has(t.to) && (layer.get(t.from) ?? 0) < (layer.get(t.to) ?? 0),
  );
  for (let i = 0; i < def.steps.length; i++) {
    let changed = false;
    for (const e of forwardEdges) {
      const nextL = (layer.get(e.from) ?? 0) + 1;
      if (nextL > (layer.get(e.to) ?? 0)) {
        layer.set(e.to, nextL);
        changed = true;
      }
    }
    if (!changed) break;
  }
  void visiting;

  let finalLayer = 0;
  for (const l of layer.values()) finalLayer = Math.max(finalLayer, l);
  if (hasEnd) layer.set("end", finalLayer + 1);

  // Nach Layern gruppieren (in Definitionsreihenfolge)
  const byLayer = new Map<number, string[]>();
  for (const s of def.steps) {
    const l = layer.get(s.key) ?? 0;
    const arr = byLayer.get(l) ?? [];
    arr.push(s.key);
    byLayer.set(l, arr);
  }
  if (hasEnd) {
    const endL = layer.get("end") ?? finalLayer + 1;
    const arr = byLayer.get(endL) ?? [];
    arr.push("end");
    byLayer.set(endL, arr);
  }

  const maxCount = Math.max(1, ...Array.from(byLayer.values(), (a) => a.length));
  const nodes: LayoutNode[] = [];

  for (const [l, keys] of [...byLayer.entries()].sort((a, b) => a[0] - b[0])) {
    const offset = ((maxCount - keys.length) * ROW_GAP) / 2;
    keys.forEach((key, idx) => {
      const explicit = def.layout?.[key];
      const step = stepMap.get(key);
      nodes.push({
        id: key,
        kind: key === "end" ? "end" : "step",
        label: key === "end" ? "Ende" : step?.name ?? key,
        x: typeof explicit?.x === "number" ? explicit.x : l * COL_GAP,
        y: typeof explicit?.y === "number" ? explicit.y : offset + idx * ROW_GAP,
        layer: l,
      });
    });
  }

  const edges: LayoutEdge[] = def.transitions.map((t, i) => {
    const fromL = layer.get(t.from) ?? 0;
    const toL = layer.get(t.to) ?? finalLayer + 1;
    return {
      id: `e_${i}_${t.from}_${t.to}`,
      source: t.from,
      target: t.to,
      label: t.on === "*" ? "" : t.on,
      isBackEdge: toL <= fromL,
      ...routeEdge(fromL, toL),
    };
  });

  return { nodes, edges };
}

function matchesAssignees(
  list: WorkflowDefinition["starters"] | undefined,
  me: UserOut | null,
  workspaceRoles?: { id: string; key: string }[],
): boolean {
  if (!me || !list) return false;
  const roleIdToKey = new Map((workspaceRoles ?? []).map((r) => [r.id, r.key]));
  return list.some((a) => {
    if (a.kind === "user") return a.user === me.id;
    if (a.kind === "role") {
      const key = roleIdToKey.get(a.role) ?? a.role;
      return me.roles.includes(key) || me.roles.includes(a.role);
    }
    return false;
  });
}

/** Darf `me` den Workflow starten? Leere `starters`-Liste bedeutet: jeder Angemeldete (L 5.2). */
export function canStartWorkflow(
  starters: WorkflowDefinition["starters"] | undefined,
  me: UserOut | null,
  workspaceRoles?: { id: string; key: string }[],
): boolean {
  if (!me) return false;
  if (!starters || starters.length === 0) return true;
  return matchesAssignees(starters, me, workspaceRoles);
}

/** Darf `me` den aktiven Run abbrechen? (L 5.4: Starter wenn `starter_can_cancel`, Manager oder `einkauf`). */
export function canCancelRun(
  run: RunStatusView,
  def: WorkflowDefinition | undefined,
  me: UserOut | null,
  workspaceRoles?: { id: string; key: string }[],
): boolean {
  if (!me || run.status !== "active") return false;
  if (me.roles.includes("einkauf")) return true;
  if (def?.starter_can_cancel !== false && run.started_by.id === me.id) return true;
  return matchesAssignees(def?.managers, me, workspaceRoles);
}

/** Lesbare deutsche Beschreibung eines Run-Verlaufseintrags (L 5.8, L 5.10). */
export function formatRunEvent(ev: RunEvent, users: Record<string, UserOut>): string {
  const who = actorLabel(ev.actor as Actor, users);
  const step = ev.step ? `„${ev.step}“` : "";
  switch (ev.type) {
    case "started":
      return `${who} hat den Ablauf gestartet`;
    case "step_entered":
      return `Schritt ${step} gestartet`;
    case "task_claimed":
      return `${who} hat Schritt ${step} übernommen`;
    case "task_released":
      return `${who} hat Schritt ${step} freigegeben`;
    case "reassigned":
      return `${who} hat Schritt ${step} neu zugewiesen`;
    case "step_completed":
      return `${who} hat Schritt ${step} abgeschlossen${ev.label ? ` (${ev.label})` : ""}`;
    case "overdue":
      return `Frist für Schritt ${step} überschritten`;
    case "unassigned":
      return `Keine Zuständigen für Schritt ${step}`;
    case "comment":
      return `${who} kommentiert:`;
    case "subflow_started":
      return `Unter-Ablauf in Schritt ${step} gestartet`;
    case "subflow_completed":
      return `Unter-Ablauf in Schritt ${step} abgeschlossen`;
    case "completed":
      return `Ablauf abgeschlossen${ev.label ? `: ${ev.label}` : ""}`;
    case "cancelled":
      return `${who} hat den Ablauf abgebrochen`;
    default:
      return `${who}: ${ev.type}`;
  }
}

/** Wandelt gespeicherte `line_items`-Arrays aus `run.steps[step].values` in das `{ id, position, values }`-Format um. */
export function normalizeSubmittedValues(
  blocks: FlatBlock[],
  raw: Record<string, unknown> | undefined,
): Record<string, unknown> {
  if (!raw) return {};
  const lineKeys = new Set(blocks.filter((b) => b.type === "line_items").map((b) => String(b.props.key)));
  const out: Record<string, unknown> = { ...raw };
  for (const key of lineKeys) {
    const val = out[key];
    if (!Array.isArray(val)) continue;
    out[key] = val.map((item, idx) => {
      if (item && typeof item === "object" && "id" in item && "values" in item) return item;
      return {
        id: `sub_${idx}`,
        position: String(idx).padStart(4, "0"),
        values: item && typeof item === "object" ? item : {},
      };
    });
  }
  return out;
}
