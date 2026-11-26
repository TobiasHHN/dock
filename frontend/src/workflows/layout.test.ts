import { describe, expect, it } from "vitest";
import type { RunStatusView } from "../api";
import type { UserOut } from "../api/client";
import type { FlatBlock } from "../documents/blockOps";
import {
  canCancelRun, canStartWorkflow, formatRunEvent, layoutWorkflow, normalizeSubmittedValues, routeEdge, type WorkflowDefinition,
} from "./layout";

const ME_BEN: UserOut = { id: "usr_ben", name: "Ben", email: "ben@example.com", roles: ["mitarbeiter"] };
const ME_ANNA: UserOut = { id: "usr_anna", name: "Anna", email: "anna@example.com", roles: ["einkauf"] };
const ME_CHEF: UserOut = { id: "usr_chef", name: "Chef", email: "chef@example.com", roles: ["chef"] };

const ORDER_WF: WorkflowDefinition = {
  start: "erfassen",
  steps: [
    { key: "erfassen", name: "Bestellung erfassen", document: "doc_1", assignees: [{ kind: "starter" }], exclude_starter: false, exclude_steps: [] },
    { key: "genehmigung", name: "Genehmigung", document: "doc_2", assignees: [{ kind: "role", role: "chef" }], exclude_starter: false, exclude_steps: [] },
    { key: "einkauf", name: "Einkauf", document: "doc_3", assignees: [{ kind: "role", role: "einkauf" }], exclude_starter: false, exclude_steps: [] },
  ],
  transitions: [
    { from: "erfassen", on: "*", to: "genehmigung" },
    { from: "genehmigung", on: "approved", to: "einkauf" },
    { from: "genehmigung", on: "rework", to: "erfassen" },
    { from: "genehmigung", on: "rejected", to: "end" },
    { from: "einkauf", on: "*", to: "end" },
  ],
  starters: [{ kind: "role", role: "mitarbeiter" }, { kind: "role", role: "einkauf" }],
  managers: [{ kind: "role", role: "chef" }],
  starter_can_cancel: true,
};

describe("workflow layout & helpers", () => {
  it("ordnet einen Workflow mit Rücksprung (rework) zyklensicher von links nach rechts an", () => {
    const { nodes, edges } = layoutWorkflow(ORDER_WF);
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    expect(byId.erfassen.layer).toBe(0);
    expect(byId.genehmigung.layer).toBe(1);
    expect(byId.einkauf.layer).toBe(2);
    expect(byId.end.layer).toBe(3);
    expect(byId.erfassen.x).toBeLessThan(byId.genehmigung.x);
    expect(byId.genehmigung.x).toBeLessThan(byId.einkauf.x);

    const rework = edges.find((e) => e.source === "genehmigung" && e.target === "erfassen");
    expect(rework?.isBackEdge).toBe(true);
    expect(rework?.label).toBe("rework");
  });

  it("verwendet explizite layout-Koordinaten, wenn gesetzt", () => {
    const withLayout: WorkflowDefinition = {
      ...ORDER_WF,
      layout: { erfassen: { x: 42, y: 99 } },
    };
    const { nodes } = layoutWorkflow(withLayout);
    expect(nodes.find((n) => n.id === "erfassen")).toMatchObject({ x: 42, y: 99 });
  });

  it("prüft Startberechtigung (inkl. leerer Liste und Rollen-ID-Mapping)", () => {
    expect(canStartWorkflow([], ME_BEN)).toBe(true);
    expect(canStartWorkflow([], null)).toBe(false);
    expect(canStartWorkflow(ORDER_WF.starters, ME_BEN)).toBe(true);
    expect(canStartWorkflow(ORDER_WF.starters, ME_CHEF)).toBe(false);
    expect(
      canStartWorkflow([{ kind: "role", role: "rol_1" }], ME_CHEF, [{ id: "rol_1", key: "chef" }]),
    ).toBe(true);
  });

  it("prüft Abbruch-Berechtigung (Starter, Manager, Einkauf)", () => {
    const run: RunStatusView = {
      id: "run_1",
      title: "Laptop",
      workflow: { id: "wf_1", name: "Bestellung", version: 1 },
      status: "active",
      started_by: { type: "user", id: "usr_ben", name: "Ben" },
      started_at: "2026-11-26T10:00:00Z",
      steps: [],
      events: [],
    };
    expect(canCancelRun(run, ORDER_WF, ME_BEN)).toBe(true);
    expect(canCancelRun(run, { ...ORDER_WF, starter_can_cancel: false }, ME_BEN)).toBe(false);
    expect(canCancelRun(run, { ...ORDER_WF, starter_can_cancel: false }, ME_CHEF)).toBe(true);
    expect(canCancelRun(run, { ...ORDER_WF, starter_can_cancel: false }, ME_ANNA)).toBe(true);
    expect(canCancelRun({ ...run, status: "completed" }, ORDER_WF, ME_BEN)).toBe(false);
  });

  it("formatiert Verlaufseinträge inklusive Agent im Auftrag von", () => {
    const users = { usr_ben: ME_BEN };
    const text = formatRunEvent(
      {
        id: "evt_1",
        run_id: "run_1",
        at: "2026-11-26T10:00:00Z",
        actor: { type: "agent", id: "agt_1", on_behalf_of: "usr_ben", name: "Bens Agent" },
        type: "step_completed",
        step: "erfassen",
        label: "Eingereicht",
      },
      users,
    );
    expect(text).toContain("Bens Agent im Auftrag von Ben");
    expect(text).toContain("erfassen");
    expect(text).toContain("Eingereicht");
  });

  it("normalisiert eingereichte line_items-Arrays für schreibgeschützte Formulare", () => {
    const blocks: FlatBlock[] = [
      { id: "f1", parent_id: null, position: "a0", type: "form", props: {}, version: 1 },
      { id: "li1", parent_id: "f1", position: "a0", type: "line_items", props: { key: "artikel" }, version: 1 },
    ];
    const normalized = normalizeSubmittedValues(blocks, {
      titel: "Laptop",
      artikel: [{ name: "ThinkPad", menge: 1 }],
    });
    expect(normalized.titel).toBe("Laptop");
    expect(normalized.artikel).toEqual([
      { id: "sub_0", position: "0000", values: { name: "ThinkPad", menge: 1 } },
    ]);
  });
});

describe("edge routing", () => {
  it("routeEdge: Nachbar-Ebene seitlich, Überspringen oben, Rücksprung unten", () => {
    expect(routeEdge(0, 1)).toEqual({ route: "forward", sourceHandle: "out-right", targetHandle: "in-left" });
    expect(routeEdge(1, 3)).toEqual({ route: "skip", sourceHandle: "out-top", targetHandle: "in-top" });
    expect(routeEdge(2, 0)).toEqual({ route: "back", sourceHandle: "out-bottom", targetHandle: "in-bottom" });
    expect(routeEdge(1, 1).route).toBe("back");
  });

  it("layoutWorkflow weist Rework- und Reject-Kanten die passenden Handles zu", () => {
    const { edges } = layoutWorkflow(ORDER_WF);
    const by = (on: string) => edges.find((e) => e.label === on)!;
    expect(by("rework")).toMatchObject({ route: "back", sourceHandle: "out-bottom", targetHandle: "in-bottom" });
    expect(by("rejected")).toMatchObject({ route: "skip", sourceHandle: "out-top", targetHandle: "in-top" });
    expect(by("approved").route).toBe("forward");
  });
});
