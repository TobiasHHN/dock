// Text-OT für `text.edit` (L 7.5, T 2.6), Spiegel von backend/app/domain/text_ot.py. Gemeinsame Fälle:
// spec/fixtures/text_ot/. Festlegungen (siehe dort im Docstring):
// - Positionen zählen Einheiten: jedes Zeichen (Code Point, nicht UTF-16!) aus text/link = 1, mention/value = 1.
// - `marks` des Edits gelten relativ zu `insert`; fehlen sie, erbt der Text die Marks des Zeichens davor.
// - side "after": bei Einfügen an derselben Stelle steht der frühere Edit vorn. Löschen gewinnt.
import type { Json } from "./tableRules";

export type Mark = "bold" | "italic" | "code" | "strike";
export const MARK_ORDER: Mark[] = ["bold", "italic", "code", "strike"];
export type TextMark = { from: number; to: number; mark: Mark };
export type Edit = { from: number; to: number; insert: string; marks?: TextMark[] | null };
export type Side = "before" | "after";

export const cpLength = (s: string) => Array.from(s).length;

export function transformOne<E extends Edit>(edit: E, prior: Edit, side: Side = "after"): E {
  const pf = prior.from;
  const pt = Math.max(prior.from, prior.to);
  const length = cpLength(prior.insert ?? "");
  const delta = length - (pt - pf);
  const ef = edit.from;
  const et = Math.max(edit.from, edit.to);
  const isInsert = ef === et;

  let nf: number;
  if (ef < pf) nf = ef;
  else if (pf === pt) nf = ef > pf || !isInsert || side === "after" ? ef + length : ef;
  else if (ef === pf) nf = ef;
  else if (ef >= pt) nf = ef + delta;
  else nf = pf + length;

  // Löschen gewinnt, wenn der Edit ganz im fremd ersetzten Bereich liegt; bei genau gleichem Bereich gewinnt der
  // am Server frühere Edit (der spätere mit side "after" entfällt, die Gegenrichtung "before" ersetzt den fremden Text).
  const sameRange = ef === pf && et === pt;
  if (pt > pf && pf <= ef && et <= pt && !(isInsert && (ef === pf || ef === pt)) && (!sameRange || side === "after"))
    return { ...edit, from: nf, to: nf, insert: "", marks: null };

  let nt: number;
  if (isInsert) nt = nf;
  else if (et <= pf) nt = et;
  else if (pf === pt) nt = et + length;
  else if (et >= pt) nt = et + delta;
  else nt = pf;
  return { ...edit, from: nf, to: Math.max(nf, nt) };
}

export function transform<E extends Edit>(edit: E, appliedSince: Edit[]): E {
  return appliedSince.reduce<E>((e, prior) => transformOne(e, prior, "after"), edit);
}

// ── Einheiten <-> Inline-Inhalt ──────────────────────────────────────────────

export type Unit =
  | { k: "c"; ch: string; marks: Mark[] }
  | { k: "l"; ch: string; href: string }
  | { k: "a"; part: Json };

export function toUnits(content: Json[] | undefined): Unit[] {
  const out: Unit[] = [];
  for (const part of content ?? []) {
    if (part.t === "text") {
      const marks = MARK_ORDER.filter((m) => (part.marks ?? []).includes(m));
      for (const ch of Array.from<string>(part.text ?? "")) out.push({ k: "c", ch, marks });
    } else if (part.t === "link") {
      for (const ch of Array.from<string>(part.text ?? "")) out.push({ k: "l", ch, href: part.href ?? "" });
    } else out.push({ k: "a", part });
  }
  return out;
}

export function fromUnits(units: Unit[]): Json[] {
  const out: Json[] = [];
  for (const u of units) {
    const last = out[out.length - 1];
    if (u.k === "c") {
      if (last?.t === "text" && (last.marks as Mark[]).join() === u.marks.join()) last.text += u.ch;
      else out.push({ t: "text", text: u.ch, marks: [...u.marks] });
    } else if (u.k === "l") {
      if (last?.t === "link" && last.href === u.href) last.text += u.ch;
      else out.push({ t: "link", text: u.ch, href: u.href });
    } else out.push({ ...u.part });
  }
  return out;
}

export const textLength = (content: Json[] | undefined) => toUnits(content).length;

export function applyEditUnits(units: Unit[], edit: Edit): Unit[] {
  const f = Math.min(Math.max(edit.from, 0), units.length);
  const t = Math.min(Math.max(edit.to, f), units.length);
  const chars = Array.from(edit.insert ?? "");
  let inserted: Unit[];
  if (edit.marks == null) {
    const before = f > 0 ? units[f - 1] : null;
    const marks = before?.k === "c" ? before.marks : [];
    inserted = chars.map((ch) => ({ k: "c", ch, marks }));
  } else {
    const spec = edit.marks;
    inserted = chars.map((ch, i) => {
      const on = new Set(spec.filter((m) => m.from <= i && i < m.to).map((m) => m.mark));
      return { k: "c", ch, marks: MARK_ORDER.filter((m) => on.has(m)) };
    });
  }
  return [...units.slice(0, f), ...inserted, ...units.slice(t)];
}

export function applyEdit(content: Json[] | undefined, edit: Edit): Json[] {
  return fromUnits(applyEditUnits(toUnits(content), edit));
}

const sameUnit = (a: Unit, b: Unit) =>
  a.k === b.k &&
  (a.k === "c"
    ? a.ch === (b as typeof a).ch && a.marks.join() === (b as typeof a).marks.join()
    : a.k === "l"
      ? a.ch === (b as typeof a).ch && a.href === (b as typeof a).href
      : JSON.stringify(a.part) === JSON.stringify((b as typeof a).part));

/** Kleinster Edit, der `a` in `b` überführt (gemeinsamer Anfang und gemeinsames Ende), oder null bei Gleichheit.
 *  `plain` = false, wenn der eingefügte Teil Links oder Erwähnungen enthält (dann geht es nicht per text.edit). */
export function diffUnits(a: Unit[], b: Unit[]): (Edit & { plain: boolean }) | null {
  let start = 0;
  while (start < a.length && start < b.length && sameUnit(a[start], b[start])) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && sameUnit(a[endA - 1], b[endB - 1])) {
    endA--;
    endB--;
  }
  if (start === endA && start === endB) return null;
  const mid = b.slice(start, endB);
  const plain = mid.every((u) => u.k === "c");
  const insert = mid.map((u) => (u.k === "a" ? "" : u.ch)).join("");
  const marks: TextMark[] = [];
  mid.forEach((u, i) => {
    if (u.k !== "c") return;
    for (const mark of u.marks) {
      const last = [...marks].reverse().find((m) => m.mark === mark);
      if (last && last.to === i) last.to = i + 1;
      else marks.push({ from: i, to: i + 1, mark });
    }
  });
  return { from: start, to: endA, insert, marks, plain };
}
