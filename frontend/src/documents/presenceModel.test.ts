import { describe, expect, it } from "vitest";
import { actorColor, scrollCorrection } from "./presenceModel";

describe("actorColor", () => {
  it("ist pro Schlüssel stabil und unterscheidet Personen", () => {
    expect(actorColor("usr_anna")).toBe(actorColor("usr_anna"));
    expect(actorColor("usr_anna")).not.toBe(actorColor("usr_ben"));
    expect(actorColor("x")).toMatch(/^hsl\(\d+ 55% 48%\)$/);
  });
});

describe("scrollCorrection", () => {
  it("gleicht eine Verschiebung des Ankers aus", () => {
    expect(scrollCorrection(120, 180, 400)).toBe(60);
    expect(scrollCorrection(120, 90, 400)).toBe(-30);
  });
  it("ignoriert Rundung und den Seitenanfang", () => {
    expect(scrollCorrection(120, 121, 400)).toBe(0);
    expect(scrollCorrection(120, 180, 0)).toBe(0);
  });
});
