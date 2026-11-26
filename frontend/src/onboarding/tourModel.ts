// Rundgang beim ersten Besuch: Schritte und „schon gesehen“-Merker (pro Nutzer und Browser).
import type { IconName } from "../ui/icons";

export type TourVisual = "welcome" | "documents" | "tasks" | "requests" | "search" | "mcp" | "start" | "collab" | "sheets";

export type TourStep = {
  id: string;
  visual: TourVisual;
  icon: IconName;
  title: string;
  text: string;
};

export const TOUR_STEPS: TourStep[] = [
  {
    id: "welcome",
    visual: "welcome",
    icon: "home",
    title: "Willkommen bei Dock",
    text: "Dokumente, Tabellen und Abläufe an einem Ort. In wenigen Schritten zeigen wir dir, wo du was findest.",
  },
  {
    id: "documents",
    visual: "documents",
    icon: "file",
    title: "Alles beginnt mit Dokumenten",
    text: "Auf der Startseite findest du alle Dokumente. Lege neue an, importiere Word- und Excel-Dateien oder ziehe sie einfach auf die Seite. Abläufe lassen sich aufklappen und zeigen ihre Schritt-Dokumente.",
  },
  {
    id: "tasks",
    visual: "tasks",
    icon: "tasks",
    title: "Zu erledigen",
    text: "Wartet ein Schritt auf dich oder deine Rolle, zeigt dir die Zahl neben „Zu erledigen“, wie viel offen ist. Übernimm die Aufgabe, bearbeite sie und gib sie frei.",
  },
  {
    id: "requests",
    visual: "requests",
    icon: "inbox",
    title: "Meine Vorgänge",
    text: "Hier siehst du, was du gestartet hast: in welchem Schritt es steht, wer gerade zuständig ist und wie es ausgegangen ist.",
  },
  {
    id: "search",
    visual: "search",
    icon: "search",
    title: "Suchen und auf dem Laufenden bleiben",
    text: "Die Suche oben findet Dokumente, Tabellen und Abläufe. Die Glocke meldet dir in Echtzeit, wenn sich etwas für dich ändert.",
  },
  {
    id: "mcp",
    visual: "mcp",
    icon: "plug",
    title: "Auch per KI-Assistent",
    text: "Dock lässt sich zusätzlich über MCP mit einem Assistenten wie Claude oder ChatGPT bedienen. Er arbeitet mit deinen Rechten. Details und die Server-Adresse findest du im Profilmenü. Dort startest du auch diesen Rundgang jederzeit neu.",
  },
  {
    id: "start",
    visual: "start",
    icon: "file",
    title: "Jetzt bist du dran",
    text: "Am besten lernst du Dock beim Ausprobieren. Wir legen ein leeres Dokument für dich an und zeigen dir dort Schritt für Schritt, wie Bearbeiten, Zusammenarbeit, Tabellen und Workflows funktionieren. Das dauert etwa zwei Minuten.",
  },
];

// ── Führung im Übungsdokument ────────────────────────────────────────────────

export type Placement = "top" | "bottom";

export type GuideStep = {
  id: string;
  title: string;
  text: string;
  /** CSS-Selektor des hervorgehobenen Elements; ohne Treffer erscheint die Karte mittig. */
  target?: string;
  placement?: Placement;
  visual?: TourVisual;
  /** Hintergrund abdunkeln? Bei Schritten mit Menüs aus, damit diese nicht grau werden. */
  dim?: boolean;
  /** Aufforderung zum Mitmachen: erkennt Eingaben im Selektor und meldet „geschafft“. */
  detect?: { selector: string; events: ("input" | "keydown" | "click")[]; hint: string; done: string };
  /** Zeigt die Randleiste (Plus und Griff) des ersten Blocks, die sonst nur beim Darüberfahren erscheint. */
  showGutter?: boolean;
};

