// Reine Logik der Formular-Blöcke (Task 3.4, L 4): Sichtbarkeit der Buttons (L 4.3), Fehlerpfade aus der
// Submit-Antwort (L 4.6), lokale Vorprüfung, Typen der Eingabefelder und die Ops für Entwürfe (L 4.4, L 6.1).
// Ob ein Absenden erlaubt ist, entscheidet immer der Server; hier wird nur angezeigt und vorgeprüft.
import type { Op } from "../api";
import type { FlatBlock } from "../documents/blockOps";
import { sortedItems } from "../sync/drafts";
import type { Json } from "../sync/tableRules";

export type ButtonDef = {
  id: string; label: string; style?: "primary" | "secondary" | "danger"; actions?: string[]; outcome?: string | null;
  validate?: boolean; require?: string[]; confirm?: string | null;
};

// ── Aufbau des Formulars ─────────────────────────────────────────────────────

/** Alle Nachkommen eines Blocks (Tiefensuche in Dokumentreihenfolge). */
export function descendants(blocks: FlatBlock[], id: string): FlatBlock[] {
  const kids = blocks.filter((b) => b.parent_id === id).sort((a, b) => (a.position < b.position ? -1 : 1));
  return kids.flatMap((k) => [k, ...descendants(blocks, k.id)]);
}

/** Das Formular, in dem ein Block liegt (nächster Vorfahre vom Typ `form`). */
export function formOf(blocks: FlatBlock[], blockId: string): FlatBlock | undefined {
  const byId = new Map(blocks.map((b) => [b.id, b]));
  for (let p = byId.get(blockId)?.parent_id; p; p = byId.get(p)?.parent_id) {
    const b = byId.get(p);
    if (b?.type === "form") return b;
  }
  return undefined;
}

export const inputBlocks = (blocks: FlatBlock[], form: string): FlatBlock[] =>
  descendants(blocks, form).filter((b) => b.type === "field" || b.type === "line_items");

/** Buttons nach L 4.3: explizit angegeben, sonst „Speichern“ (alle Actions), wenn es Felder gibt, sonst keine. */
export function effectiveButtons(form: FlatBlock, blocks: FlatBlock[]): ButtonDef[] {
  const explicit = form.props.buttons as ButtonDef[] | null | undefined;
  if (explicit) return explicit;
  if (inputBlocks(blocks, form.id).length === 0) return [];
  const actions = ((form.props.actions ?? []) as { key: string }[]).map((a) => a.key);
  return [{ id: "save", label: "Speichern", style: "primary", actions }];
}

// ── Sichtbarkeit und Schreibschutz (L 4.3) ───────────────────────────────────

export type RunInfo = {
  /** Kanal `run:<id>` ist noch nicht geladen. */
  loading: boolean;
  run?: Json;
  task?: Json;
};

export type Me = { id: string; roles: string[] } | null;

/** Darf `me` die offene Aufgabe erledigen? Nur zur Anzeige; bevorzugt das Feld `can_act`, falls der Server es liefert. */
export function canAct(task: Json, me: Me): boolean {
  if (!task || !me) return false;
  if (typeof task.can_act === "boolean") return task.can_act;
  const claimed = task.claimed_by_id ?? task.claimed_by?.id;
  if (claimed) return claimed === me.id;
  const users: string[] = task.candidate_users ?? task.candidates?.users ?? [];
  const roles: string[] = task.candidate_roles ?? task.candidates?.roles ?? [];
  return users.includes(me.id) || roles.some((r) => me.roles.includes(r));
}

export type FormState = { fillable: boolean; reason: string | null };

/**
 * Darf der Nutzer das Formular ausfüllen (und damit: Buttons sehen)?
 * Ohne Workflow-Kontext: ja, wenn angemeldet und das Dokument nicht schreibgeschützt ist.
 * Im Run: Status aktiv, aktueller Schritt = Schritt dieses Dokuments, Nutzer darf die offene Aufgabe erledigen,
 * kein wartender Sub-Run. Fehlt dem Client eine Angabe (Server liefert sie noch nicht), gilt sie als erfüllt, der Server prüft ohnehin.
 */
