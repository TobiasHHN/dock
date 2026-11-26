// Reine Logik für Aufgabenliste, Anträge und Benachrichtigungen (Task 4.5, L 5.9, L 5.10, T 5.7).
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Notification, TaskListItem } from "../api";
import type { UserOut } from "../api/client";
import { sync } from "../sync/store";
import { relativeTime } from "../ui/icons";

export function formatNotification(n: Notification): { title: string; detail: string } {
  const p = (n.payload ?? {}) as Record<string, unknown>;
  const runTitle = typeof p.run_title === "string" && p.run_title ? p.run_title : "Ablauf";
  const stepName = typeof p.step_name === "string" && p.step_name
    ? p.step_name
    : typeof p.step === "string" && p.step
      ? p.step
      : "";
  const label = typeof p.label === "string" ? p.label : "";
  const actorName = typeof p.actor_name === "string" ? p.actor_name : "";
  const text = typeof p.text === "string" ? p.text : "";

  switch (n.type) {
    case "step_entered":
      return {
        title: `Neue Aufgabe: ${stepName || "Schritt"}`,
        detail: runTitle,
      };
    case "step_completed":
      return {
        title: `Schritt „${stepName || "Schritt"}“ erledigt`,
        detail: label ? `${runTitle} · ${label}` : runTitle,
      };
    case "completed":
      return {
        title: `${runTitle} abgeschlossen`,
        detail: label || "Abgeschlossen",
      };
    case "cancelled":
      return {
        title: `${runTitle} abgebrochen`,
        detail: actorName ? `von ${actorName}` : "",
      };
    case "comment":
      return {
        title: actorName ? `Kommentar von ${actorName}` : "Neuer Kommentar",
        detail: text ? `${runTitle}: ${text}` : runTitle,
      };
    case "overdue":
      return {
        title: `Frist überschritten: ${stepName || "Aufgabe"}`,
        detail: runTitle,
      };
    case "unassigned":
      return {
        title: `Keine Zuständigen für „${stepName || "Schritt"}“`,
        detail: runTitle,
      };
    default:
      return {
        title: runTitle,
        detail: stepName || label || n.type,
      };
  }
}

export function formatDue(
  dueAt: string | null | undefined,
  now = Date.now(),
): { text: string; tone: "danger" | "warn" | "neutral" } | null {
  if (!dueAt) return null;
  const ts = Date.parse(dueAt);
  if (Number.isNaN(ts)) return null;
  const diff = ts - now;
  if (diff < 0) return { text: "Überfällig", tone: "danger" };
  const rel = relativeTime(dueAt);
  if (diff < 24 * 3600 * 1000) return { text: rel ? `fällig ${rel}` : "Bald fällig", tone: "warn" };
  return { text: rel ? `fällig ${rel}` : "Frist gesetzt", tone: "neutral" };
}

export function formatCandidates(
  c: { users?: Record<string, string | undefined>[]; roles?: Record<string, string | undefined>[] } | null | undefined,
): string {
  if (!c) return "";
  const names = [
    ...(c.users ?? []).map((u) => u.name ?? u.id ?? ""),
    ...(c.roles ?? []).map((r) => r.name ?? r.key ?? ""),
  ].filter(Boolean);
  return names.join(", ");
}

export function runStatusLabel(status: "active" | "completed" | "cancelled"): string {
  switch (status) {
    case "active": return "Aktiv";
    case "completed": return "Abgeschlossen";
    case "cancelled": return "Abgebrochen";
  }
}

/** Gängige Outcomes als Ergebnis formuliert. Buttons heißen „Genehmigen“, der Status danach „Genehmigt“. */
const OUTCOME_LABELS: Record<string, string> = {
  approved: "Genehmigt",
  rejected: "Abgelehnt",
  ordered: "Bestellt",
  submitted: "Eingereicht",
  done: "Erledigt",
  completed: "Erledigt",
  accepted: "Angenommen",
  declined: "Abgelehnt",
};

/** Lesbares Ergebnis eines Runs oder Schritts: bekanntes Outcome, sonst das Button-Label. */
export function resultLabel(result: { outcome?: string | null; label?: string | null } | null | undefined): string {
  if (!result) return "";
  return (result.outcome && OUTCOME_LABELS[result.outcome]) || result.label || "";
}

export function canClaimTask(item: TaskListItem): boolean {
  return item.task.status === "open" && !item.task.claimed_by && item.can_act;
}

export function canReleaseTask(task: TaskListItem["task"], me: UserOut | null): boolean {
  if (task.status !== "open" || !task.claimed_by || !me) return false;
  return task.claimed_by.id === me.id || me.roles.includes("einkauf");
}

/** Invalidiert React-Query-Keys automatisch bei Live-Events auf einem Sync-Kanal. */
export function useChannelInvalidate(channel: string | null, queryKeys: readonly (readonly unknown[])[]) {
  const qc = useQueryClient();
  const keySig = JSON.stringify(queryKeys);
  useEffect(() => {
    if (!channel) return;
    return sync.listen(channel, (ev) => {
      if (ev.type === "ops" && ev.ops.length > 0 && ev.ops.every((o) => typeof o.op === "string" && o.op.startsWith("draft."))) {
        return;
      }
      for (const k of queryKeys) qc.invalidateQueries({ queryKey: [...k] });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel, qc, keySig]);
}
