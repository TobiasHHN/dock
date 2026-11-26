// Tipp-Effekt für fremd eingefügten Text (3.F5): reiner Scheduler ohne DOM.
// Text erscheint wortweise, nacheinander über alle Blöcke (eine globale Warteschlange), mit kleinen Pausen an
// Satzzeichen und zwischen Blöcken. Bei langem Rückstau wird schneller, damit alles in MAX_SECONDS fertig ist.

/** Grundtempo in Zeichen pro Sekunde (ruhig, etwa 6 Wörter/s). */
export const BASE_CPS = 40;
/** Obergrenze für die Gesamtdauer aller wartenden Texte; darüber hinaus wird das Tempo erhöht. */
export const MAX_SECONDS = 10;
/** Pause zwischen zwei Blöcken. */
export const BLOCK_GAP_MS = 140;

/** Wortgrenzen: kumulierte Einheiten (Code Points) je Wort inkl. folgendem Leerraum, plus Kosten (Zeitbudget in Zeichen). */
export function wordStops(text: string): { stops: number[]; costs: number[] } {
  const stops: number[] = [];
  const costs: number[] = [];
  let at = 0;
  for (const m of text.matchAll(/\S+\s*|\s+/g)) {
    const chunk = m[0];
    at += Array.from(chunk).length;
    const word = chunk.trimEnd();
    const pause = /[.!?:]$/.test(word) ? 9 : /[,;)]$/.test(word) ? 4 : 0;
    stops.push(at);
    costs.push(Math.max(1, Array.from(word).length) + pause);
  }
  return { stops, costs };
}

export interface TypeJob {
  id: string;
  stops: number[];
  costs: number[];
  /** Block ist an der Reihe (Cursor anzeigen). */
  onStart(): void;
  /** Sichtbar sind jetzt `shown` von insgesamt `stops.at(-1)` Einheiten. `false` = Job abbrechen. */
  onStep(shown: number, prev: number): boolean;
  onDone(): void;
}

export class Typewriter {
  private jobs: (TypeJob & { i: number; started: boolean })[] = [];
  private budget = 0;
  private peak = 0; // größter Rückstau seit die Schlange zuletzt leer war: das Tempo sinkt nicht wieder ab

  get busy() {
    return this.jobs.length > 0;
  }

  add(job: TypeJob) {
    this.cancel(job.id);
    this.jobs.push({ ...job, i: 0, started: false });
  }

  cancel(id: string) {
    this.jobs = this.jobs.filter((j) => j.id !== id);
  }

  /** Alles Wartende sofort zeigen (z. B. beim Verlassen der Seite). */
  flush() {
    for (const j of this.jobs) {
      if (!j.started) j.onStart();
      j.onStep(j.stops.at(-1) ?? 0, j.stops[j.i - 1] ?? 0);
      j.onDone();
    }
    this.jobs = [];
    this.budget = 0;
  }

  /** Zeit voranschreiten lassen; liefert true, solange noch etwas zu tun ist. */
  tick(dtMs: number): boolean {
    let job = this.jobs[0];
    if (!job) {
      this.budget = 0;
      this.peak = 0;
      return false;
    }
    const backlog = this.jobs.reduce((sum, j) => sum + j.costs.slice(j.i).reduce((a, b) => a + b, 0), 0);
    this.peak = Math.max(this.peak, backlog);
    const rate = Math.max(BASE_CPS, this.peak / MAX_SECONDS);
    this.budget += (rate * dtMs) / 1000;
    while (job) {
      if (!job.started) {
        job.started = true;
        job.onStart();
      }
      const prev = job.stops[job.i - 1] ?? 0;
      let advanced = false;
      while (job.i < job.stops.length && this.budget >= job.costs[job.i]) {
        this.budget -= job.costs[job.i];
        job.i++;
        advanced = true;
      }
      if (advanced && !job.onStep(job.stops[job.i - 1], prev)) {
        this.jobs.shift();
        job = this.jobs[0];
        continue;
      }
      if (job.i < job.stops.length) break;
      job.onDone();
      this.jobs.shift();
      this.budget = -(rate * BLOCK_GAP_MS) / 1000;
      job = this.jobs[0];
      if (this.budget < 0) break;
    }
    return this.jobs.length > 0;
  }
}
