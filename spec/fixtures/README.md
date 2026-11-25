# Gemeinsame Fixtures (`spec/fixtures/`)

Testfälle im Format **„Zustand + Operationen → erwarteter Zustand“**. Dieselben JSON-Dateien laufen in
`pytest` (`backend/tests/test_fixtures.py`) und `vitest` (`frontend/src/sync/fixtures.test.ts`), damit
Backend-Handler und Frontend-Spiegel (`sync/apply.ts`) nicht auseinanderlaufen (T 5.3).
Neue Fälle immer hier ergänzen, nie nur auf einer Seite testen.

## Aufbau

```
tables/       kind: ops          Tabellen-Ops (L 2)
documents/    kind: ops          Dokument-/Block-Ops (L 3)
expressions/  kind: expression   Ausdrücke {{ }} (L 4.5)
imports/      kind: import       Datei -> erwartete Ops (L 8.3), nur pytest
files/        Beispieldateien für die Import-Fälle (erzeugt von spec/make_sample_files.py)
```

Gemeinsame Felder: `name`, `description?`, `kind`, `runners` (`["pytest","vitest"]` oder nur `["pytest"]`).

## kind: `ops`

```jsonc
{
  "state":  { "tables": [ … ], "documents": [ … ] },    // Ausgangszustand, Werte nach Spalten-ID
  "ops":    [ { "op": "row.update", … } ],              // ein Batch, atomar
  "expect_state":     { … },                            // optional, Teilvergleich (siehe unten)
  "expect_order":     [ { "doc": "doc_1", "parent": null, "ids": ["b1","b_new","b2"] } ],  // Reihenfolge nach `position`
  "expect_block_ids": { "doc_1": ["h1"] },              // genau diese Blöcke existieren noch (Reihenfolge egal)
  "expect_error":     { "code": "VALIDATION", "fields": ["name"], "message_contains": "…" }  // Batch schlägt fehl
}
```

Bei `expect_error` muss der Zustand danach **unverändert** sein (Atomarität); `expect_state` beschreibt dann, was unverändert bleibt.

Schnittstellen, die die Runner aufrufen, sobald sie existieren (bis dahin werden die Ausführungstests übersprungen):

| | Python | TypeScript |
|---|---|---|
| Ops anwenden | `app.ops.memory.apply_ops(state: dict, ops: list[dict]) -> dict` | `sync/apply.ts`: `applyOps(state, ops): State` |
| Fehler | `app.ops.memory.OpError(code, message, fields: dict)` | `OpError { code, message, fields }` |
| Ausdruck | `app.domain.expressions.evaluate(expr, context)` | `sync/expressions.ts`: `evaluate(expr, context)` |
| Import xlsx | `app.imports.xlsx.parse_xlsx(bytes, sheet=None) -> ImportResult` | – |
| Import docx | `app.imports.docx.parse_docx(bytes, title, owner, bind_table) -> ImportResult` | – |

`apply_ops` ist die reine In-Memory-Fassung der Handler (ohne DB), geschrieben in Task 1.2/1.3/1.4. Das Frontend-Gegenstück in Task 2.3.

## kind: `expression`

```jsonc
{ "context": { "fields": {…}, "user": {…}, "run": {…}, "tables": { "kostenstellen": [ {"nummer":"4711", …} ] } },
  "cases": [ { "expr": "{{fields.anzahl}}", "expect": 3 },
             { "expr": "{{fields.tippfehler}}", "expect_error": "tippfehler" } ] }   // Teilstring der Fehlermeldung
```

`context.tables` ist die Datenquelle für `lookup(table, column, value, result_column)` (Tabellen-Keys, Zeilen mit Spalten-Keys).
Reine Typen-Regel: besteht der Text nur aus einem `{{ }}`, bleibt der Typ erhalten (L 4.5).

## kind: `import`

```jsonc
{ "source": "xlsx|docx", "file": "files/…", "params": { "bind_table": "bestellungen" },
  "state": { … },                         // optional: vorhandene Tabellen (für bind_table)
  "expect_ops": [ … ],                    // erwartete Ops, Teilvergleich mit Platzhaltern
  "expect_created": { … },                // optional: Teilvergleich auf `created`
  "expect_warnings": [],                  // exakt diese Warnungen (meist leer)
  "warnings_contain": ["gemischte Werte"], // jeder Teilstring kommt in mindestens einer Warnung vor
  "warnings_absent": ["nirgends hin"] }   // kein Teilstring darf vorkommen
```

Der Parser erzeugt IDs und Positionen selbst (T 2.9), deshalb Platzhalter:

- `"<any>"`: beliebiger Wert (ID, Position).
- `"<bind:x>"`: beim ersten Auftreten wird der Wert gemerkt, jedes weitere `"<bind:x>"` muss denselben Wert haben (z. B. `row.insert.table` == `table.create.id`).

Die `description` der Import-Fälle hält **Festlegungen** fest, wo `anwendungslogik.md` 8.3 offen lässt (Schlüssel der Zeilenliste, Tabellenname aus Word, Spaltentypen aus Word-Tabellen). Diese Fälle sind dort verbindlich.

## Teilvergleich (`expect_*`)

- **Objekte:** Jeder Schlüssel aus dem Erwarteten muss im Ergebnis vorkommen und passen. Zusätzliche Schlüssel im Ergebnis sind erlaubt.
- **Listen:** gleiche Länge, Element für Element verglichen.
- **Zahlen:** `498` und `498.0` sind gleich.
- Platzhalter wie oben.
