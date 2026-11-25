// Sync-Store gegen einen Fake-Transport (Task 2.3): optimistisch anwenden, Echo/ack, reject, fremde Ops,
// Lücken in seq, Reconnect.
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WsClientMessage, WsServerMessage } from "../api";
import type { ConnectionStatus, Transport } from "./socket";
import { createSyncStore, type SyncStore } from "./store";

class FakeTransport implements Transport {
  sent: WsClientMessage[] = [];
  open = true;
  onMessage: (m: WsServerMessage) => void = () => {};
  onStatus: (s: ConnectionStatus) => void = () => {};
  onUnauthorized = () => {};
  connect() {}
  close() {}
  send(m: WsClientMessage) {
    if (!this.open) return false;
    this.sent.push(m);
    return true;
  }
  push(m: unknown) {
    this.onMessage(m as WsServerMessage);
  }
}

const ANNA = { type: "user" as const, id: "usr_anna", name: "Anna" };
const BOT = { type: "agent" as const, id: "agt_1", on_behalf_of: "usr_ben", name: "Bens Agent" };

const para = (id: string, position: string, text: string) => ({
  id, doc_id: "doc_1", parent_id: null, position, type: "paragraph", version: 1,
  props: { content: [{ t: "text", text, marks: [] }] },
});

const docSnapshot = {
  document: { id: "doc_1", title: "Doc", version: 1 },
  blocks: [para("b1", "a0", "Eins"), para("b2", "a1", "Zwei")],
};

const text = (s: SyncStore, block: string) =>
  s.store.getState().channels["doc:doc_1"].view.documents[0].blocks.find((b: { id: string }) => b.id === block)?.props.content[0]?.text;

let t: FakeTransport;
let s: SyncStore;

beforeEach(() => {
  t = new FakeTransport();
  s = createSyncStore(t);
  s.subscribe("doc:doc_1");
  t.push({ type: "snapshot", channel: "doc:doc_1", seq: 10, data: docSnapshot });
});

const update = (block: string, value: string) => ({ op: "block.update", block, props: { content: [{ t: "text", text: value }] } });

