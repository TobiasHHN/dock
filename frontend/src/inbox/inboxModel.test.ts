import { describe, expect, it } from "vitest";
import type { Notification, TaskListItem } from "../api";
import type { UserOut } from "../api/client";
import {
  canClaimTask, canReleaseTask, formatCandidates, formatDue, formatNotification, resultLabel, runStatusLabel,
} from "./inboxModel";

const ME_CHEF: UserOut = { id: "usr_chef", name: "Chef", email: "chef@example.com", roles: ["chef"] };
const ME_ANNA: UserOut = { id: "usr_anna", name: "Anna", email: "anna@example.com", roles: ["einkauf"] };

function makeNote(type: string, payload: Record<string, unknown> = {}): Notification {
  return {
    id: "ntf_1",
    recipient_id: "usr_chef",
    run_id: "run_1",
    task_id: "tsk_1",
    type,
    payload,
    created_at: "2026-11-26T10:00:00Z",
    read_at: null,
  };
}

function makeTaskItem(overrides: Partial<TaskListItem> = {}, taskOverrides: Partial<TaskListItem["task"]> = {}): TaskListItem {
  return {
    task: {
      id: "tsk_1",
      run_id: "run_1",
      step: "genehmigung",
      status: "open",
      candidates: { users: [], roles: ["chef"] },
      excluded: [],
      claimed_by: null,
      created_at: "2026-11-26T10:00:00Z",
      due_at: null,
      completed_by: null,
      completed_at: null,
      outcome: null,
      ...taskOverrides,
    },
    run_title: "Laptop für Ben",
    step_name: "Genehmigung",
    workflow_name: "Bestellprozess",
    can_act: true,
    claimed_by_name: null,
    ...overrides,
  };
}

describe("inboxModel", () => {
  it("formatiert alle Benachrichtigungstypen verständlich", () => {
    expect(formatNotification(makeNote("step_entered", { run_title: "Bestellung 1", step_name: "Genehmigung" }))).toEqual({
      title: "Neue Aufgabe: Genehmigung",
      detail: "Bestellung 1",
    });
    expect(formatNotification(makeNote("completed", { run_title: "Bestellung 1", label: "Bestellt" }))).toEqual({
      title: "Bestellung 1 abgeschlossen",
      detail: "Bestellt",
    });
    expect(formatNotification(makeNote("comment", { run_title: "Bestellung 1", actor_name: "Ben", text: "Dringend!" }))).toEqual({
      title: "Kommentar von Ben",
      detail: "Bestellung 1: Dringend!",
    });
    expect(formatNotification(makeNote("overdue", { run_title: "Bestellung 1", step_name: "Einkauf" }))).toEqual({
      title: "Frist überschritten: Einkauf",
      detail: "Bestellung 1",
    });
    expect(formatNotification(makeNote("unassigned", { run_title: "Bestellung 1", step_name: "Prüfung" }))).toEqual({
      title: "Keine Zuständigen für „Prüfung“",
      detail: "Bestellung 1",
    });
  });

  it("bewertet Fristen korrekt (überfällig, bald, normal)", () => {
    const now = Date.parse("2026-11-26T12:00:00Z");
    expect(formatDue(null, now)).toBeNull();
    expect(formatDue("2026-11-26T11:00:00Z", now)).toEqual({ text: "Überfällig", tone: "danger" });
    expect(formatDue("2026-11-26T18:00:00Z", now)?.tone).toBe("warn");
    expect(formatDue("2026-11-30T12:00:00Z", now)?.tone).toBe("neutral");
  });

  it("fasst Zuständige zusammen", () => {
    expect(formatCandidates({ users: [{ name: "Anna" }], roles: [{ name: "Chef" }] })).toBe("Anna, Chef");
    expect(formatCandidates(null)).toBe("");
  });

  it("liefert deutsche Statuslabels", () => {
    expect(runStatusLabel("active")).toBe("Aktiv");
    expect(runStatusLabel("completed")).toBe("Abgeschlossen");
    expect(runStatusLabel("cancelled")).toBe("Abgebrochen");
  });

  it("prüft Übernehmen und Freigeben", () => {
    const open = makeTaskItem();
    expect(canClaimTask(open)).toBe(true);
    expect(canReleaseTask(open.task, ME_CHEF)).toBe(false);

    const claimedByChef = makeTaskItem({}, { claimed_by: { type: "user", id: "usr_chef", name: "Chef" } });
    expect(canClaimTask(claimedByChef)).toBe(false);
    expect(canReleaseTask(claimedByChef.task, ME_CHEF)).toBe(true);
    expect(canReleaseTask(claimedByChef.task, ME_ANNA)).toBe(true); // Einkauf darf freigeben
  });
});

describe("resultLabel", () => {
  it("formuliert bekannte Outcomes als Ergebnis, sonst Button-Label", () => {
    expect(resultLabel({ outcome: "approved", label: "Genehmigen" })).toBe("Genehmigt");
    expect(resultLabel({ outcome: "rejected", label: "Ablehnen" })).toBe("Abgelehnt");
    expect(resultLabel({ outcome: "ordered", label: "Bestellen" })).toBe("Bestellt");
    expect(resultLabel({ outcome: "weiter", label: "Weiter" })).toBe("Weiter");
    expect(resultLabel(null)).toBe("");
  });
});
