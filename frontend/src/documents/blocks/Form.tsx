// `form`-Block (Task 3.4, L 4): rahmt Felder und Zeilenlisten, hält Fehler und Ladezustand und zeigt die Buttons
// nach der Regel aus L 4.3 (nur zur Anzeige, der Server entscheidet beim Absenden). Eingaben gehen als `draft.*`-Ops
// in den Entwurf, den alle im selben Kontext live sehen (L 7.6). Absenden ist `form.submit` und wird nicht
// optimistisch angewendet; der Button zeigt bis zum ack einen Ladezustand (L 7.4).
import { useMemo, useState } from "react";
import { useAuth } from "../../api/client";
import { FormContext } from "../../forms/formContext";
import {
  type ButtonDef, type FormErrors, buttonLabel, effectiveButtons, errorsOf, formState, hasErrors, inputBlocks, noErrors, splitErrors,
  submitOp, validateLocal, visibleButtons,
} from "../../forms/formModel";
import { useDraft } from "../../forms/useDraft";
import { BatchRejected, newId, submit, useChannel } from "../../sync/store";
import { confirmDialog } from "../../ui/confirm";
import { Icon } from "../../ui/icons";
import { toast } from "../../ui/toasts";
import { normalizeSubmittedValues } from "../../workflows/layout";
import type { FlatBlock } from "../blockOps";
import { useDoc } from "../docContext";
import { BlockChildren } from "../DocumentView";
import { BLOCK_COMPONENTS } from "./registry";

export function FormBlock({ block }: { block: FlatBlock }) {
  const doc = useDoc();
  const me = useAuth((s) => s.user);
  const docCh = useChannel(doc.channel || null);
  const runCh = useChannel(doc.run ? `run:${doc.run}` : null);
  const wsCh = useChannel("workspace");
  const draft = useDraft(block.id, doc.run);
  const [errors, setErrorsState] = useState<FormErrors>(noErrors());
  const [busy, setBusy] = useState<string | null>(null);

  const owner = doc.owner ?? docCh?.view?.document?.owner ?? null; // { workflow, step } bei Schritt-Dokumenten
  const step: string | null = doc.stepKey ?? owner?.step ?? null;
  const state = formState({
    me, readOnly: doc.readOnly, run: doc.run, step, owner,
    workspaceRoles: wsCh?.view?.roles as { id: string; key: string }[] | undefined,
    info: doc.run ? { loading: !runCh || runCh.status === "loading", run: runCh?.view?.run, task: runCh?.view?.task } : undefined,
  });
  const inputs = useMemo(() => inputBlocks(doc.blocks, block.id), [doc.blocks, block.id]);
  const buttons = useMemo(() => effectiveButtons(block, doc.blocks), [block, doc.blocks]);
  const shown = visibleButtons(buttons, state);
  const keys = useMemo(() => new Set(inputs.map((b) => b.props.key as string)), [inputs]);

  const click = async (button: ButtonDef) => {
    if (busy) return;
    if (button.confirm && !(await confirmDialog({ title: button.confirm, confirmLabel: buttonLabel(button.label) }))) return;
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
      else if (ack.results?.["0"]?.duplicate) toast(`${buttonLabel(button.label)}: war schon abgesendet`);
      else toast(`${buttonLabel(button.label)}: gespeichert`);
    } catch (e) {
      const err = e instanceof BatchRejected ? e.error : { message: (e as Error).message };
      const fields = errorsOf(err);
      if (fields) setErrorsState(splitErrors(fields, keys));
      else setErrorsState({ ...noErrors(), general: [err.message] });
    } finally {
      setBusy(null);
    }
  };

  const submittedValues = useMemo(() => {
    if (!doc.run || state.fillable || !step) return null;
    const raw = runCh?.view?.run?.steps?.[step]?.values;
    if (!raw || typeof raw !== "object") return null;
    return normalizeSubmittedValues(doc.blocks, raw as Record<string, unknown>);
  }, [doc.run, doc.blocks, state.fillable, step, runCh?.view?.run?.steps]);

  const ctx = {
    formId: block.id, scope: draft.scope, values: submittedValues ?? draft.values, errors, setErrors: (fn: (e: FormErrors) => FormErrors) => setErrorsState(fn),
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
                {buttonLabel(b.label)}
              </button>
            ))}
          </div>
        )}
      </form>
    </FormContext.Provider>
  );
}

BLOCK_COMPONENTS.form = FormBlock;
