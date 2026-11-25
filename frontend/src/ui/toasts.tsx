// Kurze Hinweise unten rechts (z. B. abgelehnte Änderung, L 7.4 „Hinweis anzeigen“).
import { create } from "zustand";

type Toast = { id: number; text: string; kind: "info" | "error" };

type ToastState = { toasts: Toast[]; show: (text: string, kind?: Toast["kind"]) => void; dismiss: (id: number) => void };

let counter = 0;

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  show: (text, kind = "info") => {
    const id = ++counter;
    set({ toasts: [...get().toasts, { id, text, kind }] });
    setTimeout(() => get().dismiss(id), kind === "error" ? 7000 : 4000);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

export const toast = (text: string, kind: Toast["kind"] = "info") => useToasts.getState().show(text, kind);

export function Toasts() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="toasts" role="status">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} onClick={() => dismiss(t.id)}>
          {t.text}
        </div>
      ))}
    </div>
  );
}
