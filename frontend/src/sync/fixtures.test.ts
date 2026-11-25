// Lädt spec/fixtures. Formtests laufen immer; Ausführungstests sind übersprungen, bis `apply.ts` bzw.
// `expressions.ts` existieren (Task 2.3 / 3.2) und werden dann automatisch aktiv (siehe spec/fixtures/README.md).
import { describe, expect, it } from "vitest";
import { FIXTURE_ROOT, KINDS, checkError, checkOpsResult, forRunner, loadAll, matches } from "./fixtureSupport";

const applyMods = import.meta.glob("./apply.ts");
const exprMods = import.meta.glob("./expressions.ts");
const all = loadAll();

describe("fixtures: Form", () => {
  it("es gibt je Bereich mindestens zwei Fälle", () => {
    for (const sub of ["tables", "documents", "expressions", "imports"])
      expect(all.filter(([n]) => n.startsWith(sub + "/")).length, sub).toBeGreaterThanOrEqual(2);
  });

  it.each(all)("%s hat gültige Struktur", (_name, fx) => {
    expect(KINDS).toContain(fx.kind);
    expect(fx.name).toBeTruthy();
    if (fx.kind === "ops") {
      expect(fx.ops.length).toBeGreaterThan(0);
      expect(fx.ops.every((o: { op?: string }) => typeof o.op === "string")).toBe(true);
    } else if (fx.kind === "expression") {
      expect(fx.cases.length).toBeGreaterThan(0);
    } else {
      expect(fx.expect_ops.length).toBeGreaterThan(0);
    }
  });
});

describe("fixtures: Ausführung (ops)", () => {
  const cases = forRunner("vitest", "ops");
  it.each(cases)("%s", async (_name, fx) => {
    const loader = applyMods["./apply.ts"];
    if (!loader) return; // noch nicht implementiert (Task 2.3)
    const { applyOps, OpError } = (await loader()) as {
      applyOps: (s: unknown, o: unknown[]) => unknown;
      OpError: new (...a: never[]) => Error & { code: string; fields: Record<string, unknown> };
    };
    const state = structuredClone(fx.state);
    let after: unknown = state;
    if (fx.expect_error) {
      try {
        applyOps(structuredClone(state), fx.ops);
        throw new Error("Fehler erwartet");
      } catch (e) {
        if (!(e instanceof OpError)) throw e;
        expect(checkError(fx, e.code, e.message, e.fields)).toEqual([]);
      }
    } else {
      after = applyOps(state, fx.ops);
    }
    expect(checkOpsResult(fx, after)).toEqual([]);
  });
});

describe("fixtures: Ausführung (expression)", () => {
  it.each(forRunner("vitest", "expression"))("%s", async (_name, fx) => {
    const loader = exprMods["./expressions.ts"];
    if (!loader) return; // noch nicht implementiert (Task 3.2)
    const { evaluate } = (await loader()) as { evaluate: (e: string, c: unknown) => unknown };
    for (const c of fx.cases) {
      if (c.expect_error) expect(() => evaluate(c.expr, fx.context), c.expr).toThrow(c.expect_error);
      else expect(evaluate(c.expr, fx.context), c.expr).toEqual(c.expect);
    }
  });
});

describe("fixtures: Vergleich", () => {
  it("Teilvergleich, Länge, Zahlen und Platzhalter", () => {
    expect(matches({ a: 1 }, { a: 1, b: 2 })).toEqual([]);
    expect(matches({ a: 1 }, { b: 2 }).length).toBe(1);
    expect(matches([1, { x: "<any>" }], [1, { x: "q" }])).toEqual([]);
    expect(matches([1, 2], [1, 2, 3]).length).toBe(1);
    expect(matches(498, 498.0)).toEqual([]);
    expect(matches(["<bind:t>", "<bind:t>"], ["a", "a"])).toEqual([]);
    expect(matches(["<bind:t>", "<bind:t>"], ["a", "b"]).length).toBe(1);
  });

  it("Fixture-Ordner ist erreichbar", () => {
    expect(FIXTURE_ROOT.endsWith("spec/fixtures")).toBe(true);
  });
});
