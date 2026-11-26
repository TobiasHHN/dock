// `field` und `line_items` (Task 3.4, L 4.1): Eingaben eines Formulars. Jede Änderung ist eine `draft.*`-Op in den
// Entwurf (live für alle im selben Kontext, L 7.6). Fehler vom Server (`details.errors`) stehen direkt am Feld
// bzw. an der Zeile und Spalte.
import { useState } from "react";
import { FormInput } from "../../forms/FormInput";
import { type FormContextValue, useForm } from "../../forms/formContext";
import {
  clearField, draftSetOp, itemDeleteOp, itemInsertOp, itemUpdateOp, resolveField,
} from "../../forms/formModel";
import { sortedItems } from "../../sync/drafts";
import { newId, submit, useSync } from "../../sync/store";
import type { Json } from "../../sync/tableRules";
import { Icon } from "../../ui/icons";
import type { FlatBlock } from "../blockOps";
import { BLOCK_COMPONENTS } from "./registry";

/** Spalte einer bereits geladenen Tabelle (per ID oder `tabelle.spalte`), wenn der Client sie kennt. Sonst `undefined`. */
export function useColumnDef(ref: string | undefined | null): Json | undefined {
  return useSync((s) => {
    if (!ref) return undefined;
    for (const [name, ch] of Object.entries(s.channels)) {
      if (!name.startsWith("table:")) continue;
      const t = ch.view?.tables?.[0];
      const hit = t?.columns?.find((c: Json) => c.id === ref || `${t.key}.${c.key}` === ref);
      if (hit) return hit;
    }
    return undefined;
  });
}

const fire = (p: Promise<unknown>) => p.catch(() => undefined); // Ablehnungen meldet der Store als Hinweis

export function FieldBlock({ block }: { block: FlatBlock }) {
  const p = block.props;
  const form = useForm();
  const col = useColumnDef(p.column);
  const r = resolveField(p, col);
  const [local, setLocal] = useState<string | null>(null);
  const serverError = form?.errors.fields[p.key];
  const error = local ?? serverError;
  const id = `fld_${block.id}`;
  const value = form?.values[p.key] ?? null;
  const disabled = !form || !form.fillable || form.busy;
  const isBool = r.input === "boolean";

  const input = (
    <FormInput
      kind={r.input} value={value} options={r.options} referenceTable={p.reference_table ?? col?.type?.table}
      id={id} label={r.label} disabled={disabled} invalid={!!error} describedBy={error ? `${id}_err` : undefined}
      onLocalError={setLocal}
      onEdit={() => form?.setErrors((e) => clearField(e, p.key))}
      onCommit={(v) => form && fire(submit([draftSetOp(form.formId, form.scope, p.key, v)]))}
    />
  );
  const label = (
    <label htmlFor={id}>
      {r.label}{r.required && <span className="req" aria-hidden="true"> *</span>}
      {r.required && <span className="sr-only"> (Pflichtfeld)</span>}
    </label>
  );

  return (
    <div className={`field ${isBool ? "field-bool" : ""} ${error ? "has-error" : ""}`}>
      {isBool ? <>{input}{label}</> : <>{label}{input}</>}
      {error && <span id={`${id}_err`} className="field-error" role="alert">{error}</span>}
      {!form && <span className="muted small">Dieses Feld liegt nicht in einem Formular.</span>}
    </div>
  );
}

// ── Zeilenliste ──────────────────────────────────────────────────────────────

type LineColumn = { key: string; label?: string; column?: string; input?: string; required?: boolean };

function LineCell({ form, block, col, itemId, index, value, error }: {
  form: FormContextValue; block: FlatBlock; col: LineColumn; itemId: string; index: number; value: Json; error?: string;
}) {
  const def = useColumnDef(col.column);
  const r = resolveField({ input: col.input, label: col.label ?? col.key, required: col.required, key: col.key }, def);
  const [local, setLocal] = useState<string | null>(null);
  const msg = local ?? error;
  const id = `li_${itemId}_${col.key}`;
  return (
    <td className={msg ? "cell-error" : undefined}>
      <FormInput
        kind={r.input} value={value ?? null} options={r.options} id={id} label={`${block.props.label}: ${r.label}`}
        disabled={!form.fillable || form.busy} invalid={!!msg} describedBy={msg ? `${id}_err` : undefined}
        onLocalError={setLocal}
        onCommit={(v) => fire(submit([itemUpdateOp(form.formId, form.scope, block.props.key, itemId, { [col.key]: v })]))}
        onEdit={() => form.setErrors((e) => clearField(e, block.props.key, { index, column: col.key }))}
      />
      {msg && <span id={`${id}_err`} className="cell-msg" role="alert">{msg}</span>}
    </td>
  );
}

export function LineItemsBlock({ block }: { block: FlatBlock }) {
  const p = block.props;
  const form = useForm();
  const columns: LineColumn[] = p.columns ?? [];
  if (!form)
    return <div className="placeholder-block"><b>Zeilenliste</b> · {p.label} (liegt nicht in einem Formular)</div>;
  const items = sortedItems(form.values[p.key]);
  const rowErrors = form.errors.items[p.key] ?? {};
  const listError = form.errors.fields[p.key];
  const disabled = !form.fillable || form.busy;
  const add = () => fire(submit([itemInsertOp(form.formId, form.scope, p.key, newId("itm"), items.at(-1)?.id)]));

  return (
    <div className={`line-items ${listError ? "has-error" : ""}`}>
      <div className="line-items-head">
        <b>{p.label}</b>
        {p.min_rows ? <span className="muted small">mindestens {p.min_rows}</span> : null}
      </div>
      <div className="table-wrap">
        <table className="simple grid">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} scope="col">{c.label ?? c.key}{c.required ? <span className="req" aria-hidden="true"> *</span> : null}</th>
              ))}
              {!disabled && <th className="col-actions"><span className="sr-only">Aktionen</span></th>}
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <tr key={item.id}>
                {columns.map((c) => (
                  <LineCell key={c.key} form={form} block={block} col={c} itemId={item.id} index={i} value={item.values?.[c.key]} error={rowErrors[i]?.[c.key]} />
                ))}
                {!disabled && (
                  <td className="col-actions">
                    <button
                      type="button" className="ghost danger" title="Zeile entfernen" aria-label={`Zeile ${i + 1} entfernen`}
                      onClick={() => fire(submit([itemDeleteOp(form.formId, form.scope, p.key, item.id)]))}
                    >
                      <Icon name="trash" size={14} />
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && <p className="empty">Noch keine Zeilen.</p>}
      </div>
      {listError && <span className="field-error" role="alert">{listError}</span>}
      {!disabled && (
        <button type="button" className="ghost" onClick={add}><Icon name="plus" size={14} />Zeile hinzufügen</button>
      )}
    </div>
  );
}

BLOCK_COMPONENTS.field = FieldBlock;
BLOCK_COMPONENTS.line_items = LineItemsBlock;
