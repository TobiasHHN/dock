// Gemeinsamer Kontext der Dokument-Ansicht für alle Block-Komponenten.
import { createContext, useContext } from "react";
import type { Actor } from "../api";
import type { UserOut } from "../api/client";
import type { FlatBlock } from "./blockOps";

export type DocContextValue = {
  docId: string;
  channel: string;
  blocks: FlatBlock[];
  /** Darf der angemeldete Nutzer Blöcke ändern (Demo: nur `einkauf`, und nicht schreibgeschützt)? */
  editable: boolean;
  me: UserOut | null;
  users: Record<string, UserOut>;
  authors: Record<string, Actor>;
  /** Wer den Block gerade bearbeitet (nicht man selbst), sonst null (L 7.5). Textblöcke bleiben trotzdem
   *  bearbeitbar (gleichzeitiges Tippen per text.edit); Code-Blöcke und Löschen sind dann gesperrt. */
  lockedBy: (blockId: string) => string | null;
  /** Meldet `editing` für den Block (oder null beim Verlassen). */
  setEditing: (blockId: string | null) => void;
  /** Run-Kontext (für P3/P4: Formulare, Ausdrücke im Workflow-Schritt). */
  run?: string;
};

export const DocContext = createContext<DocContextValue | null>(null);

export function useDoc(): DocContextValue {
  const ctx = useContext(DocContext);
  if (!ctx) throw new Error("useDoc außerhalb von DocumentView");
  return ctx;
}

// Fokus-Anforderung nach Einfügen/Zusammenführen: der Textblock mit dieser ID setzt beim nächsten Rendern den Cursor.
let focusRequest: { id: string; at: number | "start" | "end" } | null = null;

export function requestFocus(id: string, at: number | "start" | "end" = "start") {
  focusRequest = { id, at };
}

export function takeFocusRequest(id: string): number | "start" | "end" | null {
  if (focusRequest?.id !== id) return null;
  const at = focusRequest.at;
  focusRequest = null;
  return at;
}
