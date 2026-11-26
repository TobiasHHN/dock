import { beforeEach, describe, expect, it, vi } from "vitest";
import { TOUR_STEPS, clampStep, markTourSeen, tourSeen } from "./tourModel";

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
});