export function formState(opts: { me: Me; readOnly?: boolean; run?: string; info?: RunInfo; step?: string | null }): FormState {
  const { me, readOnly, run, info, step } = opts;
  if (!me) return { fillable: false, reason: "Bitte anmelden." };
  if (readOnly) return { fillable: false, reason: "Dieses Dokument ist schreibgeschützt." };
  if (!run) return { fillable: true, reason: null };
  if (!info || info.loading) return { fillable: false, reason: null };
  const r = info.run;
  if (r?.status && r.status !== "active") return { fillable: false, reason: "Dieser Ablauf ist abgeschlossen." };
  const current = r?.current_step ?? r?.current?.step ?? info.task?.step;
  if (current && step && current !== step) return { fillable: false, reason: "Dieser Schritt ist nicht (mehr) aktuell." };
  if (r?.waiting_subrun || r?.waiting_for) return { fillable: false, reason: "Der Ablauf wartet auf einen Unter-Ablauf." };
  if (info.task && !canAct(info.task, me)) return { fillable: false, reason: "Du bist für diese Aufgabe nicht zuständig, das Formular ist schreibgeschützt." };
  if (!info.task && r) return { fillable: false, reason: "Es gibt keine offene Aufgabe." };
  return { fillable: true, reason: null };
}

/** Sichtbare Buttons: nur wenn das Formular ausfüllbar ist. */
export const visibleButtons = (buttons: ButtonDef[], state: FormState): ButtonDef[] => (state.fillable ? buttons : []);

// ── Eingabefelder ────────────────────────────────────────────────────────────

export type FieldInputKind =
  | "text" | "textarea" | "integer" | "number" | "currency" | "date" | "boolean" | "select" | "reference" | "user";

/** Spaltentyp, nach dem ein Feld Eingaben umwandelt (für parseInput/inputText aus tables/tableModel). */
export function inputType(input: FieldInputKind, options?: { id: string; label: string }[]): Json {
  switch (input) {
    case "textarea": return { kind: "long_text" };
    case "integer": return { kind: "integer" };
    case "number": return { kind: "number", decimals: 10 }; // nicht runden, das macht der Server pro Zielspalte
    case "currency": return { kind: "currency", currency: "EUR" };
    case "date": return { kind: "date" };
    case "boolean": return { kind: "boolean" };
    case "select": return { kind: "select", options: options ?? [] };
    case "user": return { kind: "user" };
    case "reference": return { kind: "text" };
    default: return { kind: "text" };
  }
}

/** Eingabeart und Beschriftung eines Felds; bei `column`-Bindung aus der Spalte, wenn sie bekannt ist (L 4.1). */
export function resolveField(props: Json, column?: Json): {
  input: FieldInputKind; label: string; required: boolean; options: { id: string; label: string }[];
} {
  const kindOf = (t: Json): FieldInputKind => {
    switch (t?.kind) {
      case "long_text": return "textarea";
      case "integer": case "number": case "currency": case "date": case "boolean": case "select": case "user": case "reference":
        return t.kind;
      case "datetime": return "date";
      default: return "text";
    }
  };
  return {
    input: (props.input ?? (column ? kindOf(column.type) : "text")) as FieldInputKind,
    label: props.label ?? column?.name ?? props.key,
    required: !!(props.required ?? column?.required),
    options: props.options ?? column?.type?.options ?? [],
  };
}

// ── Fehler am Feld (L 4.6) ───────────────────────────────────────────────────

export type FormErrors = {
  /** Fehler je Feld-Key (`name`) und je Zeilenliste als Ganzes (`artikel`, z. B. min_rows). */
  fields: Record<string, string>;
  /** Fehler je Zeilenliste, Zeilenindex und Spalten-Key (`artikel[2].preis`). */
  items: Record<string, Record<number, Record<string, string>>>;
  /** Fehler ohne erkennbares Feld (Berechtigung, Aktion, …). */
  general: string[];
};

export const noErrors = (): FormErrors => ({ fields: {}, items: {}, general: [] });

/** `{ "artikel[2].preis": "…", "name": "…" }` → nach Feld und Zeile geordnet. Pfade unbekannter Felder landen in `general`. */
export function splitErrors(errors: Record<string, string> | null | undefined, knownKeys?: Set<string>): FormErrors {
  const out = noErrors();
  for (const [path, msg] of Object.entries(errors ?? {})) {
    const m = /^([^[\].]+)\[(\d+)\]\.(.+)$/.exec(path);
    if (m) {
      const [, key, idx, col] = m;
      ((out.items[key] ??= {})[Number(idx)] ??= {})[col] = msg;
    } else if (!knownKeys || knownKeys.has(path)) {
      out.fields[path] = msg;
    } else {
      out.general.push(`${path}: ${msg}`);
    }
  }
  return out;
}

