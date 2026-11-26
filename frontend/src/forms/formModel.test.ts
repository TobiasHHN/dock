// Logik der Formular-Blöcke (Task 3.4): Buttons und Sichtbarkeit (L 4.3), Fehlerpfade (L 4.6), Vorprüfung, Ops.
import { describe, expect, it } from "vitest";
import type { FlatBlock } from "../documents/blockOps";
import {
  type ButtonDef, canAct, clearField, draftScope, draftSetOp, effectiveButtons, errorsOf, formOf, formState, hasErrors,
  inputBlocks, inputType, itemInsertOp, noErrors, resolveField, splitErrors, submitOp, validateLocal, visibleButtons,
} from "./formModel";

let n = 0;
const blk = (id: string, type: string, parent: string | null, props: object = {}): FlatBlock =>
  ({ id, type, parent_id: parent, position: `a${String(n++).padStart(3, "0")}`, props, version: 1 }) as FlatBlock;

const blocks: FlatBlock[] = [
  blk("form", "form", null, { actions: [{ key: "order", type: "create_row", table: "t", values: {} }, { key: "items", type: "create_rows", table: "u", for_each: "x", values: {} }] }),
  blk("f_name", "field", "form", { key: "name", label: "Name", input: "text", required: true }),
  blk("quote", "quote", "form"),
  blk("f_kst", "field", "quote", { key: "kst", label: "Kostenstelle", input: "select" }),
  blk("li", "line_items", "form", {
    key: "artikel", label: "Artikel", min_rows: 1,
    columns: [{ key: "bez", label: "Bezeichnung", required: true }, { key: "preis", input: "currency" }],
  }),
  blk("p", "paragraph", null, { content: [] }),
  blk("empty", "form", null, {}),
  blk("approve", "form", null, { buttons: [{ id: "ok", label: "Genehmigen", outcome: "approved" }, { id: "no", label: "Ablehnen", style: "danger", require: ["grund"] }] }),
  blk("f_grund", "field", "approve", { key: "grund", label: "Grund", input: "textarea" }),
];

const ANNA = { id: "usr_anna", roles: ["einkauf"] };
const BEN = { id: "usr_ben", roles: ["mitarbeiter"] };

describe("Aufbau", () => {
  it("findet Eingaben rekursiv in Dokumentreihenfolge und das umgebende Formular", () => {
    expect(inputBlocks(blocks, "form").map((b) => b.id)).toEqual(["f_name", "f_kst", "li"]);
    expect(formOf(blocks, "f_kst")?.id).toBe("form");
    expect(formOf(blocks, "p")).toBeUndefined();
  });

  it("Buttons: Speichern mit allen Actions, keine ohne Felder, explizite haben Vorrang (L 4.3)", () => {
    const [save] = effectiveButtons(blocks[0], blocks);
    expect(save).toMatchObject({ id: "save", label: "Speichern", actions: ["order", "items"] });
    expect(effectiveButtons(blocks.find((b) => b.id === "empty")!, blocks)).toEqual([]);
    expect(effectiveButtons(blocks.find((b) => b.id === "approve")!, blocks).map((b) => b.id)).toEqual(["ok", "no"]);
  });
});

describe("Fehlerpfade des Servers (Task 3.3)", () => {
  it("ordnet Feld, Zeilenliste, Zeile.Spalte und actions.* zu", () => {
    const e = splitErrors({
      name: "Pflicht", artikel: "mindestens 1", "artikel[2].preis": "keine Zahl", "actions.order.values.col_x": "Spalte unbekannt", button: "unbekannter Button",
    }, new Set(["name", "artikel"]));
    expect(e.fields).toEqual({ name: "Pflicht", artikel: "mindestens 1" });
    expect(e.items).toEqual({ artikel: { 2: { preis: "keine Zahl" } } });
    expect(e.general).toEqual(["actions.order.values.col_x: Spalte unbekannt", "button: unbekannter Button"]);
  });

  it("liest details.errors einer abgelehnten Antwort", () => {
    expect(errorsOf({ code: "VALIDATION", message: "m", details: { errors: { name: "x" } } })).toEqual({ name: "x" });
    expect(errorsOf({ code: "FORBIDDEN", message: "m", details: { form_block: "f" } })).toBeNull();
  });
});

