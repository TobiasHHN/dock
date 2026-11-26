// Eingabe für Formularfelder und Zeilenlisten (Task 3.4, L 4.1). Text wird entprellt in den Entwurf geschrieben
// (T 5.5), beim Verlassen sofort; Haken und Auswahl sofort. Eingaben werden wie in Tabellenzellen in den Typ umgewandelt.
import { useEffect, useRef, useState } from "react";
import { useUsers } from "../ui/actors";
import { useChannel } from "../sync/store";
import type { Json } from "../sync/tableRules";
import { inputText, parseInput } from "../tables/tableModel";
import { type FieldInputKind, inputType } from "./formModel";

export const DRAFT_DEBOUNCE = 400;

type Props = {
  kind: FieldInputKind;
  value: Json;
  options?: { id: string; label: string }[];
  referenceTable?: string;
  disabled?: boolean;
  invalid?: boolean;
  /** Zugänglicher Name, wenn kein sichtbares Label darüber steht. */
  label: string;
  id?: string;
  describedBy?: string;
  onCommit: (value: Json) => void;
  /** Meldung, wenn die Eingabe nicht in den Typ passt (sonst null). */
  onLocalError?: (message: string | null) => void;
  /** Wird bei jeder Eingabe gerufen (z. B. um alte Serverfehler zu entfernen). */
  onEdit?: () => void;
};

export function FormInput({ kind, value, options, referenceTable, disabled, invalid, label, id, describedBy, onCommit, onLocalError, onEdit }: Props) {
  const type = inputType(kind, options);
  const shown = inputText(value, type);
  const [text, setText] = useState(shown);
  const focused = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef({ text, shown, onCommit });
  latest.current = { text, shown, onCommit };

  useEffect(() => {
    if (!focused.current) setText(shown);
  }, [shown]);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const flush = (t: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (t === latest.current.shown) return onLocalError?.(null);
    const r = parseInput(t, type);
    if ("error" in r) return onLocalError?.(r.error);
    onLocalError?.(null);
    latest.current.onCommit(r.value);
  };

  const common = { id, "aria-label": id ? undefined : label, "aria-invalid": invalid || undefined, "aria-describedby": describedBy, disabled };

  if (kind === "boolean")
    return <input {...common} type="checkbox" checked={value === true} onChange={(e) => { onEdit?.(); onCommit(e.target.checked); }} />;

  if (kind === "select" || kind === "user" || kind === "reference")
    return (
      <ChoiceSelect
        {...common} kind={kind} value={value} options={options} referenceTable={referenceTable}
        onChange={(v) => { onEdit?.(); onCommit(v); }}
      />
    );

  const change = (t: string) => {
    setText(t);
    onEdit?.();
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => flush(t), DRAFT_DEBOUNCE);
  };
  const handlers = {
    value: text,
    onFocus: () => { focused.current = true; },
    onBlur: () => { focused.current = false; flush(latest.current.text); },
  };

  if (kind === "textarea")
    return <textarea {...common} {...handlers} rows={3} onChange={(e) => change(e.target.value)} />;

  return (
    <input
      {...common} {...handlers}
      type={kind === "date" ? "date" : "text"}
      className={["integer", "number", "currency"].includes(kind) ? "num" : undefined}
      inputMode={kind === "integer" ? "numeric" : kind === "number" || kind === "currency" ? "decimal" : undefined}
      autoComplete="off"
      onChange={(e) => change(e.target.value)}
      onKeyDown={(e) => { if (e.key === "Enter" && kind !== "date") (e.target as HTMLInputElement).blur(); }}
    />
  );
}

type SelectProps = {
  kind: "select" | "user" | "reference"; value: Json; options?: { id: string; label: string }[]; referenceTable?: string;
  onChange: (v: Json) => void; [k: string]: Json;
};

function ChoiceSelect({ kind, value, options, referenceTable, onChange, ...rest }: SelectProps) {
  const users = useUsers();
  const ref = useChannel(kind === "reference" && referenceTable ? `table:${referenceTable}` : null);
  let list: { id: string; label: string }[] = options ?? [];
  if (kind === "user") list = Object.values(users).map((u) => ({ id: u.id, label: u.name }));
  if (kind === "reference") {
    const t = ref?.view?.tables?.[0];
    const cols = [...(t?.columns ?? [])].sort((a: Json, b: Json) => (a.position < b.position ? -1 : 1));
    const display = cols.find((c: Json) => c.id === t?.display_column) ?? cols[0];
    list = (t?.rows ?? []).map((r: Json) => ({ id: r.id, label: String(r.values?.[display?.id] ?? r.id) }));
  }
  return (
    <select {...rest} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}>
      <option value="">–</option>
      {list.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
    </select>
  );
}
