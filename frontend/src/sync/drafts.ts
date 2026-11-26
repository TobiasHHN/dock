// Formularentwürfe im Sync-Store (Task 3.4, L 4.4, L 7.6): `draft.*`-Ops auf den Kanalzustand von `run:<id>` bzw.
// `user:<id>` anwenden. Dort liegt der Entwurf als Liste `drafts` neben den übrigen Snapshot-Daten:
//   drafts: [{ form_block, scope: "run:run_1" | { run } | "user:usr_1" | { user }, values: { key: Wert | Zeile[] }, version }]
// Zeilen einer `line_items`-Liste: { id, position, values }. Wie bei den Tabellen gilt: weicht der Client ab, gewinnt der Server
// (Snapshot), und jede Eingabe ist eine Op, damit andere im selben Kontext sie live sehen (L 7.6).
import { between } from "./apply";
import type { Json } from "./tableRules";

export const isDraftOp = (name: string): boolean => name.startsWith("draft.");

/** `{ run: "run_1" }` / `{ user: "usr_1" }` / `"run:run_1"` → `"run:run_1"` (= Name des Kanals, der den Entwurf trägt). */
export function scopeKey(scope: Json): string {
  if (typeof scope === "string") return scope;
  if (scope?.run) return `run:${scope.run}`;
  if (scope?.user) return `user:${scope.user}`;
  return "";
}

const byPos = (a: Json, b: Json) => (a.position < b.position ? -1 : a.position > b.position ? 1 : 0);

/** Zeilen einer Zeilenliste in Anzeigereihenfolge. */
export const sortedItems = (list: Json): Json[] => (Array.isArray(list) ? [...list].sort(byPos) : []);

export function findDraft(state: Json, formBlock: string, scope: string): Json | undefined {
  return (state?.drafts ?? []).find((d: Json) => d.form_block === formBlock && scopeKey(d.scope) === scope);
}

function updateDraft(state: Json, op: Json, change: (values: Record<string, Json>) => Record<string, Json>): Json {
  const key = scopeKey(op.scope);
  const drafts: Json[] = [...(state?.drafts ?? [])];
  const i = drafts.findIndex((d) => d.form_block === op.form_block && scopeKey(d.scope) === key);
  const cur = i >= 0 ? drafts[i] : { form_block: op.form_block, scope: key, values: {}, version: 0 };
  const next = { ...cur, values: change({ ...(cur.values ?? {}) }), version: (cur.version ?? 0) + 1 };
  if (i >= 0) drafts[i] = next;
  else drafts.push(next);
  return { ...state, drafts };
}

function applyOne(state: Json, op: Json): Json {
  switch (op.op) {
    case "draft.set":
      return updateDraft(state, op, (v) => ({ ...v, [op.key]: op.value }));
    case "draft.item_insert":
      return updateDraft(state, op, (v) => {
        const items = sortedItems(v[op.key]);
        if (items.some((x) => x.id === op.item.id)) return v;
        const found = op.after ? items.findIndex((x) => x.id === op.after) : -1;
        const at = found >= 0 ? found : items.length - 1; // ohne (bekanntes) `after` ans Ende
        const prev = at >= 0 ? items[at].position : null;
        const next = at + 1 < items.length ? items[at + 1].position : null;
        const item = { ...op.item, values: op.item.values ?? {}, position: op.item.position ?? between(prev, next) };
        return { ...v, [op.key]: [...items.slice(0, at + 1), item, ...items.slice(at + 1)] };
      });
    case "draft.item_update":
      return updateDraft(state, op, (v) => ({
        ...v,
        [op.key]: sortedItems(v[op.key]).map((x) => (x.id === op.item_id ? { ...x, values: { ...x.values, ...op.values } } : x)),
      }));
    case "draft.item_delete":
      return updateDraft(state, op, (v) => ({ ...v, [op.key]: sortedItems(v[op.key]).filter((x) => x.id !== op.item_id) }));
    default:
      return state;
  }
}

/** Nur die Draft-Ops, die zu diesem Kanal gehören (der Kanal heißt wie der Scope). */
export function draftOpsFor(channel: string, ops: Json[]): Json[] {
  return ops.filter((o) => isDraftOp(o.op) && scopeKey(o.scope) === channel);
}

export function applyDraftOps(state: Json, channel: string, ops: Json[]): Json {
  return draftOpsFor(channel, ops).reduce(applyOne, state);
}
