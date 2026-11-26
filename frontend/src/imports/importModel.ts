// Logik des Imports im Browser (Task 3.8, L 8.3): Dateityp, Parsing der Antwort `ImportPlan`,
// Fehlertexte für 413/422 und das Ziel der Navigation nach dem Übernehmen.
import type { components } from "../api/types";

export type ImportPlan = components["schemas"]["ImportPlan"];
export type ImportKind = "xlsx" | "docx";

export type PlannedTable = { id: string; key: string; name: string; columns: number; rows: number };
export type PlannedDocument = { id: string; title: string; hasForm: boolean; fields: number; lineItems: number; actions: number };
export type PlanSummary = {
  tables: PlannedTable[];
  documents: PlannedDocument[];
  boundTable: { id: string; key: string } | null;
  warnings: string[];
};

export const MAX_MB = 10;

export function detectKind(name: string): ImportKind | null {
  const ext = name.toLowerCase().split(".").pop();
  return ext === "xlsx" ? "xlsx" : ext === "docx" ? "docx" : null;
}

const obj = (v: unknown): Record<string, unknown> => (v && typeof v === "object" ? (v as Record<string, unknown>) : {});
const list = (v: unknown): Record<string, unknown>[] => (Array.isArray(v) ? v.map(obj) : []);
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const num = (v: unknown): number => (typeof v === "number" ? v : 0);

/** Liest `created` und `warnings` robust aus der Antwort (die Form von `created` ist im Schema offen). */
export function summarizePlan(plan: Pick<ImportPlan, "created" | "warnings">): PlanSummary {
  const created = obj(plan.created);
  const tables = list(created.tables).map((t) => ({
    id: str(t.id), key: str(t.key), name: str(t.name, str(t.key, "Tabelle")),
    columns: Array.isArray(t.columns) ? t.columns.length : 0, rows: num(t.rows),
  }));
  const documents = list(created.documents).map((d) => {
    const form = d.form ? obj(d.form) : null;
    return {
      id: str(d.id), title: str(d.title, "Ohne Titel"), hasForm: !!form,
      fields: form ? Object.keys(obj(form.fields)).length : 0,
      lineItems: form ? Object.keys(obj(form.line_items)).length : 0,
      actions: form && Array.isArray(form.actions) ? form.actions.length : 0,
    };
  });
  const bt = created.bound_table ? obj(created.bound_table) : null;
  return {
    tables, documents,
    boundTable: bt && bt.id ? { id: str(bt.id), key: str(bt.key) } : null,
    warnings: (plan.warnings ?? []).filter((w) => typeof w === "string"),
  };
}

/** Wohin nach dem Übernehmen: Dokument zuerst (Word), sonst die erste Tabelle, sonst Home. */
export function targetPath(s: PlanSummary): string {
  if (s.documents[0]?.id) return `/documents/${s.documents[0].id}`;
  if (s.tables[0]?.id) return `/tables/${s.tables[0].id}`;
  return "/";
}

export function emptyPlanMessage(s: PlanSummary): string | null {
  return s.tables.length || s.documents.length ? null : "Die Datei enthält nichts, was sich importieren lässt.";
}

/** Verständliche Meldung für fehlgeschlagene Uploads (siehe `routers.py`: 413, 422). */
export function importErrorText(status: number | null, message?: string): string {
  const m = message?.trim();
  switch (status) {
    case 413: return `Die Datei ist zu groß (erlaubt sind ${MAX_MB} MB).`;
    case 422: return m ? `Die Datei lässt sich nicht importieren: ${m}` : "Die Datei lässt sich nicht lesen. Ist es wirklich eine .xlsx- oder .docx-Datei?";
    case 401: return "Deine Sitzung ist abgelaufen. Bitte melde dich neu an.";
    case 403: return "Dafür fehlt dir die Berechtigung.";
    case 0: case null: return m || "Keine Verbindung zum Server.";
    default: return m || `Import fehlgeschlagen (${status}).`;
  }
}

/** Vorab-Prüfung im Browser, damit große oder falsche Dateien gar nicht erst hochgeladen werden. */
export function checkFile(file: { name: string; size: number }): { kind: ImportKind } | { error: string } {
  const kind = detectKind(file.name);
  if (!kind) return { error: "Nur Excel- (.xlsx) und Word-Dateien (.docx) lassen sich importieren." };
  if (file.size > MAX_MB * 1024 * 1024) return { error: importErrorText(413) };
  return { kind };
}

export type ImportParams = { sheet?: string; title?: string; bindTable?: string };

export function buildFormData(kind: ImportKind, file: File, p: ImportParams): FormData {
  const fd = new FormData();
  fd.append("file", file);
  if (kind === "xlsx" && p.sheet) fd.append("sheet", p.sheet);
  if (kind === "docx") {
    if (p.title?.trim()) fd.append("title", p.title.trim());
    if (p.bindTable) fd.append("bind_table", p.bindTable);
  }
  return fd;
}

export function includeOp(importId: string) {
  return { op: "import.include", import_id: importId } as const;
}
