// Reine Logik des Sync-Stores (L 7.4, T 5.3), ohne WebSocket und ohne React, damit sie testbar ist.
//
// Kanalzustand = bestätigter Server-Stand (`confirmed`) + eigene ausstehende Batches. `view` ist daraus berechnet
// und das Einzige, woraus Komponenten rendern.
//
// Kanaltypen:
//   doc:<id>    confirmed = { tables: [], documents: [doc mit blocks] }   (Form wie spec/fixtures, apply.ts)
//   table:<id>  confirmed = { tables: [table mit rows], documents: [] }
//   workspace   confirmed = { documents, tables, workflows, roles }       (Listen, eigene kleine Anwendung)
//   user, run   confirmed = Snapshot-Daten; `draft.*`-Ops (Formularentwürfe, sync/drafts.ts) werden nachgebildet, bei allen
//               anderen Ops holt der Store einen frischen Snapshot (bis 4.4 die Ereignisse für diese Kanäle festlegt).

import type { Op, OpBatch } from "../api";
import { type State, UnsupportedOp, applyOps, isMirrored } from "./apply";
import { applyDraftOps, draftOpsFor, isDraftOp, scopeKey } from "./drafts";
import type { Json } from "./tableRules";

export type ChannelKind = "doc" | "table" | "run" | "user" | "workspace";

export function parseChannel(channel: string): { kind: ChannelKind; id: string } {
  const i = channel.indexOf(":");
  if (i < 0) return { kind: channel as ChannelKind, id: "" };
  return { kind: channel.slice(0, i) as ChannelKind, id: channel.slice(i + 1) };
}

export type WorkspaceData = { documents: Json[]; tables: Json[]; workflows: Json[]; roles: Json[] };

/** Snapshot-Daten (SnapshotDoc, SnapshotTable, …) in den Kanalzustand umwandeln. */
export function fromSnapshot(channel: string, data: Json): Json {
  const { kind } = parseChannel(channel);
  if (kind === "doc") return { tables: [], documents: [{ ...data.document, blocks: data.blocks ?? [] }] } satisfies State;
  if (kind === "table") return { tables: [{ ...data.table, rows: data.rows ?? [] }], documents: [] } satisfies State;
  if (kind === "workspace")
    return { documents: data.documents ?? [], tables: data.tables ?? [], workflows: data.workflows ?? [], roles: data.roles ?? [] };
  return data;
}

/** Ergebnis: neuer Zustand, oder `resync`, wenn der Client die Ops nicht nachbilden kann. */
export type ApplyResult = { state: Json; resync: boolean };

const blockIdsOf = (node: Json): string[] => [node.id, ...(node.children ?? []).flatMap(blockIdsOf)];

/** Nur die Ops, die diesen Kanal betreffen (ein Batch wird in jedem betroffenen Kanal vollständig verteilt). */
export function relevantOps(channel: string, state: Json, ops: Json[]): { ops: Json[]; unknown: boolean } {
  const { kind, id } = parseChannel(channel);
  const out: Json[] = [];
  let unknown = false;
  if (kind === "doc") {
    const known = new Set<string>((state?.documents?.[0]?.blocks ?? []).map((b: Json) => b.id));
    for (const op of ops) {
      let hit = false;
      if (op.op === "doc.create") hit = op.id === id;
      else if (op.op?.startsWith("doc.") || op.op === "block.insert") hit = op.doc === id;
      else if (typeof op.block === "string") hit = known.has(op.block);
      if (!hit) continue;
      if (op.op === "block.insert") blockIdsOf(op.block).forEach((b) => known.add(b));
      if (!isMirrored(op.op) || (op.op === "doc.create" && op.markdown)) unknown = true;
      out.push(op);
    }
  } else if (kind === "table") {
    for (const op of ops) {
      const hit = op.op === "table.create" ? op.id === id : op.table === id && /^(table|column|row)\./.test(op.op);
      if (hit) out.push(op);
    }
  }
  return { ops: out, unknown };
}

