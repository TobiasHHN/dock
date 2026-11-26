// Entwürfe im Sync-Store (Task 3.4, L 4.4, L 7.6): draft.*-Ops auf run:<id> und user:<id>, optimistisch und live.
import { beforeEach, describe, expect, it } from "vitest";
import type { WsClientMessage, WsServerMessage } from "../api";
import { applyDraftOps, findDraft, scopeKey, sortedItems } from "./drafts";
import type { ConnectionStatus, Transport } from "./socket";
import { createSyncStore, type SyncStore } from "./store";
import { draftSetOp, itemDeleteOp, itemInsertOp, itemUpdateOp, submitOp } from "../forms/formModel";

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

const BEN = { type: "user" as const, id: "usr_ben", name: "Ben" };
const RUN = { run: "run_1" };

describe("applyDraftOps", () => {
  const base = { run: { id: "run_1" }, drafts: [] as unknown[] };

  it("scopeKey versteht Dict und Text", () => {
    expect(scopeKey({ run: "run_1" })).toBe("run:run_1");
    expect(scopeKey({ user: "usr_1" })).toBe("user:usr_1");
    expect(scopeKey("run:run_9")).toBe("run:run_9");
    expect(scopeKey({})).toBe("");
  });

  it("draft.set legt den Entwurf an und überschreibt Werte, ohne den Rest des Kanals anzutasten", () => {
    const a = applyDraftOps(base, "run:run_1", [draftSetOp("f", RUN, "name", "A"), draftSetOp("f", RUN, "kst", "K1")]);
    const b = applyDraftOps(a, "run:run_1", [draftSetOp("f", RUN, "name", "B")]);
    expect(findDraft(b, "f", "run:run_1")?.values).toEqual({ name: "B", kst: "K1" });
    expect(b.run).toEqual({ id: "run_1" });
    expect(base.drafts).toEqual([]); // Eingabe bleibt unverändert
  });

  it("findet Entwürfe aus Snapshots mit Scope als Text", () => {
    const s = { drafts: [{ form_block: "f", scope: "run:run_1", values: { name: "X" }, version: 3 }] };
    expect(findDraft(s, "f", "run:run_1")?.values).toEqual({ name: "X" });
    expect(applyDraftOps(s, "run:run_1", [draftSetOp("f", RUN, "name", "Y")]).drafts[0].version).toBe(4);
  });

  it("Zeilen: einfügen an der richtigen Stelle, ändern nur übergebene Spalten, löschen", () => {
    let s: unknown = base;
    s = applyDraftOps(s, "run:run_1", [
      itemInsertOp("f", RUN, "artikel", "i1"),
      itemInsertOp("f", RUN, "artikel", "i3", "i1"),
      itemInsertOp("f", RUN, "artikel", "i2", "i1"),
    ]);
    expect(sortedItems(findDraft(s, "f", "run:run_1")!.values.artikel).map((i) => i.id)).toEqual(["i1", "i2", "i3"]);
    s = applyDraftOps(s, "run:run_1", [itemUpdateOp("f", RUN, "artikel", "i2", { bez: "Stift" }), itemUpdateOp("f", RUN, "artikel", "i2", { preis: 2 })]);
    expect(sortedItems(findDraft(s, "f", "run:run_1")!.values.artikel)[1].values).toEqual({ bez: "Stift", preis: 2 });
    s = applyDraftOps(s, "run:run_1", [itemDeleteOp("f", RUN, "artikel", "i1"), itemInsertOp("f", RUN, "artikel", "i2")]);
    expect(sortedItems(findDraft(s, "f", "run:run_1")!.values.artikel).map((i) => i.id)).toEqual(["i2", "i3"]);
  });

  it("ignoriert Ops fremder Scopes", () => {
    const s = applyDraftOps(base, "run:run_1", [draftSetOp("f", { run: "run_2" }, "name", "X")]);
    expect(s).toBe(base);
  });
});

