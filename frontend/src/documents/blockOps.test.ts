import { describe, expect, it } from "vitest";
import { dropAfter } from "./blockOps";

const sibs = ["a", "b", "c", "d"].map((id) => ({ id }));

describe("dropAfter", () => {
  it("nach vorn: Marke vor dem ersten Block", () => {
    expect(dropAfter(sibs, "c", 0)).toBe("^");
  });
  it("nach hinten: Marke hinter dem letzten Block", () => {
    expect(dropAfter(sibs, "a", 4)).toBe("d");
  });
  it("in die Mitte nach unten (Zielindex wird um den gezogenen Block bereinigt)", () => {
    expect(dropAfter(sibs, "a", 3)).toBe("c");
  });
  it("in die Mitte nach oben", () => {
    expect(dropAfter(sibs, "d", 1)).toBe("a");
  });
  it("Marke direkt vor oder hinter sich selbst ändert nichts", () => {
    expect(dropAfter(sibs, "b", 1)).toBeNull();
    expect(dropAfter(sibs, "b", 2)).toBeNull();
    expect(dropAfter(sibs, "a", 0)).toBeNull();
    expect(dropAfter(sibs, "d", 4)).toBeNull();
  });
  it("unbekannter Block", () => {
    expect(dropAfter(sibs, "x", 1)).toBeNull();
  });
});