export const GUIDE_STEPS: GuideStep[] = [
  {
    id: "title",
    title: "Gib deinem Dokument einen Namen",
    text: "Klicke auf den Titel und tippe los, zum Beispiel „Meine erste Bestellung“. Er wird automatisch gespeichert.",
    target: ".doc-title",
    detect: { selector: ".doc-title", events: ["input"], hint: "Probier es aus: tippe einen Titel.", done: "Super, der Titel steht." },
  },
  {
    id: "write",
    title: "Schreib den ersten Absatz",
    text: "Klicke in den Absatz darunter und schreib einen Satz. Enter beginnt einen neuen Block, Umschalt+Enter einen Zeilenumbruch. Mit Strg+B (⌘+B) wird Text fett, mit Strg+I (⌘+I) kursiv.",
    target: ".doc-body > .block:first-child",
    detect: { selector: ".doc-body .block", events: ["input", "keydown"], hint: "Probier es aus: schreib etwas.", done: "Genau so geht’s." },
  },
  {
    id: "blocks",
    title: "Jeder Absatz ist ein Block",
    text: "Fahre mit der Maus über einen Block. Links erscheinen das Plus, um darunter einen weiteren Block einzufügen, und der Griff: Ziehen verschiebt den Block, ein Klick öffnet das Menü zum Verschieben und Löschen.",
    target: ".doc-body > .block:first-child > .gutter",
    placement: "bottom",
    dim: false,
    showGutter: true,
    detect: { selector: ".block > .gutter button", events: ["click"], hint: "Probier es aus: klicke auf das Plus oder den Griff.", done: "Gut, so bearbeitest du einzelne Blöcke." },
  },
  {
    id: "add-block",
    title: "Überschriften, Listen und mehr",
    text: "Über „Block hinzufügen“ fügst du Überschriften, Aufzählungen, nummerierte Listen, Zitate, Code und Trennlinien ein. Auch hier kannst du später alles per Ziehen umsortieren.",
    target: ".add-block",
    placement: "top",
    dim: false,
    detect: { selector: ".add-block > button", events: ["click"], hint: "Probier es aus: öffne das Menü.", done: "Hier findest du alle Blocktypen." },
  },
  {
    id: "collab",
    title: "Gemeinsam in Echtzeit",
    text: "Mehrere Personen können gleichzeitig am selben Dokument arbeiten. Oben siehst du, wer gerade dabei ist. Änderungen erscheinen sofort ohne Neuladen, und ein Block, an dem jemand schreibt, ist für die Zeit markiert. Auch KI-Agenten arbeiten so mit: Sie sind als „im Auftrag von …“ gekennzeichnet.",
    target: ".doc-toolbar",
    placement: "bottom",
    visual: "collab",
  },
  {
    id: "sheets",
    title: "Tabellen und Workflows",
    text: "Unten siehst du die Blätter des Dokuments, wie in Excel: Blatt 1 ist dein Text. Eine Tabelle sammelt strukturierte Daten in Zeilen und Spalten, zum Beispiel Bestellungen. Ein Workflow ist ein Ablauf aus Schritten mit Zuständigen und Freigaben. Daraus entstehen die Aufgaben unter „Zu erledigen“.",
    target: ".sheet-bar",
    placement: "top",
    visual: "sheets",
  },
  {
    id: "embed",
    title: "Einbetten",
    text: "Mit dem Plus in der Blattleiste legst du neue Tabellen und Workflows an oder bettest vorhandene ein. Eine Tabelle erscheint dann als Ansicht mit Filter und ausgewählten Spalten, ein Workflow mit Startknopf. Die Daten bleiben live: Ändert sich die Tabelle, ändert sich auch jede Ansicht davon.",
    target: ".sheet-add",
    placement: "top",
    dim: false,
  },
  {
    id: "done",
    title: "Das war’s",
    text: "Du kennst jetzt die Grundlagen. Dein Übungsdokument bleibt erhalten, du kannst es jederzeit löschen. Den Rundgang startest du im Profilmenü neu.",
  },
];

// ── Positionierung der Führungskarte ─────────────────────────────────────────

export type Box = { top: number; left: number; width: number; height: number };

const GAP = 14;
const MARGIN = 12;

/** Platz für die Karte: bevorzugt auf der gewünschten Seite des Ziels, sonst gegenüber, sonst mittig; immer im Fenster. */
export function placeCard(
  target: Box | null, card: { width: number; height: number }, viewport: { width: number; height: number }, prefer: Placement = "bottom",
): { top: number; left: number; side: Placement | "center" } {
  const clampX = (x: number) => Math.min(Math.max(x, MARGIN), Math.max(MARGIN, viewport.width - card.width - MARGIN));
  const centered = () => ({
    top: Math.max(MARGIN, (viewport.height - card.height) / 2), left: clampX((viewport.width - card.width) / 2), side: "center" as const,
  });
  if (!target) return centered();
  const below = target.top + target.height + GAP;
  const above = target.top - GAP - card.height;
  const fitsBelow = below + card.height <= viewport.height - MARGIN;
  const fitsAbove = above >= MARGIN;
  const side: Placement | null = prefer === "bottom" ? (fitsBelow ? "bottom" : fitsAbove ? "top" : null) : fitsAbove ? "top" : fitsBelow ? "bottom" : null;
  if (!side) return centered();
  return { top: side === "bottom" ? below : above, left: clampX(target.left + target.width / 2 - card.width / 2), side };
}

const key = (userId: string) => `dock.tour.done.${userId}`;

export function tourSeen(userId: string): boolean {
  try {
    return localStorage.getItem(key(userId)) === "1";
  } catch {
    return true; // ohne Speicher lieber nicht bei jedem Laden stören
  }
}

export function markTourSeen(userId: string): void {
  try {
    localStorage.setItem(key(userId), "1");
  } catch {
    /* privates Fenster o. Ä.: dann eben nicht gemerkt */
  }
}

/** Schritt nach einer Navigation, begrenzt auf den gültigen Bereich. */
export function clampStep(index: number, total: number = TOUR_STEPS.length): number {
  return Math.min(Math.max(index, 0), total - 1);
}
