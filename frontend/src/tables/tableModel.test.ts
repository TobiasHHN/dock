// Logik des Tabellen-Editors (Task 3.1) und das Zusammenspiel mit dem Sync-Store (Zellen sofort, neue Zeilen live).
import { describe, expect, it } from "vitest";
import type { WsClientMessage, WsServerMessage } from "../api";
import type { ConnectionStatus, Transport } from "../sync/socket";
import { createSyncStore } from "../sync/store";
import {
  type Col, type TRow, activeFilters, buildColumnAdd, columnType, deleteRowOp, displayValue, fieldErrors, filterValue,
  hasExpression, inputText, insertRowOp, insertedRowIds, opsFor, overlayRows, parseInput, queryErrorText, slugKey, sortRows,
  uniqueKey, updateCellOp,
} from "./tableModel";

const col = (id: string, key: string, type: object, extra: object = {}): Col =>
  ({ id, key, name: key[0].toUpperCase() + key.slice(1), type, position: id, ...extra }) as Col;

const columns: Col[] = [
  col("c1", "name", { kind: "text" }),
  col("c2", "preis", { kind: "currency", currency: "EUR" }),
  col("c3", "status", { kind: "select", options: [{ id: "open", label: "Offen" }, { id: "done", label: "Erledigt" }] }),
];
const row = (id: string, values: object): TRow => ({ id, position: id, values }) as TRow;

describe("Anzeige und Eingabe", () => {
  it("formatiert Werte deutsch", () => {
    expect(displayValue(1234.5, { kind: "currency", currency: "EUR" })).toBe("1.234,50 €");
    expect(displayValue(3, { kind: "number", decimals: 2 })).toBe("3,00");
    expect(displayValue("2025-03-09", { kind: "date" })).toBe("09.03.2025");
    expect(displayValue(true, { kind: "boolean" })).toBe("Ja");
    expect(displayValue("open", columns[2].type)).toBe("Offen");
    expect(displayValue("usr_1", { kind: "user" }, { usr_1: { name: "Anna" } })).toBe("Anna");
    expect(displayValue(null, { kind: "text" })).toBe("");
  });

  it("wandelt Eingaben in den Spaltentyp um oder meldet den Grund", () => {
    expect(parseInput("12,50", columns[1].type)).toEqual({ value: 12.5 });
    expect(parseInput("", columns[1].type)).toEqual({ value: null });
    const bad = parseInput("abc", { kind: "integer" });
    expect("error" in bad && bad.error).toMatch(/ganze Zahl/);
    expect(inputText(12.5, columns[1].type)).toBe("12,5");
  });
});

describe("Spalten anlegen", () => {
  it("leitet Keys aus dem Namen ab und hält sie eindeutig", () => {
    expect(slugKey("Größe & Preis")).toBe("groesse_preis");
    expect(slugKey("col_menge")).toBe("menge");
    expect(uniqueKey("name", ["name", "name_2"])).toBe("name_3");
    expect(uniqueKey("", [])).toBe("spalte");
  });

  it("baut column.add hinter der letzten Spalte", () => {
    const r = buildColumnAdd({ id: "tbl_1", columns }, { name: "Menge", kind: "integer", required: true, options: "", decimals: 2 }, () => "col_new");
    expect(r).toEqual({
      op: {
        op: "column.add", table: "tbl_1", after: "c3",
        column: { id: "col_new", key: "menge", name: "Menge", type: { kind: "integer" }, required: true, unique: false },
      },
    });
  });

  it("verlangt Namen und bei Auswahl Optionen", () => {
    expect(buildColumnAdd({ id: "t", columns }, { name: " ", kind: "text", required: false, options: "", decimals: 2 }, () => "x")).toHaveProperty("errors.name");
    expect(buildColumnAdd({ id: "t", columns }, { name: "A", kind: "select", required: false, options: " , ", decimals: 2 }, () => "x")).toHaveProperty("errors.options");
    expect(columnType({ kind: "select", options: "Offen, In Arbeit", decimals: 2 })).toEqual({
      kind: "select", options: [{ id: "offen", label: "Offen" }, { id: "in_arbeit", label: "In Arbeit" }],
    });
  });
});