function applyWorkspace(state: WorkspaceData, ops: Json[]): WorkspaceData {
  const s: WorkspaceData = {
    documents: [...state.documents], tables: [...state.tables], workflows: [...state.workflows], roles: [...state.roles],
  };
  const upd = (list: Json[], ref: string, patch: Json) =>
    list.map((x) => (x.id === ref || (x.key && x.key === ref) ? { ...x, ...patch } : x));
  const del = (list: Json[], ref: string) => list.filter((x) => x.id !== ref && !(x.key && x.key === ref));
  const defined = (o: Json) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== null));
  for (const op of ops) {
    switch (op.op) {
      case "doc.create":
        if (!s.documents.some((d) => d.id === op.id))
          s.documents.push({ id: op.id, title: op.title, owner: op.owner ?? null, version: 1 });
        break;
      case "doc.update":
        s.documents = upd(s.documents, op.doc, { title: op.title });
        break;
      case "doc.delete":
        s.documents = del(s.documents, op.doc);
        break;
      case "table.create":
        if (!s.tables.some((t) => t.id === op.id)) s.tables.push({ id: op.id, key: op.key, name: op.name, version: 1 });
        break;
      case "table.update":
        s.tables = upd(s.tables, op.table, defined({ name: op.name, key: op.key }));
        break;
      case "table.delete":
        s.tables = del(s.tables, op.table);
        break;
      case "workflow.create":
        if (!s.workflows.some((w) => w.id === op.id))
          s.workflows.push({ id: op.id, key: op.key, name: op.name, latest_version: null });
        break;
      case "workflow.delete":
        s.workflows = del(s.workflows, op.workflow);
        break;
      case "role.create":
        if (!s.roles.some((r) => r.id === op.id)) s.roles.push({ id: op.id, key: op.key, name: op.name });
        break;
      case "role.update":
        s.roles = upd(s.roles, op.role, defined({ key: op.key, name: op.name }));
        break;
      case "role.delete":
        s.roles = del(s.roles, op.role);
        break;
    }
  }
  const byName = (a: Json, b: Json) => String(a.title ?? a.name).localeCompare(String(b.title ?? b.name), "de");
  s.documents.sort(byName);
  s.tables.sort(byName);
  s.workflows.sort(byName);
  return s;
}

/** Ops eines Ereignisses (oder eines eigenen Batches) auf einen Kanalzustand anwenden. Wirft OpError. */
export function applyToChannel(channel: string, state: Json, ops: Json[]): ApplyResult {
  const { kind } = parseChannel(channel);
  if (kind === "workspace") return { state: applyWorkspace(state, ops), resync: false };
  if (kind === "doc" || kind === "table") {
    const { ops: mine, unknown } = relevantOps(channel, state, ops);
    if (unknown) return { state, resync: true };
    if (!mine.length) return { state, resync: false };
    try {
      return { state: applyOps(state, mine), resync: false };
    } catch (e) {
      if (e instanceof UnsupportedOp) return { state, resync: true };
      throw e;
    }
  }
  // user, run: Entwürfe (draft.*) bildet der Client nach (L 7.6), alles andere kennt nur der Server
  if (ops.length > 0 && ops.every((o) => isDraftOp(o.op))) {
    return draftOpsFor(channel, ops).length ? { state: applyDraftOps(state, channel, ops), resync: false } : { state, resync: false };
  }
  return { state, resync: ops.length > 0 };
}

/** Kann der Client den Batch selbst nachbilden? Sonst wird er nicht optimistisch angewendet (L 7.4). */
export function isOptimistic(ops: Op[]): boolean {
  // text.edit nicht optimistisch: Textblöcke führen ihren lokalen Stand selbst (OT, documents/textSync.ts)
  return ops.every((o) => (isMirrored(o.op) || isDraftOp(o.op)) && o.op !== "text.edit" && !(o.op === "doc.create" && (o as Json).markdown));
}

export type Pending = {
  batch: OpBatch;
  optimistic: boolean;
  /** Kanäle, in denen der Batch noch nicht im bestätigten Stand steckt. */
  waiting: Set<string>;
  acked: boolean;
  sent: boolean;
};

/** view = confirmed + ausstehende eigene Batches dieses Kanals, in Sendereihenfolge. */
export function computeView(channel: string, confirmed: Json, pending: Pending[]): Json {
  let view = confirmed;
  for (const p of pending) {
    if (!p.optimistic || !p.waiting.has(channel)) continue;
    try {
      view = applyToChannel(channel, view, p.batch.ops).state;
    } catch {
      // passt nicht mehr auf den aktuellen Stand: Der Server entscheidet (reject oder andere Folge).
    }
  }
  return view;
}

/** Welche Kanäle ein Batch betrifft (Spiegel von pipeline.channels_for). `blockDoc` findet das Dokument eines Blocks. */
export function channelsFor(ops: Json[], blockDoc: (block: string) => string | undefined, tableId: (ref: string) => string): Set<string> {
  const out = new Set<string>();
  const ws = new Set(["table.create", "table.update", "table.delete", "doc.create", "doc.update", "doc.delete", "user.set_roles", "agent.set_roles"]);
  const inserted = new Map<string, string>();
  for (const op of ops) {
    const name: string = op.op;
    if (ws.has(name) || name.startsWith("workflow.") || name.startsWith("role.")) out.add("workspace");
    if (name === "table.create") out.add(`table:${op.id}`);
    else if (typeof op.table === "string") out.add(`table:${tableId(op.table)}`);
    if (name === "doc.create") out.add(`doc:${op.id}`);
    else if (typeof op.doc === "string") out.add(`doc:${op.doc}`);
    if (name === "block.insert") blockIdsOf(op.block).forEach((b) => inserted.set(b, op.doc));
    if (typeof op.block === "string") {
      const d = inserted.get(op.block) ?? blockDoc(op.block);
      if (d) out.add(`doc:${d}`);
    }
    if (isDraftOp(name) && scopeKey(op.scope)) out.add(scopeKey(op.scope));
    if (name === "run.start") out.add(`run:${op.id}`);
    else if (typeof op.run === "string") out.add(`run:${op.run}`);
  }
  return out;
}