/** Fehlerdetails aus einer abgelehnten oder bestätigten Antwort (`details.errors` bzw. `results.errors`). */
export function errorsOf(source: Json): Record<string, string> | null {
  const e = source?.details?.errors ?? source?.errors ?? source?.["0"]?.errors;
  return e && typeof e === "object" && !Array.isArray(e) ? (e as Record<string, string>) : null;
}

const isBlank = (v: Json) => v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0);

/**
 * Vorprüfung vor dem Absenden (Pflichtfelder, `button.require`, `min_rows`, Pflichtspalten der Zeilen), nur wenn der
 * Button `validate` nicht abschaltet. Der Server prüft zusätzlich Typen und Tabellenregeln.
 */
export function validateLocal(inputs: FlatBlock[], values: Record<string, Json>, button: ButtonDef): FormErrors {
  const out = noErrors();
  if (button.validate === false) return out;
  const extra = new Set(button.require ?? []);
  for (const b of inputs) {
    const p = b.props;
    const v = values[p.key];
    if (b.type === "field") {
      const need = p.required || extra.has(p.key);
      // Ein Haken, der nicht gesetzt ist, zählt als beantwortet (false), nur „nie angefasst“ bei Pflicht nicht
      if (need && isBlank(v) && !(p.input === "boolean" && v === false)) out.fields[p.key] = `${p.label ?? p.key} ist ein Pflichtfeld`;
    } else {
      const items = sortedItems(v);
      if (p.min_rows && items.length < p.min_rows) out.fields[p.key] = `Mindestens ${p.min_rows} ${p.min_rows === 1 ? "Zeile" : "Zeilen"} erforderlich`;
      else if (extra.has(p.key) && items.length === 0) out.fields[p.key] = `${p.label ?? p.key} braucht mindestens eine Zeile`;
      items.forEach((item, i) => {
        for (const c of p.columns ?? []) {
          if (c.required && isBlank(item.values?.[c.key])) ((out.items[p.key] ??= {})[i] ??= {})[c.key] = `${c.label ?? c.key} ist ein Pflichtfeld`;
        }
      });
    }
  }
  return out;
}

export const hasErrors = (e: FormErrors): boolean =>
  Object.keys(e.fields).length > 0 || Object.keys(e.items).length > 0 || e.general.length > 0;

/** Entfernt den Fehler eines Felds (nach Eingabe), ohne den Rest anzutasten. */
export function clearField(e: FormErrors, key: string, item?: { index: number; column: string }): FormErrors {
  if (!item) {
    if (!(key in e.fields)) return e;
    const { [key]: _gone, ...fields } = e.fields;
    return { ...e, fields };
  }
  const rows = e.items[key];
  if (!rows?.[item.index]?.[item.column]) return e;
  const { [item.column]: _c, ...rest } = rows[item.index];
  return { ...e, items: { ...e.items, [key]: { ...rows, [item.index]: rest } } };
}

// ── Ops ──────────────────────────────────────────────────────────────────────

export type Scope = { run: string } | { user: string };

export const draftScope = (run: string | undefined, userId: string): Scope => (run ? { run } : { user: userId });

export const draftSetOp = (form_block: string, scope: Scope, key: string, value: Json): Op =>
  ({ op: "draft.set", form_block, scope, key, value }) as Op;

export const itemInsertOp = (form_block: string, scope: Scope, key: string, id: string, after?: string, values: Json = {}): Op =>
  ({ op: "draft.item_insert", form_block, scope, key, item: { id, values }, ...(after ? { after } : {}) }) as Op;

export const itemUpdateOp = (form_block: string, scope: Scope, key: string, item_id: string, values: Json): Op =>
  ({ op: "draft.item_update", form_block, scope, key, item_id, values }) as Op;

export const itemDeleteOp = (form_block: string, scope: Scope, key: string, item_id: string): Op =>
  ({ op: "draft.item_delete", form_block, scope, key, item_id }) as Op;

export const submitOp = (form_block: string, button: string, submission_id: string, run?: string): Op =>
  ({ op: "form.submit", submission_id, form_block, button, ...(run ? { run } : {}) }) as Op;