describe("Sortierung", () => {
  const rows = [row("r1", { c1: "Stuhl", c2: 30 }), row("r2", { c1: "Tisch", c2: 5 }), row("r3", { c1: "Lampe" }), row("r4", { c1: "Bett", c2: 120 })];
  it("sortiert Zahlen numerisch, Leere stehen immer hinten", () => {
    expect(sortRows(rows, columns, [{ column: "c2", dir: "asc" }]).map((r) => r.id)).toEqual(["r2", "r1", "r4", "r3"]);
    expect(sortRows(rows, columns, [{ column: "preis", dir: "desc" }]).map((r) => r.id)).toEqual(["r4", "r1", "r2", "r3"]);
  });
  it("sortiert Text deutsch und stabil, ohne Angabe bleibt die Reihenfolge", () => {
    expect(sortRows(rows, columns, [{ column: "c1", dir: "asc" }]).map((r) => r.id)).toEqual(["r4", "r3", "r1", "r2"]);
    expect(sortRows(rows, columns, [])).toBe(rows);
  });
});

describe("Filter", () => {
  it("bietet Operatoren passend zum Typ an", () => {
    expect(opsFor({ kind: "text" })).toContain("contains");
    expect(opsFor({ kind: "integer" })).toContain("gte");
    expect(opsFor({ kind: "integer" })).not.toContain("contains");
    expect(opsFor({ kind: "boolean" })).toEqual(["eq", "ne", "in", "is_null"]);
  });

  it("wandelt Eingaben in typisierte Werte, Ausdrücke bleiben Text", () => {
    expect(filterValue("gte", "10,5", { kind: "number", decimals: 2 })).toBe(10.5);
    expect(filterValue("in", "1, 2,3", { kind: "integer" })).toEqual([1, 2, 3]);
    expect(filterValue("is_null", "egal", { kind: "text" })).toBeNull();
    expect(filterValue("eq", "{{ run.input.x }}", { kind: "integer" })).toBe("{{ run.input.x }}");
    expect(hasExpression(["a", "{{x}}"])).toBe(true);
  });

  it("lässt unvollständige Bedingungen weg und löst Keys auf IDs auf", () => {
    const conds = activeFilters(
      [{ column: "preis", op: "gt", text: "10" }, { column: "name", op: "contains", text: "  " }, { column: "status", op: "is_null", text: "" }, { column: "gibtsnicht", op: "eq", text: "x" }],
      columns,
    );
    expect(conds).toEqual([{ column: "c2", op: "gt", value: 10 }, { column: "c3", op: "is_null", value: null }]);
  });

  it("legt das Serverergebnis auf den Live-Stand: Reihenfolge vom Server, Gelöschtes entfällt", () => {
    const live = [row("r1", { c1: "neu" }), row("r2", {})];
    expect(overlayRows(["r2", "gone", "r1"], live)).toEqual([live[1], live[0]]);
  });

  it("meldet den 422 bei Ausdrücken im Filter mit dem Grund des Servers", () => {
    const withExpr = [{ column: "c1", op: "eq" as const, value: "{{ run.id }}" }];
    expect(queryErrorText(422, "x", withExpr)).toBe("Der Filter oder sein Ausdruck ist ungültig: x");
    expect(queryErrorText(422, "Spalte unbekannt", [{ column: "c1", op: "eq", value: 1 }])).toBe("Der Filter ist ungültig: Spalte unbekannt");
    expect(queryErrorText(500, "kaputt", [])).toMatch(/kaputt/);
  });
});

describe("Ops", () => {
  it("baut Zellen-, Einfüge- und Löschops", () => {
    expect(updateCellOp("t", "r", "c", 5)).toEqual({ op: "row.update", table: "t", row: "r", values: { c: 5 } });
    expect(insertRowOp("t", "r", { c: 1 }, "r0")).toEqual({ op: "row.insert", table: "t", rows: [{ id: "r", values: { c: 1 }, after: "r0" }] });
    expect(deleteRowOp("t", "r")).toEqual({ op: "row.delete", table: "t", rows: ["r"] });
    expect(insertedRowIds([{ op: "row.update" }, { op: "row.insert", rows: [{ id: "a" }, { id: "b" }] }])).toEqual(["a", "b"]);
  });

  it("liest Feldfehler aus details.errors", () => {
    expect(fieldErrors({ message: "m", details: { errors: { preis: "zu klein" } } })).toEqual({ fields: { preis: "zu klein" }, message: "m" });
    expect(fieldErrors(undefined).fields).toEqual({});
  });
});

// ── Zusammenspiel mit dem Sync-Store ─────────────────────────────────────────

