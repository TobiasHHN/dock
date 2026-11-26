import { describe, expect, it } from "vitest";
import { BASE_CPS, type TypeJob, Typewriter, wordStops } from "./typewriterQueue";

function job(id: string, text: string, log: string[] = []): TypeJob {
  const { stops, costs } = wordStops(text);
  return {
    id, stops, costs,
    onStart: () => log.push(`${id}:start`),
    onStep: (shown) => (log.push(`${id}:${shown}`), true),
    onDone: () => log.push(`${id}:done`),
  };
}

describe("wordStops", () => {
  it("teilt in Wörter inkl. Leerraum und zählt Code Points", () => {
    expect(wordStops("Hallo Welt 😀").stops).toEqual([6, 11, 12]);
  });
  it("gibt Satzzeichen eine Pause", () => {
    const { costs } = wordStops("Ende. Weiter, ja");
    expect(costs[0]).toBeGreaterThan(costs[1]);
    expect(costs[1]).toBeGreaterThan(costs[2]);
  });
});

describe("Typewriter", () => {
  it("zeigt Wörter nacheinander im Grundtempo", () => {
    const log: string[] = [];
    const tw = new Typewriter();
    tw.add(job("a", "eins zwei drei", log));
    tw.tick(1000 / BASE_CPS * 4.5); // reicht für das erste Wort (4 Zeichen)
    expect(log).toEqual(["a:start", "a:5"]);
  });

  it("arbeitet Blöcke der Reihe nach ab und wartet dazwischen", () => {
    const log: string[] = [];
    const tw = new Typewriter();
    tw.add(job("a", "ab", log));
    tw.add(job("b", "cd", log));
    tw.tick(1000);
    expect(log).toEqual(["a:start", "a:2", "a:done"]);
    expect(tw.tick(10)).toBe(true); // Blockpause
    tw.tick(1000);
    expect(log.at(-1)).toBe("b:done");
    expect(tw.busy).toBe(false);
  });

  it("wird bei langem Rückstau schneller und bleibt unter der Obergrenze", () => {
    const tw = new Typewriter();
    const long = Array.from({ length: 800 }, () => "wort").join(" ");
    let done = false;
    const j = job("a", long);
    j.onDone = () => (done = true);
    tw.add(j);
    let ms = 0;
    while (tw.tick(16)) ms += 16;
    expect(done).toBe(true);
    expect(ms).toBeLessThan(24500);
  });

  it("bricht ab, wenn onStep false liefert, und flush zeigt alles", () => {
    const tw = new Typewriter();
    const aborted = job("a", "eins zwei");
    aborted.onStep = () => false;
    tw.add(aborted);
    tw.tick(1000);
    expect(tw.busy).toBe(false);
    const log: string[] = [];
    tw.add(job("b", "eins zwei", log));
    tw.flush();
    expect(log).toEqual(["b:start", "b:9", "b:done"]);
  });
});
