// Simulation: ein Server (Regeln wie backend text_edit-Handler: Transformation gegen das Op-Log seit `version`)
// und mehrere Clients mit TextSync. Zufällige Eingaben, zufällige Zustellreihenfolge (pro Client FIFO, Ack und
// Echo in beliebiger Reihenfolge). Am Ende müssen alle Editoren und der Server denselben Text haben.
import { describe, expect, it } from "vitest";
import type { Actor, Op } from "../api";
import type { BatchAck, ChannelEvent } from "../sync/store";
import type { Json } from "../sync/tableRules";
import { type Edit, type Unit, applyEditUnits, fromUnits, textLength, toUnits, transform } from "../sync/textOt";
import { TextSync } from "./textSync";

const CH = "doc:d1";
const BLK = "p1";

function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

type Msg =
  | { type: "ops"; batch_id: string; actor: Actor; ops: Json[] }
  | { type: "ack"; batch_id: string; seq: Record<string, number> };

class Server {
  content: Json[] = [{ t: "text", text: "Hallo Welt" }];
  version = 1;
  seq = 0;
  log: Json[] = [];
  clients: Client[] = [];
  inbox: { from: Client; ops: Json[]; batchId: string }[] = [];

  process(i: number) {
    const [{ from, ops, batchId }] = this.inbox.splice(i, 1);
    const out: Json[] = [];
    for (const op of ops) {
      if (op.op === "text.edit") {
        let e: Edit = { from: op.from, to: op.to, insert: op.insert, marks: op.marks };
        if (op.version < this.version) e = transform(e, this.log.filter((l) => l.version >= op.version));
        const len = textLength(this.content);
        e.from = Math.min(Math.max(e.from, 0), len);
        e.to = Math.min(Math.max(e.to, e.from), len);
        this.content = fromUnits(applyEditUnits(toUnits(this.content), e));
        const logged = { ...op, ...e, version: this.version };
        this.log.push(logged);
        out.push(logged);
      }
    }
    this.version += 1;
    this.seq += 1;
    for (const c of this.clients) c.queue.push({ type: "ops", batch_id: batchId, actor: { type: "user", id: from.id } as Actor, ops: out });
    from.queue.push({ type: "ack", batch_id: batchId, seq: { [CH]: this.seq } });
  }
}

class Client {
  queue: Msg[] = [];
  units: Unit[];
  confirmed: { content: Json[]; version: number };
  seq = 0;
  listeners = new Set<(e: ChannelEvent) => void>();
  waiters = new Map<string, (a: BatchAck) => void>();
  sync: TextSync;
  private n = 0;

  constructor(readonly id: string, server: Server) {
    this.confirmed = { content: structuredClone(server.content), version: server.version };
    this.units = toUnits(server.content);
    this.sync = new TextSync(BLK, CH, {
      submit: (ops: Op[], { batchId }) => {
        server.inbox.push({ from: this, ops: ops as Json[], batchId });
        return new Promise((resolve) => this.waiters.set(batchId, resolve));
      },
      confirmedBlock: () => ({ id: BLK, version: this.confirmed.version, props: { content: this.confirmed.content } }),
      channelSeq: () => this.seq,
      listen: (_c, fn) => {
        this.listeners.add(fn);
        return () => this.listeners.delete(fn);
      },
      newId: (p) => `${p}_${this.id}_${this.n++}`,
    });
    this.sync.attach({
      getUnits: () => this.units,
      applyRemote: (edit, expected) => {
        this.units = applyEditUnits(this.units, edit);
        expect(fromUnits(this.units)).toEqual(fromUnits(expected));
      },
      setUnits: (u) => (this.units = u),
    });
  }

  type(r: () => number) {
    const len = this.units.length;
    const from = Math.floor(r() * (len + 1));
    const to = r() < 0.6 ? from : Math.min(len, from + Math.floor(r() * 4));
    const insert = r() < 0.8 ? ["a", "b", "ä", "👋", "xy"][Math.floor(r() * 5)] : "";
    const bold = r() < 0.2;
    this.units = applyEditUnits(this.units, { from, to, insert, marks: bold ? [{ from: 0, to: 9, mark: "bold" }] : [] });
    this.sync.changed();
  }

  deliver() {
    const m = this.queue.shift()!;
    if (m.type === "ops") {
      for (const op of m.ops) {
        if (op.op === "text.edit") {
          this.confirmed = { content: fromUnits(applyEditUnits(toUnits(this.confirmed.content), op as Edit)), version: op.version + 1 };
        }
      }
      if (!m.ops.length) this.confirmed = { ...this.confirmed, version: this.confirmed.version + 1 };
      this.seq += 1;
      this.listeners.forEach((fn) => fn({ type: "ops", batch_id: m.batch_id, actor: m.actor, ops: m.ops }));
    } else {
      this.waiters.get(m.batch_id)?.({ batch_id: m.batch_id, seq: m.seq, results: {} });
    }
  }
}

const text = (units: Unit[]) => JSON.stringify(fromUnits(units));
const tick = async () => {
  for (let i = 0; i < 4; i++) await Promise.resolve();
};

describe("TextSync: gleichzeitiges Tippen im selben Block", () => {
  it.each(Array.from({ length: 200 }, (_, i) => i + 1))("Lauf %i konvergiert", async (seed) => {
    const r = rng(seed);
    const server = new Server();
    const clients = ["anna", "ben", "chef"].map((id) => new Client(id, server));
    server.clients = clients;

    for (let step = 0; step < 120; step++) {
      const x = r();
      const c = clients[Math.floor(r() * clients.length)];
      if (x < 0.35) c.type(r);
      else if (x < 0.5) c.sync.flush();
      else if (x < 0.75 && server.inbox.length) server.process(Math.floor(r() * server.inbox.length));
      else if (c.queue.length) c.deliver();
      await tick();
    }
    // ausliefern, bis alles ruhig ist
    for (let guard = 0; guard < 500; guard++) {
      clients.forEach((c) => c.sync.flush());
      await tick();
      if (server.inbox.length) server.process(0);
      clients.forEach((c) => {
        while (c.queue.length) c.deliver();
      });
      await tick();
      if (!server.inbox.length && clients.every((c) => !c.queue.length && !c.sync.busy)) break;
    }
    const serverText = JSON.stringify(server.content.length ? fromUnits(toUnits(server.content)) : []);
    for (const c of clients) expect(text(c.units), c.id).toBe(serverText);
  });
});
