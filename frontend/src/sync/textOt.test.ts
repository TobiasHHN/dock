// Vollständige Prüfung der Transformation (TP1) auf einem kurzen Text: für JEDES Paar gleichzeitiger Edits
// müssen Server (a, dann b verschoben) und Client von b (b, dann a verschoben) denselben Text ergeben.
import { describe, expect, it } from "vitest";
import { type Edit, applyEdit, transformOne } from "./textOt";

const S = [{ t: "text", text: "abcde" }, { t: "mention", target: "usr_anna" }, { t: "text", text: "f", marks: ["bold"] }];
const LEN = 7;

function allEdits(ins: string): Edit[] {
  const out: Edit[] = [];
  for (let f = 0; f <= LEN; f++)
    for (let t = f; t <= LEN; t++)
      for (const i of ["", ins]) if (!(f === t && i === "")) out.push({ from: f, to: t, insert: i, marks: [] });
  return out;
}

describe("textOt: Konvergenz für alle Edit-Paare", () => {
  it("Server- und Client-Reihenfolge ergeben denselben Inhalt", () => {
    const bad: string[] = [];
    for (const a of allEdits("X")) {
      for (const b of allEdits("YZ")) {
        const server = JSON.stringify(applyEdit(applyEdit(S, a), transformOne(b, a, "after")));
        const client = JSON.stringify(applyEdit(applyEdit(S, b), transformOne(a, b, "before")));
        if (server !== client) bad.push(`a=${JSON.stringify(a)} b=${JSON.stringify(b)}: ${server} != ${client}`);
      }
    }
    expect(bad.slice(0, 5)).toEqual([]);
  });
});
