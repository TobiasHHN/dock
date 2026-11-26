import { describe, expect, it } from "vitest";
import type { Col } from "../tables/tableModel";
import { buildTableViewProps, newTableOp, workflowBlock } from "./embedModel";

const col = (id: string, position: string): Col => ({ id, key: id, name: id, type: { kind: "text" }, position });
const cols = [col("col_a", "a"), col("col_c", "c"), col("col_b", "b")];
const base = { table: "tbl_1", allColumns: cols, selected: ["col_a", "col_b", "col_c"], filterRows: [], sort: [], editable: false, allowAdd: true, allowDelete: true };

describe("buildTableViewProps", () => {
  it("lässt columns weg, wenn alle Spalten gewählt sind", () => {
    expect(buildTableViewProps(base)).toMatchObject({ table: "tbl_1", columns: null, filter: [], sort: [] });
  });
  it("behält die Tabellenreihenfolge bei Teilauswahl", () => {
    expect(buildTableViewProps({ ...base, selected: ["col_c", "col_a"] }).columns).toEqual(["col_a", "col_c"]);
  });
  it("allow_add/allow_delete nur mit editable", () => {
    expect(buildTableViewProps(base)).toMatchObject({ editable: false, allow_add: false, allow_delete: false });
    expect(buildTableViewProps({ ...base, editable: true })).toMatchObject({ editable: true, allow_add: true, allow_delete: true });
  });
  it("übernimmt Filter, ignoriert unvollständige, und gültige Sortierung", () => {
    const p = buildTableViewProps({
      ...base,
      filterRows: [{ column: "col_a", op: "eq", text: "x" }, { column: "col_b", op: "eq", text: "" }],
      sort: [{ column: "col_a", dir: "desc" }, { column: "gone", dir: "asc" }],
    });
    expect(p.filter).toEqual([{ column: "col_a", op: "eq", value: "x" }]);
    expect(p.sort).toEqual([{ column: "col_a", dir: "desc" }]);
  });
});

describe("newTableOp / workflowBlock", () => {
  it("leitet einen eindeutigen Key ab", () => {
    const op = newTableOp("tbl_n", "Bestellungen Süd", ["bestellungen_sued"], "col_n") as unknown as { key: string; name: string };
    expect(op.key).toBe("bestellungen_sued_2");
    expect(op.name).toBe("Bestellungen Süd");
  });
  it("Workflow-Block startet als launcher", () => {
    expect(workflowBlock("blk_1", "wfl_1").props).toEqual({ workflow: "wfl_1", mode: "launcher", wait: false });
  });
});
