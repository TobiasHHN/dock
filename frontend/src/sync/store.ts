// Sync-Store (Task 2.3, L 7.4, T 5.3): ein Zustand-Store für alle abonnierten Kanäle.
//
//   eigene Änderung → Batch lokal anwenden (falls nachbildbar), an `pending` hängen, senden
//   fremde Ops      → auf `confirmed` anwenden, `view` = confirmed + pending neu berechnen
//   eigene Ops      → kommen mit derselben batch_id zurück (seq bleibt lückenlos) und wandern in `confirmed`
//   ack             → Batch ist bestätigt; Kanäle, deren Echo schon da ist, sind fertig
//   reject          → Batch verwerfen, `view` neu berechnen, Hinweis anzeigen
//   Reconnect       → alle Kanäle mit `since` neu abonnieren, unbestätigte Batches erneut senden (batch_id
//                     macht Wiederholungen ungefährlich)
//
// Komponenten lesen nur `view` (über `useChannel`) und schreiben nur über `submit`.

import { useEffect } from "react";
import { ulid } from "ulid";
import { useStore } from "zustand";
import { createStore } from "zustand/vanilla";
import type { Actor, ApiError, Op, OpBatch, WsServerMessage } from "../api";
import { OpError } from "./apply";
import {
  type Pending, applyToChannel, channelsFor, computeView, fromSnapshot, isOptimistic, parseChannel,
} from "./core";
import { type ConnectionStatus, SocketTransport, type Transport } from "./socket";
import type { Json } from "./tableRules";

export type PresenceEntry = { actor: Actor; state: { editing?: string | null; cursor?: Json } };

export type ChannelState = {
  seq: number | null; // null: Snapshot wird erwartet
  confirmed: Json;
  view: Json;
  status: "loading" | "ready" | "error";
  error?: ApiError;
  presence: PresenceEntry[];
  /** Letzter Autor je Objekt-ID (Block, Zeile), aus eingehenden Ops (L 7.1: Agenten als Autor sichtbar). */
  authors: Record<string, Actor>;
};

export type BatchAck = { batch_id: string; seq: Record<string, number>; results: Record<string, Json> };

export class BatchRejected extends Error {
  constructor(public error: ApiError, public batchId: string) {
    super(error.message);
  }
}

type Waiter = { resolve: (a: BatchAck) => void; reject: (e: BatchRejected) => void };
type PendingFull = Pending & { ackSeq?: Record<string, number> };

export type SyncState = {
  status: ConnectionStatus;
  channels: Record<string, ChannelState>;
  pending: PendingFull[];
};

export type SubmitOptions = { base?: Record<string, number>; batchId?: string };

export const newId = (prefix: string) => `${prefix}_${ulid()}`;

const UNSUBSCRIBE_DELAY = 1500; // verhindert Ab-/Anmelden bei schnellen Seitenwechseln und StrictMode

/** Ids, deren Autor wir uns merken (Blöcke, Zeilen). */
function touchedIds(op: Json): string[] {
  const nodeIds = (n: Json): string[] => [n.id, ...(n.children ?? []).flatMap(nodeIds)];
  if (op.op === "block.insert") return nodeIds(op.block);
  if (typeof op.block === "string") return [op.block];
  if (op.op === "row.insert") return (op.rows ?? []).map((r: Json) => r.id);
  if (typeof op.row === "string") return [op.row];
  return [];
}

export type ChannelEvent =
  | { type: "ops"; batch_id: string; actor: Actor; ops: Json[] }
  | { type: "snapshot" };