describe("Entwürfe im Sync-Store", () => {
  let t: FakeTransport;
  let s: SyncStore;
  const drafts = (channel = "run:run_1") => s.store.getState().channels[channel].view.drafts;

  beforeEach(() => {
    t = new FakeTransport();
    s = createSyncStore(t);
    s.subscribe("run:run_1");
    t.push({ type: "snapshot", channel: "run:run_1", seq: 3, data: { run: { id: "run_1" }, task: null, events: [], drafts: [{ form_block: "f", scope: "run:run_1", values: { name: "Anna" }, version: 1 }] } });
  });

  it("zeigt die eigene Eingabe sofort (optimistisch) und schickt sie ab", () => {
    void s.submit([draftSetOp("f", RUN, "name", "Anne")]).catch(() => undefined);
    expect(findDraft(s.store.getState().channels["run:run_1"].view, "f", "run:run_1")?.values.name).toBe("Anne");
    expect(t.sent.at(-1)).toMatchObject({ type: "ops" });
  });

  it("zeigt die Eingabe anderer live, ohne neuen Snapshot zu holen", () => {
    const before = t.sent.length;
    t.push({ type: "ops", channel: "run:run_1", seq: 4, batch_id: "bat_b", actor: BEN, ops: [draftSetOp("f", RUN, "kst", "K7")] });
    t.push({ type: "ops", channel: "run:run_1", seq: 5, batch_id: "bat_c", actor: BEN, ops: [itemInsertOp("f", RUN, "artikel", "i1", undefined, { bez: "Papier" })] });
    const d = findDraft(s.store.getState().channels["run:run_1"].view, "f", "run:run_1")!;
    expect(d.values.kst).toBe("K7");
    expect(d.values.artikel[0].values.bez).toBe("Papier");
    expect(d.values.name).toBe("Anna");
    expect(t.sent.length).toBe(before); // kein subscribe für einen Snapshot
    expect(drafts()).toHaveLength(1);
  });

  it("eigenes Echo nach dem ack ersetzt die vorläufige Eingabe ohne Doppelung", async () => {
    const p = s.submit([itemInsertOp("f", RUN, "artikel", "i1")], { batchId: "bat_x" });
    t.push({ type: "ack", batch_id: "bat_x", seq: { "run:run_1": 4 }, results: {} });
    t.push({ type: "ops", channel: "run:run_1", seq: 4, batch_id: "bat_x", actor: BEN, ops: [itemInsertOp("f", RUN, "artikel", "i1")] });
    await p;
    expect(findDraft(s.store.getState().channels["run:run_1"].view, "f", "run:run_1")!.values.artikel).toHaveLength(1);
    expect(s.store.getState().pending).toHaveLength(0);
  });

  it("nimmt eine abgelehnte Eingabe zurück", async () => {
    const p = s.submit([draftSetOp("f", RUN, "name", "Zu lang")], { batchId: "bat_r" });
    t.push({ type: "reject", batch_id: "bat_r", error: { code: "FORBIDDEN", message: "nein" } });
    await expect(p).rejects.toBeTruthy();
    expect(findDraft(s.store.getState().channels["run:run_1"].view, "f", "run:run_1")!.values.name).toBe("Anna");
  });

  it("Entwürfe ohne Run liegen im Kanal user:<id>, daneben bleiben die Aufgaben erhalten", () => {
    s.subscribe("user:usr_1");
    t.push({ type: "snapshot", channel: "user:usr_1", seq: 1, data: { tasks: [{ id: "tsk_1" }], runs: [], notifications: [] } });
    void s.submit([draftSetOp("f", { user: "usr_1" }, "name", "Ben")]).catch(() => undefined);
    const view = s.store.getState().channels["user:usr_1"].view;
    expect(findDraft(view, "f", "user:usr_1")?.values.name).toBe("Ben");
    expect(view.tasks).toEqual([{ id: "tsk_1" }]);
  });

  it("form.submit wird nicht optimistisch angewendet; andere Ops im Run-Kanal holen weiter einen Snapshot", () => {
    void s.submit([submitOp("f", "save", "sub_1", "run_1")]).catch(() => undefined);
    expect(s.store.getState().pending[0].optimistic).toBe(false);
    const before = t.sent.length;
    t.push({ type: "ops", channel: "run:run_1", seq: 4, batch_id: "bat_y", actor: BEN, ops: [submitOp("f", "save", "sub_2", "run_1")] });
    expect(t.sent.length).toBe(before + 1);
    expect(t.sent.at(-1)).toMatchObject({ type: "subscribe", channel: "run:run_1" });
  });
});
