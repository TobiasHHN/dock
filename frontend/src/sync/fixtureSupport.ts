// Lader und Vergleichslogik für spec/fixtures (Regeln: spec/fixtures/README.md).
// Python-Gegenstück: backend/tests/fixture_support.py. Beide müssen sich gleich verhalten.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const posix = (p: string) => p.split("\\").join("/"); // Windows: Pfade mit "/" vergleichen
export const FIXTURE_ROOT = posix(resolve(dirname(fileURLToPath(import.meta.url)), "../../../spec/fixtures"));
export const KINDS = ["ops", "expression", "import", "text_ot"];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any;
export type Fixture = Json;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : p.endsWith(".json") ? [p] : [];
  });
}

export function loadAll(): [string, Fixture][] {
  return walk(FIXTURE_ROOT)
    .sort()
    .map((p) => [posix(relative(FIXTURE_ROOT, p)), JSON.parse(readFileSync(p, "utf8"))]);
}

export function forRunner(runner = "vitest", kind?: string): [string, Fixture][] {
  return loadAll().filter(([, f]) => f.runners.includes(runner) && (!kind || f.kind === kind));
}

const isObj = (v: unknown): v is Record<string, Json> => typeof v === "object" && v !== null && !Array.isArray(v);

/** Teilvergleich mit Platzhaltern. Gibt Abweichungen zurück (leer = passt). */
export function matches(expected: Json, actual: Json, binds: Record<string, Json> = {}, path = "$"): string[] {
  if (expected === "<any>") return [];
  if (typeof expected === "string" && expected.startsWith("<bind:") && expected.endsWith(">")) {
    const name = expected.slice(6, -1);
    if (!(name in binds)) {
      binds[name] = actual;
      return [];
    }
    return binds[name] === actual ? [] : [`${path}: ${JSON.stringify(actual)} != gebundener Wert ${JSON.stringify(binds[name])} (${name})`];
  }
  if (isObj(expected)) {
    if (!isObj(actual)) return [`${path}: Objekt erwartet, bekam ${JSON.stringify(actual)}`];
    return Object.entries(expected).flatMap(([k, v]) =>
      k in actual ? matches(v, actual[k], binds, `${path}.${k}`) : [`${path}.${k}: fehlt`],
    );
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual) || actual.length !== expected.length)
      return [`${path}: Liste der Länge ${expected.length} erwartet, bekam ${JSON.stringify(actual)}`];
    return expected.flatMap((e, i) => matches(e, actual[i], binds, `${path}[${i}]`));
  }
  return expected === actual ? [] : [`${path}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`];
}

const byBytes = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0); // wie collate "C" (nur ASCII-Positionen)

export function checkOpsResult(fx: Fixture, after: Json): string[] {
  const errs: string[] = [];
  if ("expect_state" in fx) errs.push(...matches(fx.expect_state, after));
  for (const o of fx.expect_order ?? []) {
    const doc = after.documents.find((d: Json) => d.id === o.doc);
    const ids = doc.blocks
      .filter((b: Json) => (b.parent_id ?? null) === o.parent)
      .sort((a: Json, b: Json) => byBytes(a.position, b.position))
      .map((b: Json) => b.id);
    if (JSON.stringify(ids) !== JSON.stringify(o.ids)) errs.push(`Reihenfolge in ${o.doc}: ${ids} != ${o.ids}`);
  }
  for (const [docId, ids] of Object.entries<string[]>(fx.expect_block_ids ?? {})) {
    const doc = after.documents.find((d: Json) => d.id === docId);
    const got = doc.blocks.map((b: Json) => b.id).sort();
    if (JSON.stringify(got) !== JSON.stringify([...ids].sort())) errs.push(`Blöcke in ${docId}: ${got} != ${ids}`);
  }
  return errs;
}

export function checkError(fx: Fixture, code: string, message: string, fields: Record<string, Json> = {}): string[] {
  const exp = fx.expect_error;
  const errs: string[] = [];
  if (code !== exp.code) errs.push(`Fehlercode ${code} != ${exp.code}`);
  for (const f of exp.fields ?? []) if (!(f in fields)) errs.push(`Feldfehler für '${f}' fehlt`);
  if (exp.message_contains && !message.includes(exp.message_contains)) errs.push(`Meldung enthält nicht '${exp.message_contains}'`);
  return errs;
}
