import { describe, expect, it } from "vitest";
import { groupDocuments } from "./homeModel";

describe("groupDocuments", () => {
  const docs = [
    { id: "doc_ov", title: "Bestellprozess", owner: { workflow: "wf_best", step: null } },
    { id: "doc_s2", title: "Genehmigung", owner: { workflow: "wf_best", step: "genehmigung" } },
    { id: "doc_s1", title: "Antrag", owner: { workflow: "bestellprozess", step: "erfassen" } },
    { id: "doc_x", title: "Extra", owner: { workflow: "wf_best", step: "alt" } },
    { id: "doc_free_old", title: "Notizen", updated_at: "2026-01-01" },
    { id: "doc_free_new", title: "Protokoll", updated_at: "2026-02-01" },
  ];
  const workflows = [{ id: "wf_best", key: "bestellprozess", name: "Bestellprozess", documents: ["doc_s1", "doc_s2"] }];

  it("hängt Schritt-Dokumente in Schrittreihenfolge unter das Übersichtsdokument", () => {
    const { groups, loose } = groupDocuments(docs, workflows);
    expect(groups).toHaveLength(1);
    expect(groups[0].overview?.id).toBe("doc_ov");
    expect(groups[0].children.map((d) => d.id)).toEqual(["doc_s1", "doc_s2", "doc_x"]);
    expect(loose.map((d) => d.id)).toEqual(["doc_free_new", "doc_free_old"]);
  });

  it("zeigt einen Workflow ohne Übersichtsdokument trotzdem als Gruppe", () => {
    const { groups, loose } = groupDocuments(docs.filter((d) => d.id !== "doc_ov"), workflows);
    expect(groups[0].overview).toBeNull();
    expect(groups[0].children).toHaveLength(3);
    expect(loose).toHaveLength(2);
  });

  it("ein Dokument in mehreren Workflows erscheint unter jedem", () => {
    const { groups } = groupDocuments(docs, [...workflows, { id: "wf_b", name: "B", documents: ["doc_s1"] }]);
    expect(groups.map((g) => g.children.map((d) => d.id))).toEqual([["doc_s1"], ["doc_s1", "doc_s2", "doc_x"]]);
  });
});