describe("Sichtbarkeit (L 4.3)", () => {
  const buttons: ButtonDef[] = [{ id: "save", label: "Speichern" }];
  const task = { id: "tsk_1", step: "erfassen", status: "open", candidate_users: ["usr_anna"], candidate_roles: [] };
  const run = { status: "active", current_step: "erfassen" };

  it("ohne Workflow: angemeldet und nicht schreibgeschützt reicht", () => {
    expect(visibleButtons(buttons, formState({ me: BEN })).length).toBe(1);
    expect(visibleButtons(buttons, formState({ me: null }))).toEqual([]);
    expect(visibleButtons(buttons, formState({ me: BEN, readOnly: true }))).toEqual([]);
  });

  it("Schritt-Dokument außerhalb eines Runs: ausfüllbar, aber keine Buttons (wie buttons_allowed im Server)", () => {
    const st = formState({ me: BEN, owner: { workflow: "wf_1", step: "erfassen" } });
    expect(st).toMatchObject({ fillable: true, buttons: false });
    expect(visibleButtons(buttons, st)).toEqual([]);
  });

  it("im Run: nur der Zuständige im aktuellen Schritt eines aktiven Runs", () => {
    const base = { run: "run_1", step: "erfassen", info: { loading: false, run, task } };
    expect(formState({ ...base, me: ANNA }).fillable).toBe(true);
    const ben = formState({ ...base, me: BEN });
    expect(ben.fillable).toBe(false);
    expect(ben.reason).toMatch(/nicht zuständig/);
    expect(formState({ ...base, me: ANNA, step: "genehmigung" }).fillable).toBe(false);
    expect(formState({ ...base, me: ANNA, info: { loading: false, run: { ...run, status: "completed" }, task } }).fillable).toBe(false);
    expect(formState({ ...base, me: ANNA, info: { loading: false, run: { ...run, waiting_subrun: true }, task } }).fillable).toBe(false);
    expect(formState({ ...base, me: ANNA, info: { loading: true } }).fillable).toBe(false);
  });

  it("erkennt Zuständige über Rolle, Übernahme oder can_act", () => {
    expect(canAct({ candidate_roles: ["chef"] }, { id: "u", roles: ["chef"] })).toBe(true);
    expect(canAct({ candidate_users: ["u"], claimed_by_id: "x" }, { id: "u", roles: [] })).toBe(false);
    expect(canAct({ can_act: true, candidate_users: [] }, { id: "u", roles: [] })).toBe(true);
  });
});

describe("Felder", () => {
  it("übernimmt Typ, Label und Optionen aus der gebundenen Spalte, Eigenes hat Vorrang", () => {
    const col = { name: "Menge", required: true, type: { kind: "integer" } };
    expect(resolveField({ key: "m", column: "col_m" }, col)).toMatchObject({ input: "integer", label: "Menge", required: true });
    expect(resolveField({ key: "m", label: "Anzahl", input: "number" }, col)).toMatchObject({ input: "number", label: "Anzahl" });
    expect(resolveField({ key: "s", column: "c" }, { name: "S", type: { kind: "select", options: [{ id: "a", label: "A" }] } }).options).toHaveLength(1);
    expect(resolveField({ key: "x" })).toMatchObject({ input: "text", label: "x", required: false });
  });

  it("Eingabearten bilden auf Spaltentypen ab", () => {
    expect(inputType("textarea")).toEqual({ kind: "long_text" });
    expect(inputType("select", [{ id: "a", label: "A" }])).toEqual({ kind: "select", options: [{ id: "a", label: "A" }] });
  });
});

