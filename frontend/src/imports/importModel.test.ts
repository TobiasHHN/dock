import { describe, expect, it } from "vitest";
import {
  buildFormData, checkFile, detectKind, emptyPlanMessage, importErrorText, includeOp, summarizePlan, targetPath,
} from "./importModel";

const xlsxPlan = {
  import_id: "imp_1",
  created: { tables: [{ id: "tbl_1", key: "bestellungen", name: "Bestellungen", columns: ["a", "b", "c"], column_ids: {}, rows: 3 }] },
  warnings: ["Spalte C: gemischte Werte, als text angelegt"],
};
const docxPlan = {
  import_id: "imp_2",
  created: {
    tables: [],
    documents: [{ id: "doc_1", title: "Bestellformular", form: { block: "b", fields: { a: "x", b: "y" }, line_items: { pos: {} }, actions: [] } }],
    bound_table: { id: "tbl_9", key: "bestellungen" },
  },
  warnings: ["Formular schreibt nirgends hin"],
};

describe("Import-Antwort", () => {
  it("fasst Excel-Tabellen und Warnungen zusammen", () => {
    const s = summarizePlan(xlsxPlan);
    expect(s.tables).toEqual([{ id: "tbl_1", key: "bestellungen", name: "Bestellungen", columns: 3, rows: 3 }]);
    expect(s.documents).toEqual([]);
    expect(s.warnings).toHaveLength(1);
    expect(targetPath(s)).toBe("/tables/tbl_1");
  });

  it("fasst Word-Dokument mit Formular zusammen und navigiert zum Dokument", () => {
    const s = summarizePlan(docxPlan);
    expect(s.documents[0]).toMatchObject({ title: "Bestellformular", hasForm: true, fields: 2, lineItems: 1, actions: 0 });
    expect(s.boundTable).toEqual({ id: "tbl_9", key: "bestellungen" });
    expect(targetPath(s)).toBe("/documents/doc_1");
  });

  it("verträgt fehlende oder unerwartete Felder", () => {
    const s = summarizePlan({ created: {}, warnings: [] });
    expect(emptyPlanMessage(s)).toMatch(/nichts/);
    expect(targetPath(s)).toBe("/");
    expect(summarizePlan({ created: { tables: [null, 5] } as never, warnings: [] }).tables).toHaveLength(2);
  });
});

describe("Fehler und Dateiprüfung", () => {
  it("übersetzt 413 und 422", () => {
    expect(importErrorText(413, "x")).toMatch(/zu groß.*10 MB/);
    expect(importErrorText(422, "Blatt fehlt")).toBe("Die Datei lässt sich nicht importieren: Blatt fehlt");
    expect(importErrorText(422)).toMatch(/nicht lesen/);
    expect(importErrorText(500)).toMatch(/\(500\)/);
    expect(importErrorText(null, "Failed to fetch")).toBe("Failed to fetch");
  });

  it("erkennt Dateitypen und Größe", () => {
    expect(detectKind("A.XLSX")).toBe("xlsx");
    expect(detectKind("b.docx")).toBe("docx");
    expect(detectKind("c.pdf")).toBeNull();
    expect(checkFile({ name: "c.pdf", size: 1 })).toHaveProperty("error");
    expect(checkFile({ name: "a.xlsx", size: 11 * 1024 * 1024 })).toHaveProperty("error");
    expect(checkFile({ name: "a.xlsx", size: 100 })).toEqual({ kind: "xlsx" });
  });
});

describe("Anfrage", () => {
  const file = new File(["x"], "a.docx");
  it("setzt nur passende Parameter", () => {
    const d = buildFormData("docx", file, { title: " Titel ", bindTable: "bestellungen", sheet: "S" });
    expect(d.get("title")).toBe("Titel");
    expect(d.get("bind_table")).toBe("bestellungen");
    expect(d.get("sheet")).toBeNull();
    const x = buildFormData("xlsx", file, { sheet: "Blatt1", title: "t" });
    expect(x.get("sheet")).toBe("Blatt1");
    expect(x.get("title")).toBeNull();
  });
  it("baut import.include", () => {
    expect(includeOp("imp_1")).toEqual({ op: "import.include", import_id: "imp_1" });
  });
});
