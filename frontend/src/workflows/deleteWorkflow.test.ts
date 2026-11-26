import { describe, expect, it } from "vitest";
import { workflowDeleteOps } from "./deleteWorkflow";

describe("workflowDeleteOps", () => {
  it("löscht erst den Workflow, dann seine Schritt-Dokumente (Übersicht ergänzt der Server)", () => {
    const docs = [
      { id: "doc_ov", owner: { workflow: "wf_best", step: null } },
      { id: "doc_s1", owner: { workflow: "bestellprozess", step: "erfassen" } },
      { id: "doc_s2", owner: { workflow: "wf_best", step: "genehmigung" } },
      { id: "doc_other", owner: { workflow: "wf_x", step: "a" } },
      { id: "doc_free" },
    ];
    expect(workflowDeleteOps({ id: "wf_best", key: "bestellprozess" }, docs)).toEqual([
      { op: "workflow.delete", workflow: "wf_best" },
      { op: "doc.delete", doc: "doc_s1" },
      { op: "doc.delete", doc: "doc_s2" },
    ]);
  });
});
