// `form`-Block (Task 3.4, L 4): rahmt Felder und Zeilenlisten, hält Fehler und Ladezustand und zeigt die Buttons
// nach der Regel aus L 4.3 (nur zur Anzeige, der Server entscheidet beim Absenden). Eingaben gehen als `draft.*`-Ops
// in den Entwurf, den alle im selben Kontext live sehen (L 7.6). Absenden ist `form.submit` und wird nicht
// optimistisch angewendet; der Button zeigt bis zum ack einen Ladezustand (L 7.4).
import { useMemo, useState } from "react";
import { useAuth } from "../../api/client";
import { FormContext } from "../../forms/formContext";
import {
  type ButtonDef, type FormErrors, effectiveButtons, errorsOf, formState, hasErrors, inputBlocks, noErrors, splitErrors,
  submitOp, validateLocal, visibleButtons,
} from "../../forms/formModel";
import { useDraft } from "../../forms/useDraft";
import { BatchRejected, newId, submit, useChannel } from "../../sync/store";
import { Icon } from "../../ui/icons";
import { toast } from "../../ui/toasts";
import type { FlatBlock } from "../blockOps";
import { useDoc } from "../docContext";
import { BlockChildren } from "../DocumentView";
import { BLOCK_COMPONENTS } from "./registry";

export function FormBlock({ block }: { block: FlatBlock }) {
  const doc = useDoc();
  const me = useAuth((s) => s.user);
  const docCh = useChannel(doc.channel);
  const runCh = useChannel(doc.run ? `run:${doc.run}` : null);
  const draft = useDraft(block.id, doc.run);
  const [errors, setErrorsState] = useState<FormErrors>(noErrors());
  const [busy, setBusy] = useState<string | null>(null);

  const step: string | null = docCh?.view?.documents?.[0]?.owner?.step ?? null;
  const state = formState({
    me, readOnly: doc.readOnly, run: doc.run, step,
    info: doc.run ? { loading: !runCh || runCh.status === "loading", run: runCh?.view?.run, task: runCh?.view?.task } : undefined,
  });
  const inputs = useMemo(() => inputBlocks(doc.blocks, block.id), [doc.blocks, block.id]);
  const buttons = useMemo(() => effectiveButtons(block, doc.blocks), [block, doc.blocks]);
  const shown = visibleButtons(buttons, state);
  const keys = useMemo(() => new Set(inputs.map((b) => b.props.key as string)), [inputs]);

  const click = async (button: ButtonDef) => {
    if (busy) return;
    if (button.confirm && !window.confirm(button.confirm)) return;
    const local = validateLocal(inputs, draft.values, button);
    if (hasErrors(local)) {
      setErrorsState(local);
      return;
    }
    setErrorsState(noErrors());
    setBusy(button.id);
    try {
      const ack = await submit([submitOp(block.id, button.id, newId("sub"), doc.run)]);
      const failed = errorsOf(ack.results);
      if (failed) setErrorsState(splitErrors(failed, keys));
      else toast(`${button.label}: gespeichert`);
    } catch (e) {
      const err = e instanceof BatchRejected ? e.error : { message: (e as Error).message };
      const fields = errorsOf(err);
      if (fields) setErrorsState(splitErrors(fields, keys));
      else setErrorsState({ ...noErrors(), general: [err.message] });
    } finally {
      setBusy(null);
    }
  };

  const ctx = {
    formId: block.id, scope: draft.scope, values: draft.values, errors, setErrors: (fn: (e: FormErrors) => FormErrors) => setErrorsState(fn),
    fillable: state.fillable && draft.ready, busy: busy !== null,
  };

  return (
    <FormContext.Provider value={ctx}>
      <form className="form-block" aria-busy={busy !== null} noValidate onSubmit={(e) => e.preventDefault()}>
        {state.reason && inputs.length > 0 && <p className="form-note"><Icon name="info" size={14} />{state.reason}</p>}
        <BlockChildren parent={block.id} />
        {errors.general.length > 0 && (
          <div className="alert" role="alert">
            <Icon name="alert" />
            <span>{errors.general.map((m) => <span key={m} className="block-msg">{m}</span>)}</span>
          </div>
        )}
        {shown.length > 0 && (
          <div className="form-buttons">
            {shown.map((b) => (
              <button
                key={b.id} type="button" className={b.style === "primary" ? "primary" : b.style === "danger" ? "danger" : ""}
                disabled={busy !== null || !draft.ready} aria-busy={busy === b.id} onClick={() => click(b)}
              >
                {busy === b.id && <span className="spinner" aria-hidden="true" />}
                {b.label}
              </button>
            ))}
          </div>
        )}
      </form>
    </FormContext.Provider>
  );
}

BLOCK_COMPONENTS.form = FormBlock;
