// Rundgang beim ersten Besuch: Schritte und „schon gesehen“-Merker (pro Nutzer und Browser).
import type { IconName } from "../ui/icons";

export type TourVisual = "welcome" | "documents" | "tasks" | "requests" | "search" | "mcp";

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
];

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
