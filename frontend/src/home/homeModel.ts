// Home-Baum: Jeder Workflow hat ein Übersichtsdokument (owner = { workflow, step: null }, angelegt mit
// `workflow.create`), darunter hängen seine Schritt-Dokumente (owner.step gesetzt oder in `documents` der
// Definition). Alles andere sind freie Dokumente. Reine Funktionen, getestet in homeModel.test.ts.

export type HomeDoc = {
  id: string; title?: string; owner?: { workflow: string; step: string | null } | null;
  updated_at?: string | null;
};
export type HomeWorkflow = { id: string; key?: string; name?: string; documents?: string[] };
export type HomeGroup = { workflow: HomeWorkflow; overview: HomeDoc | null; children: HomeDoc[] };

const byTitle = (a: HomeDoc, b: HomeDoc) => (a.title ?? "").localeCompare(b.title ?? "", "de");
const byUpdated = (a: HomeDoc, b: HomeDoc) => (b.updated_at ?? "").localeCompare(a.updated_at ?? "") || byTitle(a, b);

export function groupDocuments(docs: HomeDoc[], workflows: HomeWorkflow[]): { groups: HomeGroup[]; loose: HomeDoc[] } {
  const byId = new Map(docs.map((d) => [d.id, d]));
  const placed = new Set<string>();
  const matches = (w: HomeWorkflow, ref: string | undefined) => !!ref && (ref === w.id || (!!w.key && ref === w.key));

  const groups = workflows.map((w): HomeGroup => {
    const overview = docs.find((d) => matches(w, d.owner?.workflow) && !d.owner?.step) ?? null;
    if (overview) placed.add(overview.id);
    // Reihenfolge der Schritte aus der Definition, danach weitere Dokumente des Workflows nach Titel
    const stepIds = (w.documents ?? []).filter((id) => byId.has(id) && id !== overview?.id);
    const owned = docs
      .filter((d) => matches(w, d.owner?.workflow) && d.owner?.step && !stepIds.includes(d.id))
      .sort(byTitle)
      .map((d) => d.id);
    const children = [...new Set([...stepIds, ...owned])].map((id) => byId.get(id)!);
    children.forEach((d) => placed.add(d.id));
    return { workflow: w, overview, children };
  });

  groups.sort((a, b) => (a.overview?.title ?? a.workflow.name ?? "").localeCompare(b.overview?.title ?? b.workflow.name ?? "", "de"));
  const loose = docs.filter((d) => !placed.has(d.id)).sort(byUpdated);
  return { groups, loose };
}

const STORAGE_KEY = "dock.home.expanded";

/** Aufgeklappte Workflows (pro Browser gemerkt). Standard: zugeklappt. */
export function loadExpanded(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

export function saveExpanded(ids: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]));
  } catch {
    /* privates Fenster o. Ä.: dann eben nicht gemerkt */
  }
}
