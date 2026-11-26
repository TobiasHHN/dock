// Entwurf eines Formulars live aus dem Sync-Store (Task 3.4, L 4.4, L 7.6): im Workflow aus dem Kanal `run:<id>`
// (alle Zuständigen sehen denselben Entwurf), sonst der eigene Entwurf aus `user:<id>`.
import { useMemo } from "react";
import { useAuth } from "../api/client";
import { findDraft, scopeKey } from "../sync/drafts";
import { useChannel } from "../sync/store";
import type { Json } from "../sync/tableRules";
import { type Scope, draftScope } from "./formModel";

export type DraftState = {
  scope: Scope;
  /** Kanal, der den Entwurf trägt (= Name des Scopes). */
  channel: string;
  values: Record<string, Json>;
  ready: boolean;
};

const NONE = {};

export function useDraft(formBlock: string, run?: string): DraftState {
  const me = useAuth((s) => s.user);
  const scope = useMemo(() => draftScope(run, me?.id ?? ""), [run, me?.id]);
  const channel = scopeKey(scope);
  const ch = useChannel(me ? channel : null);
  const draft = findDraft(ch?.view, formBlock, channel);
  return { scope, channel, values: draft?.values ?? NONE, ready: ch?.status === "ready" };
}
