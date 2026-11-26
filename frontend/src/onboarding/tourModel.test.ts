import { beforeEach, describe, expect, it, vi } from "vitest";
import { GUIDE_STEPS, TOUR_STEPS, clampStep, markTourSeen, placeCard, tourSeen } from "./tourModel";

describe("tourModel", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    });
  });

  it("merkt sich den Rundgang pro Nutzer", () => {
    expect(tourSeen("u1")).toBe(false);
    markTourSeen("u1");
    expect(tourSeen("u1")).toBe(true);
    expect(tourSeen("u2")).toBe(false);
  });

  it("begrenzt den Schritt auf den gültigen Bereich", () => {
    expect(clampStep(-1)).toBe(0);
    expect(clampStep(99)).toBe(TOUR_STEPS.length - 1);
    expect(clampStep(2)).toBe(2);
  });

  it("hat eindeutige Schritt-IDs", () => {
    expect(new Set(TOUR_STEPS.map((s) => s.id)).size).toBe(TOUR_STEPS.length);
  });

  it("hat eindeutige Führungsschritte", () => {
    expect(new Set(GUIDE_STEPS.map((s) => s.id)).size).toBe(GUIDE_STEPS.length);
  });
});

describe("placeCard", () => {
  const vp = { width: 1000, height: 700 };
  const card = { width: 360, height: 200 };
  const target = { top: 100, left: 300, width: 200, height: 40 };

  it("stellt die Karte unter das Ziel, wenn dort Platz ist", () => {
    const p = placeCard(target, card, vp, "bottom");
    expect(p.side).toBe("bottom");
    expect(p.top).toBe(154);
    expect(p.left).toBe(220); // mittig zum Ziel
  });

  it("weicht nach oben aus, wenn unten kein Platz ist", () => {
    const p = placeCard({ top: 600, left: 300, width: 200, height: 40 }, card, vp, "bottom");
    expect(p.side).toBe("top");
    expect(p.top).toBe(600 - 14 - 200);
  });

  it("bleibt im Fenster und fällt ohne Ziel auf die Mitte zurück", () => {
    expect(placeCard({ top: 100, left: 0, width: 20, height: 40 }, card, vp).left).toBe(12);
    expect(placeCard(null, card, vp).side).toBe("center");
    expect(placeCard({ top: 0, left: 0, width: 1000, height: 700 }, card, vp).side).toBe("center");
  });
});