describe("Fehler am Feld (L 4.6)", () => {
  it("ordnet Pfade nach Feld, Zeile und Spalte; Unbekanntes kommt in general", () => {
    const e = splitErrors({ name: "Pflicht", "artikel[2].preis": "keine Zahl", artikel: "zu wenige", "": "?", ding: "x" }, new Set(["name", "artikel"]));
    expect(e.fields).toEqual({ name: "Pflicht", artikel: "zu wenige" });
    expect(e.items).toEqual({ artikel: { 2: { preis: "keine Zahl" } } });
    expect(e.general).toEqual([": ?", "ding: x"]);
    expect(hasErrors(e)).toBe(true);
    expect(hasErrors(noErrors())).toBe(false);
  });

  it("liest Fehler aus reject-Details und aus der Antwort", () => {
    expect(errorsOf({ code: "VALIDATION", message: "m", details: { errors: { a: "b" } } })).toEqual({ a: "b" });
    expect(errorsOf({ errors: { a: "b" } })).toEqual({ a: "b" });
    expect(errorsOf({ "0": { errors: { a: "b" } } })).toEqual({ a: "b" });
    expect(errorsOf({ "0": { id: "row_1" } })).toBeNull();
    expect(errorsOf({ message: "x" })).toBeNull();
  });

  it("entfernt nur den bearbeiteten Fehler", () => {
    const e = splitErrors({ name: "a", kst: "b", "artikel[0].preis": "c", "artikel[0].bez": "d" });
    expect(clearField(e, "name").fields).toEqual({ kst: "b" });
    expect(clearField(e, "artikel", { index: 0, column: "preis" }).items.artikel[0]).toEqual({ bez: "d" });
    expect(clearField(e, "unbekannt")).toBe(e);
  });

  it("prüft Pflichtfelder, min_rows und Pflichtspalten vor dem Absenden", () => {
    const inputs = inputBlocks(blocks, "form");
    const save: ButtonDef = { id: "save", label: "Speichern" };
    const empty = validateLocal(inputs, {}, save);
    expect(empty.fields).toEqual({ name: "Name ist ein Pflichtfeld", artikel: "Mindestens 1 Zeile erforderlich" });
    const rows = validateLocal(inputs, { name: "x", artikel: [{ id: "i1", position: "a", values: { preis: 3 } }, { id: "i2", position: "b", values: { bez: "ok" } }] }, save);
    expect(rows.fields).toEqual({});
    expect(rows.items).toEqual({ artikel: { 0: { bez: "Bezeichnung ist ein Pflichtfeld" } } });
    expect(hasErrors(validateLocal(inputs, { name: "x", artikel: [{ id: "i", position: "a", values: { bez: "a" } }] }, save))).toBe(false);
  });

  it("button.require macht Felder nur für diesen Button zur Pflicht, validate=false prüft nichts", () => {
    const inputs = inputBlocks(blocks, "approve");
    expect(validateLocal(inputs, {}, { id: "ok", label: "Genehmigen" }).fields).toEqual({});
    expect(validateLocal(inputs, {}, { id: "no", label: "Ablehnen", require: ["grund"] }).fields).toEqual({ grund: "Grund ist ein Pflichtfeld" });
    expect(hasErrors(validateLocal(inputBlocks(blocks, "form"), {}, { id: "x", label: "x", validate: false }))).toBe(false);
  });

  it("ein nicht gesetzter Haken zählt bei Pflicht als beantwortet, nur nie Berührtes nicht", () => {
    const b = [blk("c", "field", "x", { key: "ok", label: "OK", input: "boolean", required: true })];
    const btn: ButtonDef = { id: "s", label: "s" };
    expect(hasErrors(validateLocal(b, { ok: false }, btn))).toBe(false);
    expect(hasErrors(validateLocal(b, {}, btn))).toBe(true);
  });
});

describe("Ops", () => {
  it("baut Entwurfs- und Submit-Ops mit Scope", () => {
    expect(draftScope("run_1", "usr_1")).toEqual({ run: "run_1" });
    expect(draftScope(undefined, "usr_1")).toEqual({ user: "usr_1" });
    expect(draftSetOp("f", { user: "u" }, "name", "x")).toEqual({ op: "draft.set", form_block: "f", scope: { user: "u" }, key: "name", value: "x" });
    expect(itemInsertOp("f", { run: "r" }, "artikel", "itm_1", "itm_0")).toMatchObject({ op: "draft.item_insert", item: { id: "itm_1", values: {} }, after: "itm_0" });
    expect(submitOp("f", "save", "sub_1", "run_1")).toEqual({ op: "form.submit", submission_id: "sub_1", form_block: "f", button: "save", run: "run_1" });
    expect(submitOp("f", "save", "sub_1")).not.toHaveProperty("run");
  });

  it("Vier-Augen-Prinzip: excluded sperrt die Person selbst bei passender Rolle", () => {
    const task = { step: "genehmigung", candidate_roles: ["chef"], excluded: ["usr_ben"] };
    expect(formState({ me: { id: "usr_ben", roles: ["chef"] }, run: "run_1", step: "genehmigung", info: { loading: false, run: { status: "active", current_step: "genehmigung" }, task } }).fillable).toBe(false);
  });
});
