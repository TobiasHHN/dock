// Bestätigungsdialog statt `window.confirm`: `await confirmDialog({ … })` liefert true (bestätigt) oder false (abgebrochen).
import { useEffect, useRef } from "react";
import { create } from "zustand";
import { Icon } from "./icons";

export type ConfirmOptions = {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Zerstörerische Aktion: roter Button, Fokus liegt zunächst auf „Abbrechen“. */
  danger?: boolean;
};

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

const useConfirm = create<{ pending: Pending | null }>(() => ({ pending: null }));

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    // Ein noch offener Dialog gilt als abgebrochen
    useConfirm.getState().pending?.resolve(false);
    useConfirm.setState({ pending: { ...options, resolve } });
  });
}

function close(ok: boolean) {
  const p = useConfirm.getState().pending;
  useConfirm.setState({ pending: null });
  p?.resolve(ok);
}

export function ConfirmHost() {
  const pending = useConfirm((s) => s.pending);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!pending) return;
    (pending.danger ? cancelRef : okRef).current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending]);

  if (!pending) return null;
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close(false)}>
      <div className="modal modal-confirm" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-text">
        <div className="confirm-body">
          {pending.danger && <span className="confirm-icon"><Icon name="alert" size={20} /></span>}
          <div>
            <h2 id="confirm-title">{pending.title}</h2>
            {pending.message && <p id="confirm-text" className="muted">{pending.message}</p>}
          </div>
        </div>
        <div className="modal-foot">
          <button ref={cancelRef} onClick={() => close(false)}>{pending.cancelLabel ?? "Abbrechen"}</button>
          <button ref={okRef} className={pending.danger ? "btn-danger" : "primary"} onClick={() => close(true)}>
            {pending.confirmLabel ?? "OK"}
          </button>
        </div>
      </div>
    </div>
  );
}
