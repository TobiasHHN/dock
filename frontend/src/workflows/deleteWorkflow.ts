// Workflow löschen (B28): Workflow samt Übersichtsdokument (ergänzt die Pipeline) und den Schritt-Dokumenten,
// die ihm gehören (owner.workflow). Erst `workflow.delete`, dann die Dokumente: so ist die Verwendung als
// `step.document` schon weg. Aktive Runs oder Workflow-Blöcke in anderen Dokumenten lehnt der Server ab (IN_USE).
import type { Op } from "../api";
import { BatchRejected, submit, sync } from "../sync/store";
import { confirmDialog } from "../ui/confirm";
import { toast } from "../ui/toasts";

type Doc = { id: string; title?: string; owner?: { workflow: string; step: string | null } | null };
type Wf = { id: string; key?: string; name?: string };

/** Schritt-Dokumente, die dem Workflow gehören (das Übersichtsdokument löscht die Pipeline selbst). */
export function ownedStepDocs(wf: Wf, docs: Doc[]): Doc[] {
  return docs.filter((d) => d.owner?.step && (d.owner.workflow === wf.id || (!!wf.key && d.owner.workflow === wf.key)));
}

export function workflowDeleteOps(wf: Wf, docs: Doc[]): Op[] {
  return [
    { op: "workflow.delete", workflow: wf.id },
    ...ownedStepDocs(wf, docs).map((d) => ({ op: "doc.delete", doc: d.id })),
  ] as Op[];
}

/** Fragt nach und löscht. Liefert true, wenn gelöscht wurde. */
export async function deleteWorkflow(wf: Wf): Promise<boolean> {
  const docs = (sync.store.getState().channels.workspace?.view?.documents ?? []) as Doc[];
  const steps = ownedStepDocs(wf, docs);
  const ok = await confirmDialog({
    title: `Workflow „${wf.name ?? wf.key ?? wf.id}“ löschen?`,
    message:
      `Gelöscht werden der Workflow, sein Übersichtsdokument` +
      (steps.length ? ` und ${steps.length === 1 ? "das Schritt-Dokument" : `die ${steps.length} Schritt-Dokumente`} (${steps.map((d) => `„${d.title || d.id}“`).join(", ")})` : "") +
      ". Abgeschlossene Abläufe werden mitgelöscht. Mit laufenden Abläufen ist das Löschen nicht möglich.",
    confirmLabel: "Workflow löschen", danger: true,
  });
  if (!ok) return false;
  try {
    await submit(workflowDeleteOps(wf, docs));
    toast("Workflow gelöscht");
    return true;
  } catch (e) {
    const msg = e instanceof BatchRejected ? e.error.message : (e as Error).message;
    toast(`Löschen nicht möglich: ${msg}`, "error");
    return false;
  }
}
