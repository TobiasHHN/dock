import { describe, expect, it } from "vitest";
import type { FlatBlock } from "./blockOps";
import { activeSheet, collectSheets, sheetOfBlock, sheetParam } from "./workbookModel";

const b = (id: string, type: string, props: Record<string, unknown>, parent: string | null, position: string): FlatBlock =>
  ({ id, parent_id: parent, position, type, props, version: 1 });

describe("collectSheets", () => {
  const blocks = [
    b("w1", "workflow", { workflow: "wf_a" }, null, "a1"),
    b("t2", "table_view", { table: "tbl_b" }, null, "a3"),
    b("p", "paragraph", {}, null, "a2"),
    b("sec", "section", {}, null, "a4"),
    b("t1", "table_view", { table: "tbl_a" }, "sec", "a0"),
    b("t3", "table_view", { table: "tbl_b" }, "sec", "a1"),
    b("w2", "workflow", { workflow: "wf_b" }, "sec", "a2"),
  ];
  it("Tabellen vor Workflows, Dokumentreihenfolge, ohne Doppelte, jede Tiefe", () => {
    expect(collectSheets(blocks).map((s) => s.id)).toEqual(["tbl_b", "tbl_a", "wf_a", "wf_b"]);
  });
  it("leer ohne Einbettungen", () => expect(collectSheets([b("p", "paragraph", {}, null, "a")])).toEqual([]));
  it("löst Keys auf und lässt unbekannte Verweise weg", () => {
    const bl = [b("1", "table_view", { table: "orders" }, null, "a"), b("2", "table_view", { table: "weg" }, null, "b")];
    expect(collectSheets(bl, { tables: [{ id: "tbl_1", key: "orders" }] })).toEqual([{ kind: "table", id: "tbl_1" }]);
  });
  it("ignoriert Blöcke ohne Verweis", () => {
    expect(collectSheets([b("1", "table_view", {}, null, "a")])).toEqual([]);
  });
});

describe("activeSheet / sheetParam", () => {
  const sheets = [{ kind: "table" as const, id: "tbl_a" }];
  it("findet das Blatt", () => expect(activeSheet("tbl_a", sheets)).toEqual(sheets[0]));
  it("unbekannt oder leer: Blatt 1", () => {
    expect(activeSheet("x", sheets)).toBeNull();
    expect(activeSheet(null, sheets)).toBeNull();
  });
  it("Parameter", () => {
    expect(sheetParam(sheets[0])).toBe("tbl_a");
    expect(sheetParam(null)).toBeNull();
  });
});

describe("sheetOfBlock", () => {
  it("Tabelle und Workflow", () => {
    expect(sheetOfBlock({ type: "table_view", props: { table: "t" } })).toEqual({ kind: "table", id: "t" });
    expect(sheetOfBlock({ type: "workflow", props: { workflow: "w" } })).toEqual({ kind: "workflow", id: "w" });
    expect(sheetOfBlock({ type: "paragraph", props: {} })).toBeNull();
  });
});