class FakeTransport implements Transport {
  sent: WsClientMessage[] = [];
  onMessage: (m: WsServerMessage) => void = () => {};
  onStatus: (s: ConnectionStatus) => void = () => {};
  onUnauthorized = () => {};
  connect() {}
  close() {}
  send(m: WsClientMessage) {
    this.sent.push(m);
    return true;
  }
  push(m: unknown) {
    this.onMessage(m as WsServerMessage);
  }
}

const ANNA = { type: "user" as const, id: "usr_anna", name: "Anna" };
const BEN = { type: "user" as const, id: "usr_ben", name: "Ben" };

const tableSnapshot = {
  table: {
    id: "tbl_1", key: "artikel", name: "Artikel", display_column: null, version: 1,
    columns: [
      { id: "c1", key: "name", name: "Name", type: { kind: "text" }, required: false, unique: false, position: "a0" },
      { id: "c2", key: "preis", name: "Preis", type: { kind: "currency", currency: "EUR" }, required: false, unique: false, position: "a1" },
    ],
  },
  rows: [{ id: "r1", table_id: "tbl_1", position: "a0", version: 1, values: { c1: "Stuhl", c2: 30 } }],
};

describe("Tabelle im Sync-Store", () => {
  const setup = () => {
    const t = new FakeTransport();
    const s = createSyncStore(t);
    s.subscribe("table:tbl_1");
    t.push({ type: "snapshot", channel: "table:tbl_1", seq: 5, data: tableSnapshot });
    const rows = () => s.store.getState().channels["table:tbl_1"].view.tables[0].rows as TRow[];
    return { t, s, rows };
  };

  it("zeigt eine Zelländerung sofort, noch vor dem ack", () => {
    const { t, s, rows } = setup();
    void s.submit([updateCellOp("tbl_1", "r1", "c2", 42)]).catch(() => undefined);
    expect(rows()[0].values.c2).toBe(42);
    expect(t.sent.at(-1)).toMatchObject({ type: "ops" });
  });

  it("nimmt die Änderung zurück, wenn der Server ablehnt", async () => {
    const { t, s, rows } = setup();
    const p = s.submit([updateCellOp("tbl_1", "r1", "c2", 42)], { batchId: "bat_x" });
    t.push({ type: "reject", batch_id: "bat_x", error: { code: "VALIDATION", message: "nein", details: { errors: { preis: "zu hoch" } } } });
    await expect(p).rejects.toMatchObject({ error: { details: { errors: { preis: "zu hoch" } } } });
    expect(rows()[0].values.c2).toBe(30);
  });

  it("zeigt neue Zeilen anderer live und meldet sie als Ereignis (Hervorhebung)", () => {
    const { t, s, rows } = setup();
    const seen: string[] = [];
    s.listen("table:tbl_1", (e) => e.type === "ops" && seen.push(...insertedRowIds(e.ops)));
    t.push({
      type: "ops", channel: "table:tbl_1", seq: 6, batch_id: "bat_ben", actor: BEN,
      ops: [{ op: "row.insert", table: "tbl_1", rows: [{ id: "r2", values: { c1: "Tisch" } }] }],
    });
    expect(rows().map((r) => r.id)).toEqual(["r1", "r2"]);
    expect(seen).toEqual(["r2"]);
    expect(s.store.getState().channels["table:tbl_1"].authors.r2).toEqual(BEN);
  });

  it("merged gleichzeitige Änderungen verschiedener Zellen derselben Zeile", () => {
    const { t, s, rows } = setup();
    void s.submit([updateCellOp("tbl_1", "r1", "c1", "Sessel")]).catch(() => undefined);
    t.push({ type: "ops", channel: "table:tbl_1", seq: 6, batch_id: "bat_a", actor: ANNA, ops: [updateCellOp("tbl_1", "r1", "c2", 99)] });
    expect(rows()[0].values).toMatchObject({ c1: "Sessel", c2: 99 });
  });

  it("legt eine Zeile optimistisch an und löscht sie wieder", () => {
    const { s, rows } = setup();
    void s.submit([insertRowOp("tbl_1", "r9", { c1: "Neu" }, "r1")]).catch(() => undefined);
    expect(rows().map((r) => r.id)).toEqual(["r1", "r9"]);
    void s.submit([deleteRowOp("tbl_1", "r9")]).catch(() => undefined);
    expect(rows().map((r) => r.id)).toEqual(["r1"]);
  });
});