export function createSyncStore(transport: Transport) {
  const store = createStore<SyncState>(() => ({ status: "idle", channels: {}, pending: [] }));
  const refs = new Map<string, number>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const waiters = new Map<string, Waiter>();
  let rejectListener: (e: BatchRejected) => void = () => {};
  const listeners = new Map<string, Set<(e: ChannelEvent) => void>>();
  const emit = (channel: string, e: ChannelEvent) => listeners.get(channel)?.forEach((fn) => fn(e));

  const get = () => store.getState();
  const setChannel = (channel: string, patch: Partial<ChannelState>) =>
    store.setState((s) => (s.channels[channel] ? { channels: { ...s.channels, [channel]: { ...s.channels[channel], ...patch } } } : s));

  function recompute(channels: Iterable<string>) {
    const s = get();
    const next = { ...s.channels };
    for (const c of channels) {
      const ch = next[c];
      if (!ch || ch.seq === null) continue;
      next[c] = { ...ch, view: computeView(c, ch.confirmed, s.pending) };
    }
    store.setState({ channels: next });
  }

  function finishPending() {
    store.setState((s) => ({ pending: s.pending.filter((p) => !(p.acked && p.waiting.size === 0)) }));
  }

  function sendSubscribe(channel: string, since?: number | null) {
    transport.send(since === null || since === undefined ? { type: "subscribe", channel } : { type: "subscribe", channel, since });
  }

  function requestSnapshot(channel: string) {
    setChannel(channel, { seq: null });
    sendSubscribe(channel);
  }

  function blockDoc(block: string): string | undefined {
    for (const [c, ch] of Object.entries(get().channels)) {
      if (!c.startsWith("doc:")) continue;
      if ((ch.view?.documents?.[0]?.blocks ?? []).some((b: Json) => b.id === block)) return c.slice(4);
    }
    return undefined;
  }

  function tableId(ref: string): string {
    if (ref.startsWith("tbl_")) return ref;
    const ws = get().channels["workspace"]?.view;
    return ws?.tables?.find((t: Json) => t.key === ref)?.id ?? ref;
  }

  // ── Eingehende Nachrichten ─────────────────────────────────────────────────

  function onSnapshot(channel: string, seq: number, data: Json) {
    if (!get().channels[channel]) return;
    for (const p of get().pending) {
      if (p.ackSeq && p.waiting.has(channel) && (p.ackSeq[channel] ?? Infinity) <= seq) p.waiting.delete(channel);
    }
    setChannel(channel, { seq, confirmed: fromSnapshot(channel, data), status: "ready", error: undefined });
    finishPending();
    recompute([channel]);
    emit(channel, { type: "snapshot" });
  }

  function onOps(msg: Extract<WsServerMessage, { type: "ops" }>) {
    const ch = get().channels[msg.channel];
    if (!ch || ch.seq === null) return;
    if (msg.seq <= ch.seq) return; // schon gesehen
    if (msg.seq > ch.seq + 1) {
      sendSubscribe(msg.channel, ch.seq); // Lücke: ab der letzten bekannten seq nachholen
      return;
    }
    let confirmed = ch.confirmed;
    let resync = false;
    try {
      const r = applyToChannel(msg.channel, ch.confirmed, msg.ops as Json[]);
      confirmed = r.state;
      resync = r.resync;
    } catch (e) {
      if (!(e instanceof OpError)) throw e;
      console.warn(`Ops in ${msg.channel} passen nicht auf den lokalen Stand, hole Snapshot`, e);
      resync = true;
    }
    const authors = { ...ch.authors };
    for (const op of msg.ops as Json[]) for (const id of touchedIds(op)) authors[id] = msg.actor;
    const own = get().pending.find((p) => p.batch.batch_id === msg.batch_id);
    if (own) own.waiting.delete(msg.channel);
    setChannel(msg.channel, { seq: msg.seq, confirmed, authors });
    finishPending();
    emit(msg.channel, { type: "ops", batch_id: msg.batch_id, actor: msg.actor as Actor, ops: msg.ops as Json[] });
    if (resync) requestSnapshot(msg.channel);
    else recompute([msg.channel]);
  }

  function onAck(msg: Extract<WsServerMessage, { type: "ack" }>) {
    const p = get().pending.find((x) => x.batch.batch_id === msg.batch_id);
    const affected = p ? [...p.waiting] : [];
    if (p) {
      p.acked = true;
      p.ackSeq = msg.seq;
      for (const c of [...p.waiting]) {
        const ch = get().channels[c];
        const target = msg.seq[c];
        // Echo schon da (oder kommt nie, weil nicht abonniert / Kanal nicht betroffen) → fertig
        if (target === undefined || !ch || (ch.seq !== null && ch.seq >= target)) p.waiting.delete(c);
      }
      finishPending();
      recompute(affected);
    }
    const w = waiters.get(msg.batch_id);
    waiters.delete(msg.batch_id);
    w?.resolve({ batch_id: msg.batch_id, seq: msg.seq, results: msg.results ?? {} });
  }

  function onReject(msg: Extract<WsServerMessage, { type: "reject" }>) {
    const id = msg.batch_id;
    if (id.startsWith("subscribe:")) {
      setChannel(id.slice("subscribe:".length), { status: "error", error: msg.error });
      return;
    }
    if (id.startsWith("presence:")) return;
    const p = get().pending.find((x) => x.batch.batch_id === id);
    if (p) {
      store.setState((s) => ({ pending: s.pending.filter((x) => x !== p) }));
      recompute(p.waiting);
    }
    const err = new BatchRejected(msg.error, id);
    const w = waiters.get(id);
    waiters.delete(id);
    if (w) w.reject(err);
    if (p || w) rejectListener(err);
  }

  transport.onMessage = (msg) => {
    switch (msg.type) {
      case "snapshot":
        return onSnapshot(msg.channel, msg.seq, msg.data);
      case "ops":
        return onOps(msg);
      case "ack":
        return onAck(msg);
      case "reject":
        return onReject(msg);
      case "presence":
        return setChannel(msg.channel, { presence: msg.actors as PresenceEntry[] });
    }
  };

  transport.onStatus = (status) => {
    store.setState({ status });
    if (status !== "open") return;
    // Wiederverbinden: Abos mit since, dann unbestätigte Batches erneut senden
    for (const [c, ch] of Object.entries(get().channels)) sendSubscribe(c, ch.seq);
    for (const p of get().pending) if (!p.acked) p.sent = transport.send({ type: "ops", batch: p.batch });
  };

  // ── Öffentliche API ────────────────────────────────────────────────────────

  function subscribe(channel: string) {
    const t = timers.get(channel);
    if (t) {
      clearTimeout(t);
      timers.delete(channel);
    }
    refs.set(channel, (refs.get(channel) ?? 0) + 1);
    if (get().channels[channel]) return;
    store.setState((s) => ({
      channels: { ...s.channels, [channel]: { seq: null, confirmed: null, view: null, status: "loading", presence: [], authors: {} } },
    }));
    sendSubscribe(channel);
  }

  function unsubscribe(channel: string) {
    const n = (refs.get(channel) ?? 0) - 1;
    if (n > 0) {
      refs.set(channel, n);
      return;
    }
    refs.delete(channel);
    timers.set(channel, setTimeout(() => {
      timers.delete(channel);
      if (refs.has(channel)) return;
      transport.send({ type: "unsubscribe", channel });
      store.setState((s) => {
        const next = { ...s.channels };
        delete next[channel];
        return { channels: next };
      });
    }, UNSUBSCRIBE_DELAY));
  }

  /** Schickt einen Batch. Nachbildbare Batches erscheinen sofort in `view`; das Promise endet mit ack/reject. */
  function submit(ops: Op[], opts: SubmitOptions = {}): Promise<BatchAck> {
    const batch: OpBatch = { batch_id: opts.batchId ?? newId("bat"), ops, base: opts.base ?? {} };
    const channels = channelsFor(ops as Json[], blockDoc, tableId);
    const waiting = new Set([...channels].filter((c) => get().channels[c]));
    const p: PendingFull = { batch, optimistic: isOptimistic(ops), waiting, acked: false, sent: false };
    store.setState((s) => ({ pending: [...s.pending, p] }));
    recompute(waiting);
    const promise = new Promise<BatchAck>((resolve, reject) => waiters.set(batch.batch_id, { resolve, reject }));
    p.sent = transport.send({ type: "ops", batch });
    return promise;
  }

  function sendPresence(channel: string, state: { editing?: string | null; cursor?: Json }) {
    if (get().channels[channel]?.seq === null) return;
    transport.send({ type: "presence", channel, state });
  }

  function connect(token: string) {
    transport.connect(token);
  }

  function disconnect() {
    transport.close();
    for (const t of timers.values()) clearTimeout(t);
    timers.clear();
    refs.clear();
    for (const [id, w] of waiters) w.reject(new BatchRejected({ code: "FORBIDDEN", message: "Abgemeldet" }, id));
    waiters.clear();
    store.setState({ channels: {}, pending: [], status: "idle" });
  }

  /** Ereignisse eines Kanals in Server-Reihenfolge: angewendete Ops (auch das eigene Echo) und neue Snapshots.
   *  Für Komponenten mit eigenem lokalem Stand, z. B. Textblöcke mit OT. Gibt die Abmeldung zurück. */
  function listen(channel: string, fn: (e: ChannelEvent) => void): () => void {
    if (!listeners.has(channel)) listeners.set(channel, new Set());
    listeners.get(channel)!.add(fn);
    return () => listeners.get(channel)?.delete(fn);
  }

  /** Bestätigter Stand eines Blocks (ohne eigene ausstehende Änderungen). */
  function confirmedBlock(channel: string, id: string): Json | undefined {
    return get().channels[channel]?.confirmed?.documents?.[0]?.blocks?.find((b: Json) => b.id === id);
  }

  function onRejected(fn: (e: BatchRejected) => void) {
    rejectListener = fn;
  }

  /** Server hat das Token abgelehnt (WebSocket-Code 4401). */
  function onUnauthorized(fn: () => void) {
    transport.onUnauthorized = fn;
  }

  return {
    store, subscribe, unsubscribe, submit, sendPresence, connect, disconnect, onRejected, onUnauthorized, requestSnapshot,
    parseChannel, listen, confirmedBlock,
  };
}

export type SyncStore = ReturnType<typeof createSyncStore>;

// ── Instanz für die App ──────────────────────────────────────────────────────

export const sync = createSyncStore(new SocketTransport());

export function useSync<T>(selector: (s: SyncState) => T): T {
  return useStore(sync.store, selector);
}

/** Abonniert einen Kanal, solange die Komponente lebt, und liefert seinen Zustand. */
export function useChannel(channel: string | null): ChannelState | undefined {
  useEffect(() => {
    if (!channel) return;
    sync.subscribe(channel);
    return () => sync.unsubscribe(channel);
  }, [channel]);
  return useSync((s) => (channel ? s.channels[channel] : undefined));
}

export const submit = (ops: Op[], opts?: SubmitOptions) => sync.submit(ops, opts);