describe("Sync-Store", () => {
  it("abonniert mit Snapshot und rendert view", () => {
    expect(t.sent[0]).toEqual({ type: "subscribe", channel: "doc:doc_1" });
    expect(text(s, "b1")).toBe("Eins");
    expect(s.store.getState().channels["doc:doc_1"].status).toBe("ready");
  });

  it("eigene Änderung erscheint sofort, ack + Echo machen sie zum Server-Stand", async () => {
    const p = s.submit([update("b1", "Neu") as never], { batchId: "bat_1" });
    expect(text(s, "b1")).toBe("Neu");
    expect(t.sent.at(-1)).toMatchObject({ type: "ops", batch: { batch_id: "bat_1" } });

    t.push({ type: "ack", batch_id: "bat_1", seq: { "doc:doc_1": 11 }, results: {} });
    await expect(p).resolves.toMatchObject({ batch_id: "bat_1" });
    expect(text(s, "b1")).toBe("Neu"); // Echo fehlt noch, Batch bleibt in pending
    expect(s.store.getState().pending).toHaveLength(1);

    t.push({ type: "ops", channel: "doc:doc_1", seq: 11, batch_id: "bat_1", actor: ANNA, ops: [update("b1", "Neu")] });
    expect(s.store.getState().pending).toHaveLength(0);
    expect(text(s, "b1")).toBe("Neu");
    expect(s.store.getState().channels["doc:doc_1"].confirmed.documents[0].blocks[0].version).toBe(2);
  });

  it("Echo vor ack: Batch ist nach dem ack erledigt", async () => {
    const p = s.submit([update("b1", "Neu") as never], { batchId: "bat_1" });
    t.push({ type: "ops", channel: "doc:doc_1", seq: 11, batch_id: "bat_1", actor: ANNA, ops: [update("b1", "Neu")] });
    t.push({ type: "ack", batch_id: "bat_1", seq: { "doc:doc_1": 11 }, results: {} });
    await p;
    expect(s.store.getState().pending).toHaveLength(0);
    expect(text(s, "b1")).toBe("Neu");
  });

  it("reject setzt den Zustand zurück und meldet den Fehler", async () => {
    const listener = vi.fn();
    s.onRejected(listener);
    const p = s.submit([update("b1", "Neu") as never], { batchId: "bat_1" });
    expect(text(s, "b1")).toBe("Neu");
    t.push({ type: "reject", batch_id: "bat_1", error: { code: "BLOCK_IN_USE", message: "Ben bearbeitet den Block" } });
    await expect(p).rejects.toMatchObject({ error: { code: "BLOCK_IN_USE" } });
    expect(text(s, "b1")).toBe("Eins");
    expect(s.store.getState().pending).toHaveLength(0);
    expect(listener).toHaveBeenCalledOnce();
  });

  it("fremde Ops werden unter die eigenen ausstehenden gelegt", () => {
    s.submit([update("b1", "Meins") as never], { batchId: "bat_1" });
    t.push({ type: "ops", channel: "doc:doc_1", seq: 11, batch_id: "bat_x", actor: BOT, ops: [update("b2", "Agent")] });
    expect(text(s, "b1")).toBe("Meins");
    expect(text(s, "b2")).toBe("Agent");
    expect(s.store.getState().channels["doc:doc_1"].authors.b2).toEqual(BOT);
    // fremder Stand allein (ohne eigene Änderung) in confirmed
    expect(s.store.getState().channels["doc:doc_1"].confirmed.documents[0].blocks[0].props.content[0].text).toBe("Eins");
  });

  it("Ops für andere Dokumente im selben Batch werden ignoriert", () => {
    t.push({
      type: "ops", channel: "doc:doc_1", seq: 11, batch_id: "bat_x", actor: ANNA,
      ops: [
        { op: "block.insert", doc: "doc_2", parent: null, block: { id: "x1", type: "paragraph", props: {} } },
        { op: "block.insert", doc: "doc_1", parent: null, after: "b1", block: { id: "b_new", type: "paragraph", props: {} } },
      ],
    });
    const blocks = s.store.getState().channels["doc:doc_1"].view.documents[0].blocks;
    expect(blocks.map((b: { id: string }) => b.id)).toEqual(["b1", "b2", "b_new"]);
  });

  it("Lücke in seq holt ab der letzten bekannten seq nach", () => {
    t.push({ type: "ops", channel: "doc:doc_1", seq: 13, batch_id: "bat_x", actor: ANNA, ops: [update("b2", "X")] });
    expect(t.sent.at(-1)).toEqual({ type: "subscribe", channel: "doc:doc_1", since: 10 });
    expect(text(s, "b2")).toBe("Zwei");
  });

  it("Reconnect abonniert mit since und sendet unbestätigte Batches erneut", () => {
    t.open = false;
    s.submit([update("b1", "Offline") as never], { batchId: "bat_1" });
    expect(text(s, "b1")).toBe("Offline");
    t.open = true;
    t.sent = [];
    t.onStatus("open");
    expect(t.sent).toEqual([
      { type: "subscribe", channel: "doc:doc_1", since: 10 },
      expect.objectContaining({ type: "ops", batch: expect.objectContaining({ batch_id: "bat_1" }) }),
    ]);
  });

  it("form.submit wird nicht optimistisch angewendet", () => {
    s.submit([{ op: "form.submit", submission_id: "sub_1", form_block: "f1", button: "save" } as never]);
    expect(s.store.getState().pending[0].optimistic).toBe(false);
  });

  it("Workspace-Liste folgt doc.create ohne Neuladen", () => {
    s.subscribe("workspace");
    t.push({ type: "snapshot", channel: "workspace", seq: 3, data: { documents: [{ id: "doc_1", title: "Doc" }], tables: [], workflows: [], roles: [] } });
    t.push({ type: "ops", channel: "workspace", seq: 4, batch_id: "bat_y", actor: BOT, ops: [{ op: "doc.create", id: "doc_2", title: "Antrag" }] });
    expect(s.store.getState().channels.workspace.view.documents.map((d: { id: string }) => d.id)).toEqual(["doc_2", "doc_1"]);
  });

  it("abgelehntes Abo setzt den Kanal auf Fehler", () => {
    s.subscribe("run:run_9");
    t.push({ type: "reject", batch_id: "subscribe:run:run_9", error: { code: "FORBIDDEN", message: "Kein Zugriff" } });
    expect(s.store.getState().channels["run:run_9"].status).toBe("error");
  });
});
