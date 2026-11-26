# Hackathon-Plan: Dokument-Plattform – Demo „Bestellfreigabe im Einkauf“

## Kontext

5 Engineers, ca. 1 Arbeitstag, Demo am Freitag (in 48 h). Jeder hat Claude Code (Pro-Plan, 20 $).

Dieser Plan beschreibt **was** gebaut wird (Features, Aufgaben, Reihenfolge, Abnahme). **Wie** es funktioniert und umgesetzt wird, steht ausschließlich in den beiden Fachdokumenten:

- **L** = `anwendungslogik.md` (Datenmodell, Regeln, Operationen, Echtzeit, MCP)
- **T** = `technische-umsetzung.md` (Stack, Struktur, Datenbankschema, Frontend)

Verweise wie „L 5.9“ meinen den Abschnitt in der jeweiligen Datei. Wer eine Aufgabe übernimmt, liest vorher die genannten Abschnitte. Widerspricht sich etwas, gelten L und T vor diesem Plan und vor `CLAUDE.md`. Im Plan selbst steht keine Logik, damit sie nur an einer Stelle gepflegt wird.

## Demo-Story

Beispielprozess ist der Bestellprozess aus L 10. Die Rolle `teamleitung` heißt in der Demo `chef`.

| Person | Rolle | Agent |
|---|---|---|
| Anna | `einkauf` | Annas Agent legt den Prozess an und führt die Bestellung aus |
| Ben | `mitarbeiter` | Bens Agent stellt den Antrag |
| Chef | `chef` | genehmigt im Browser, optional per Agent im Auftrag |

1. **Prozess aus Excel und Word anlegen.** Anna gibt ihrem Agent die Dateien `Bestelluebersicht.xlsx` (Übersicht der Bestellungen) und `Bestellformular.docx` (Formular mit Feldern und Artikelliste) plus eine Beschreibung: *„Wenn jemand das Bestellformular einreicht, muss der Chef freigeben, danach bestellt der Einkauf.“* Der Agent importiert beide Dateien (L 8.3), schaut, welche Rollen es gibt, und legt in **einem atomaren Batch** an: den Import (Tabelle und Formular-Dokument), was der Import nicht erkennen kann (Aktionen, Buttons, Statusspalte), den Workflow „Bestellprozess“ mit den übrigen Schritt-Dokumenten, das Einstiegsdokument „Einkauf“ mit Startknopf und die Veröffentlichung (L 10.1). Fehler der Prüfung korrigiert der Agent selbst. Alle offenen Browser zeigen die neuen Dokumente sofort.
2. **Antrag stellen.** Ben sagt seinem Agent: *„Bestelle 2× Dell-Monitor für Kostenstelle 4711.“* Der Agent findet den Prozess über die Suche, startet einen Run und schickt das Formular im Schritt „erfassen“ ab (L 10.3). Die Bestellung steht live in der Tabelle, der Run wartet auf Genehmigung.
3. **Genehmigen.** Der Chef bekommt live eine Aufgabe, öffnet sie, übernimmt sie und klickt „Genehmigt“. Ben darf nicht selbst genehmigen (Vier-Augen-Prinzip). Lehnt der Chef ab, ist ein Kommentar Pflicht und der Run endet.
4. **Bestellen.** Anna (Rolle `einkauf`) bekommt live die nächste Aufgabe, trägt Bestellnummer und Liefertermin ein und klickt „Bestellt“. Der Run ist abgeschlossen.
5. **Status verfolgen.** Ben sieht in „Meine Anträge“ und per Agent (`get_run`) jederzeit den Stand mit Verlauf. Annas offene Tabelle zeigt jede Statusänderung sofort. Im Verlauf steht, wer etwas getan hat, auch „Agent im Auftrag von …“ (L 5.8).

**Vorgaben:**
- Anmeldung mit **JWT und Rollen** (`einkauf`, `mitarbeiter`, `chef`), siehe L 5.8 und T 6
- Postgres + pgvector für die Suche
- Frontend in React + React Flow, Backend in Python/FastAPI im Docker-Container
- Echtzeit über WebSockets (L 7), alle Schreibzugriffe über Operationen (L 6)

---

## Features

„Muss“ ist Teil der Demo. „Stretch“ nur, wenn alles läuft.

| # | Feature | Kurzbeschreibung | Muss/Stretch | Logik / Technik |
|---|---|---|---|---|
| F1 | Anmeldung und Rollen | Sign-up mit Rollenwahl, Login, Rollen verwalten. Agenten handeln im Auftrag einer Person oder mit eigener Identität. | Muss (eigene Agenten-Identität: Stretch) | L 5.8, T 6 |
| F2 | Ein Schreibweg | Browser, Agent und Workflow-Engine ändern alles über dieselben Operationen. Batches sind atomar, wiederholbar und mit Versionsprüfung. | Muss | L 1, L 6, T 2.3–2.5 |
| F3 | Tabellen | Typisierte Tabellen mit Spalten und Zeilen, Regeln (Pflicht, eindeutig, Referenzen), Löschschutz. | Muss | L 2, L 9, T 4 |
| F4 | Dokumente | Blockbäume aus Überschrift, Absatz, Liste, Zitat, Code, Trennlinie. Jeder Block einzeln änderbar. Markdown-Ansicht mit Block-IDs für Agenten. | Muss | L 3, L 8.2 |
| F5 | Tabellen im Dokument | `table_view` zeigt eine Tabelle mit Filter und Sortierung, Änderungen in Zellen werden sofort gespeichert. | Muss | L 3.4, L 3.5 |
| F6 | Formulare | Felder, Zeilenlisten (`line_items`), Buttons mit Aktionen, die Zeilen in Tabellen schreiben. Entwürfe live sichtbar. | Muss | L 4 |
| F7 | Ausdrücke | Kleine `{{ }}`-Sprache für Werte, Filter und Aktionen. | Muss | L 4.5 |
| F8 | Workflows | Schritte sind Dokumente mit Zuständigen, Übergänge ergeben sich aus den Buttons. Prüfung vor dem Veröffentlichen, Versionen mit eingefrorenen Dokumenten. | Muss | L 5.1–5.3, L 5.7 |
| F9 | Runs und Aufgaben | Start, Schrittwechsel, Aufgaben für Personen und Rollen, Vier-Augen-Prinzip, Übernehmen/Freigeben, Abbrechen. | Muss (Umverteilen, Fristen: Stretch) | L 5.4, L 5.9 |
| F10 | Status und Benachrichtigungen | Statusansicht, Verlauf, Kommentare, „Meine Aufgaben“, „Meine Anträge“, Benachrichtigungen nach Standardregeln. | Muss | L 5.10 |
| F11 | Workflow-Block und Run-Ansicht | Startknopf mit Run-Liste im Dokument, Graph des Workflows mit Live-Status. | Muss (Editor im Canvas: Stretch) | L 5.5, T 5.6 |
| F12 | Echtzeit | Kanäle, Snapshot, Nachholen nach Reconnect, Präsenz, Schutz vor Überschreiben für Agenten. | Muss | L 7, T 2.7 |
| F13 | Suche | Hybride Suche (Bedeutung + Stichwörter) über Dokumente, Tabellen und Workflows. | Muss | T 3 |
| F14 | MCP für Agenten | Tools zum Finden, Lesen, Ändern, Prozesse starten und Aufgaben erledigen. | Muss | L 8, T 2.8 |
| F15 | Gleichzeitiges Tippen | Mehrere Personen im selben Textblock. | Stretch | L 7.5, T 2.6 |
| F16 | Undo | Eigene Änderungen rückgängig machen. | Stretch | T 6 |
| F17 | Unter-Workflows | Ein Schritt startet einen Kind-Run. | Stretch | L 5.6 |
| F18 | Import von Excel und Word | `.xlsx` wird zu Tabellen, `.docx` zu Dokument mit Formular. Der Import erzeugt nur Operationen, wird mit Warnungen vorgeschlagen und im selben Batch wie Workflow und Aktionen ausgeführt. Im Browser per Upload, für Agenten per MCP. | Muss | L 8.3, T 2.9 |

**Nicht im Scope** (siehe auch L 12): Rechte-Modell im Detail, Eskalation, Vertretung, Quorum, automatische Schritte, Bedingungen in Übergängen, berechnete Spalten, Vorschlagsmodus, Migration laufender Runs, Unterschriften-Block (gab es im alten Plan, ist nicht Teil der Fachdokumente), andere Dateiformate (PDF, CSV, `.doc`, `.xls`).

**Demo-Vereinfachung bei Rechten:** Tabellen-, Dokument- und Workflow-Änderungen (Schema, Veröffentlichen) sind nur für `einkauf` erlaubt, Runs starten darf jeder. Das ersetzt vorerst den offenen Punkt „Rechte allgemein“ (L 12).

---

## Rollen im Team

| Kürzel | Rolle | Schwerpunkt |
|---|---|---|
| **P1** | Backend Core | F1, F2, F3 (Regeln), F4 (Operationen), F12 (Hub) |
| **P2** | Frontend Shell | Anmeldung, Home, Dokument-Ansicht, Sync-Store, Textblöcke, Präsenz |
| **P3** | Tabellen + Formulare + Import | F5, F6, F7, F18: Frontend und Backend |
| **P4** | Workflow | F8, F9, F10, F11: Engine, Aufgaben, Status, Run-Ansicht |
| **P5** | Suche + MCP + Demo | F13, F14, Demo-Dateien und -Daten, Seed, Prompts, Proben |

---

## Phase 0: Fundament (0:00–1:00, **alle zusammen, sequenziell**)

Hier lässt sich nicht parallelisieren. Ohne den gemeinsamen Vertrag arbeiten alle aneinander vorbei.

| ID | Task | Owner | Done wenn |
|---|---|---|---|
| 0.1 ✅ | Demo-Story und Prompts final abnicken (15 min). Welche Rollen und Namen, welche Beispielartikel. | alle | `demo/prompts.md` steht als Entwurf |
| 0.2 ✅ | Repo und `docker compose` mit Datenbank, API, Worker und Web. Hello-World für API und Frontend. | P1 (+P2 für `frontend/`) | `docker compose up` → `localhost:5173` und `localhost:8000/docs` erreichbar |
| 0.3 ✅ | Datenbankschema komplett (T 4) | P1 + P4 | Tabellen existieren nach `docker compose up` |
| 0.4 ✅ | API-Vertrag im Schemas-Paket (T 2.2): Operationen, Blocktypen, Spaltentypen, Workflow-Definition, Run, Aufgabe, Event, Statusansicht und alle WebSocket-Nachrichten (L 6, L 7.3, T 2.3), dazu **Stub-Endpunkte** mit Beispieldaten | P3 + P5 (mit allen abgestimmt) | `/docs` zeigt alle Endpunkte, Frontend kann gegen Stubs bauen |
| 0.5 ✅ | Interne Schnittstellen als Funktions-Stubs: Batch ausführen, Ereignis veröffentlichen, Ausdruck auswerten, Formular absenden, Workflow prüfen/veröffentlichen, Run starten, Zuständige auflösen, Neu-Einbetten anstoßen | P1 + P3 + P4 + P5 | Signaturen mit leerem Rumpf im Backend, `domain/`-Struktur wie in T 2.2 |
| 0.6 ✅ | Platzhalter für den angemeldeten Nutzer (Header wählt Anna, Ben oder Chef), bis F1 fertig ist | P1 | alle können ohne echtes Login testen |
| 0.7 ✅ | `CLAUDE.md` und `AGENTS.md` nach dem Aufbau abgleichen (Struktur, Befehle) | P2 | Befehle stimmen mit dem Repo überein |
| 0.8 ✅ | TypeScript-Typen aus dem API-Schema erzeugen (Befehl siehe `CLAUDE.md`) | P2 | Typen im Frontend nutzbar |
| 0.9 ✅ | Gemeinsamer Ordner `spec/fixtures/` mit Testfällen im Format „Zustand + Operationen → erwarteter Zustand“, den `pytest` und `vitest` beide lesen (T 5.3). Zwei Beispielfälle je für Tabellen, Dokumente, Ausdrücke und Import (kleine Beispieldateien mit erwarteten Ops). | P1 + P2 + P3 | Beide Test-Runner laden dieselben Fälle |
| 0.10 ✅ | Aufbau der Demo-Dateien festlegen, so dass der Import (L 8.3) ohne Handarbeit brauchbar ist: Spalten und Beispielzeilen in `Bestelluebersicht.xlsx`, Feldzeilen („Name: ____“), Artikeltabelle und Kontrollkästchen in `Bestellformular.docx`. Als Notiz in `demo/prompts.md`. | P3 + P5 | Notiz steht, beide verstehen die erwarteten Spalten, Felder und Warnungen |

## Handover Phase 0 → Phase 1

**Status: Phase 0 ist abgeschlossen** (0.1–0.10 ✅, auf `main`, Review ohne offene Abweichungen). Wer eine Phase-1-Aufgabe übernimmt, startet von `main`, legt einen Branch `task/<id>-<kurzname>` an und hält sich an `AGENTS.md`.

**Was existiert (und wo):**

| Bereich | Stand | Ort |
|---|---|---|
| Betrieb | `docker compose up -d --build` startet db (Host-Port **5433**), backend (:8000), worker, frontend (:5173). Frisch: `docker compose down -v && docker compose up -d` | `docker-compose.yml` |
| Schema | alle Tabellen aus T 4, Workspace `ws_demo`. Quelle der Wahrheit ist `init.sql`, keine Migrationen, keine `models.py` | `db/init.sql` |
| API-Vertrag | Pydantic-Schemas für alle 40 Ops (L 6.1), Blöcke, Tabellen, Workflows/Runs/Tasks/Status, WebSocket-Nachrichten und Snapshot-Inhalte. **Verbindlich, Änderungen nur nach Absprache** | `backend/app/schemas/` |
| Stub-Endpunkte | liefern Bestellprozess-Beispieldaten, `/docs` zeigt sie. Jeder Owner ersetzt die Stubs seines Bereichs | `backend/app/api/routers.py`, `stub_data.py`, `ws.py` |
| Interne Schnittstellen | Funktionen mit Signatur, leerem Rumpf und Task-ID im Docstring (Signaturen sind per Test fixiert, nicht ändern ohne Absprache) | `backend/app/{ops,domain,realtime,imports,search,mcp}/` |
| Nutzer-Platzhalter | Header `X-Demo-User: anna\|ben\|chef` (Default Anna), `current_user` und `require_role`. 1.1 ersetzt das, die Signaturen bleiben | `backend/app/auth.py` |
| Frontend | Vite + React + TS, Proxy für `/api`, `/ws`, `/mcp`. **Generierte Typen** und Kurznamen (`OpBatch`, `WsServerMessage`, …) | `frontend/src/api/` |
| Fixtures | 17 gemeinsame Testfälle, Format und Platzhalter in der README. pytest und vitest laden dieselben Dateien | `spec/fixtures/`, `backend/tests/fixture_support.py`, `frontend/src/sync/fixtureSupport.ts` |
| Demo | Rollen, Namen, Beispielartikel, Agent-Prompts, Aufbau von `Bestelluebersicht.xlsx` und `Bestellformular.docx` | `demo/prompts.md` |

**Wichtige Hinweise für alle:**

- **Typen neu erzeugen** nach jeder Änderung an Schemas oder Endpunkten: `cd frontend && npm run gen:types` (Backend läuft) und `types.ts` mit committen.
- **Fixtures sind Pflicht:** `app.ops.memory.apply_ops` (Python) und `sync/apply.ts` (TS) bzw. `evaluate` und die Import-Parser aktivieren die derzeit **übersprungenen** Ausführungstests (17 in pytest) automatisch. Wer sie implementiert, muss sie grün bekommen (Schnittstellen in `spec/fixtures/README.md`). Neue Fälle immer dort ergänzen.
- **3.6 (Branch `task/3.6-xlsx-import`):** `POST /api/imports/xlsx` (Parser `imports/xlsx.py`, Speicher `imports/store.py`, `import.include` expandiert die Pipeline über `store.take_ops`). Kaputte Dateien: 422 mit Klartext, größer als 10 MB: 413. `created.tables[]` enthält zusätzlich `name`, `column_ids` und `rows`. Docx-Endpunkt bleibt Stub bis 3.7.
- **Festlegungen für den Import** (Schlüssel der Zeilenliste = Slug der ersten Kopfzeile, Tabellenname aus Word = letzte Überschrift davor, Word-Tabellen sind `text`) stehen in den Beschreibungen der Import-Fixtures und gelten für 3.6/3.7. Sie sind vom Team noch nicht abgenickt, Abweichungen vorher mit P3/P5 klären.
- **Abweichungen von T:** `mcp` ist auf `<2` gepinnt (`FastMCP`), Embedding-Dimension ist 384, `db/models.py` und `db/migrations/` gibt es noch nicht (entstehen mit 1.2, falls nötig).
- **Noch offen aus Phase 0:** Das Team nickt `demo/prompts.md` ab (Checkliste am Ende der Datei). Das Seed-Skript gibt es noch nicht (Task 5.5).

**Sofort startbar** (alle Abhängigkeiten ✅): 1.1 (P1), 1.2 (P1, **Engpass** für 1.3, 1.4, 3.3, 4.1), 2.1 (P2), 2.3 (P2), 3.2 (P3), 5.1 (P5), 5.3 (P5, gegen Stubs), 5.4 (P5). Alles andere wartet auf die genannten Abhängigkeiten, siehe Spalte „Abhängig von“.

**Exit-Kriterium:** Alle können `git pull && docker compose up` ausführen und gegen die Stubs entwickeln.

---

## Phase 1: Paralleles Bauen (1:00–4:00, **voll parallel**)

### P1: Backend Core
| ID | Task | Done wenn | Abhängig von |
|---|---|---|---|
| 1.1 ✅ | **F1** Anmeldung: Sign-up mit Rollenwahl, Login, Token mit Rollen, Rollen anlegen/ändern/zuweisen, Akteur aus dem Token bestimmen inklusive „im Auftrag von“ (L 5.8). Platzhalter aus 0.6 entfernen. | Login als Anna/Ben/Chef liefert Token mit richtiger Rolle, falsche Rolle bekommt 403 | 0.3 |
| 1.2 ✅ | **F2** Ausführung von Operationen: Batch atomar ausführen, Keys auflösen, Versionsprüfung mit `CONFLICT`, Wiederholung mit gleicher `batch_id` ungefährlich, Rechteprüfung, Op-Log mit inversen Ops, Referenz-Index (L 6.2, L 9, T 2.4, T 2.5) | Ein Batch mit mehreren Ops ist ganz oder gar nicht gespeichert, zweiter Versuch mit gleicher ID liefert das erste Ergebnis | 0.4, 0.5 |
| 1.3 ✅ | **F3** Tabellen: `table.*`, `column.*`, `row.*` mit Typumwandlung, Pflicht/Eindeutig/Min/Max, Referenzen mit `on_delete`, Löschschutz mit Liste der Verwendungen, Spaltentyp ändern (L 2) | Fehlerfälle aus L 2.2 liefern verständliche Meldungen pro Feld, Fixtures laufen grün | 1.2 |
| 1.4 ✅ | **F4** Dokumente: `doc.*`, `block.*` (ohne `text.edit`), Verschachtelungsregeln, lesende Endpunkte für Dokumente, Tabellen und gefilterte Zeilen, Markdown-Ansicht mit Block-IDs und Import (L 3, L 8.2, T 2.2) | `get_document` als Markdown und zurück ergibt dieselben Blöcke | 1.2 |
| 1.5 ✅ | **F12** Echtzeit-Verteilung: Kanäle (`doc`, `table`, `run`, `user`, `workspace`), lückenlose `seq`, Abonnement mit Snapshot oder Nachholen ab `since`, `ack`/`reject`, Rechteprüfung beim Abonnieren, Präsenz mit `editing` und `BLOCK_IN_USE` für Agenten (L 7, T 2.7) | Zwei Clients sehen eine Änderung des jeweils anderen sofort, Reconnect holt Verpasstes nach | 1.1, 1.2 |

### P2: Frontend Shell
| ID | Task | Done wenn | Abhängig von |
|---|---|---|---|
| 2.1 ✅ | Routing (Login, Sign-up, Home, Dokument, Tabelle, Workflow, Run), API-Client mit Token, Name und Rolle im Header | Navigation funktioniert gegen Stubs | 0.8 |
| 2.2 ✅ | Login und Sign-up mit Rollenauswahl | Anmeldung liefert Token und leitet auf Home | 2.1 (später 1.1) |
| 2.3 ✅ | **Sync-Store**: Server-Stand + eigene ausstehende Batches, optimistische Änderungen, `ack`/`reject`, Reconnect mit `since`, Anwenden fremder Ops (L 7.4, T 5.3). Arbeitet gegen Fake-Events, bis 1.5 steht. | Fixtures aus 0.9 laufen auch in `vitest` grün, Reject setzt den Zustand korrekt zurück | 0.4, 0.9 |
| 2.4 ✅ | Dokument-Ansicht: Blöcke der Typen Überschrift, Absatz, Liste, Zitat, Code, Trennlinie; Blöcke einfügen, verschieben, löschen; Kennzeichnung des Autors (Mensch, Agent mit „im Auftrag von“, Workflow) | Dokument lässt sich im Browser aufbauen, Änderungen anderer erscheinen live | 2.3 |
| 2.5 ✅ | Textblöcke bearbeiten, Präsenz-Avatare, „X bearbeitet“ an gesperrten Blöcken, Hinweis bei Konflikt (L 7.5) | Zwei Browser bearbeiten verschiedene Blöcke gleichzeitig | 2.4 (später 1.5) |
| 2.6 ✅ | Home: Listen für Dokumente, Tabellen, Workflows, „Neues Dokument“, Suchfeld, Zähler für Aufgaben und Benachrichtigungen | Neue Dokumente erscheinen ohne Neuladen | 2.1 |

### P3: Tabellen und Formulare
| ID | Task | Done wenn | Abhängig von |
|---|---|---|---|
| 3.1 🚧 | **F5** `table_view` im Dokument und eigener Tabellen-Editor: Spalten und Typen anlegen, Zeilen hinzufügen/löschen, Zellen sofort speichern, Filter und Sortierung, neue Zeilen kurz hervorheben | Edit in einer Zelle erscheint im zweiten Browser, Filter mit Ausdruck funktioniert (🚧 Branch `task/3.1-table-editor`: Editor, `table_view`-Block, Filter, Sortierung und Hervorhebung umgesetzt, Vitest grün; Ausdrücke im Filter zeigen bis 3.2 den 422-Hinweis, Zwei-Browser-Test gegen das echte Backend steht noch aus) | 2.3 (Schnittstelle aus 0.4) |
| 3.2 ✅ | **F7** Ausdrücke: Pfade, Funktionen `sum`, `count`, `concat`, `coalesce`, `lookup`, Typ bleibt erhalten, Fehler bei unbekannten Pfaden (L 4.5, T 2.1) | alle Fälle aus den Fixtures grün | 0.9 |
| 3.3 ✅ | **F6** Formulare im Backend: Sichtbarkeit der Buttons, Entwürfe (`draft.*`), Absenden mit Prüfung, Aktionen in einer Transaktion, Ergebnisse unter `results`, Doppelabsendung wird erkannt (L 4.3, L 4.4, L 4.6) | Absenden schreibt Bestellung und Artikel gemeinsam oder gar nicht | 1.2, 1.3, 3.2 |
| 3.4 🚧 | **F6** Formulare im Frontend: Feld, Zeilenliste, Buttons mit Ladezustand, Pflichtfelder und Fehler am Feld, Entwurf live für alle im selben Kontext, Sichtbarkeit wie in L 4.3 | Formular lässt sich ausfüllen und absenden, Fehler stehen am richtigen Feld (🚧 Branch `task/3.4-forms-frontend`: Blöcke `form`/`field`/`line_items`, Entwurf live über `draft.*`, Sichtbarkeit L 4.3, Fehler aus `details.errors`, Vitest grün; Ende-zu-Ende erst mit Backend 3.3 prüfbar, Ort des User-Entwurfs angenommen: `drafts` im Kanal `user:<id>`) | 2.3 (Schnittstelle aus 0.4) |
| 3.5 ✅ | Formularprüfung (`validate_form`): Warnungen bei Tippfehlern in Ausdrücken, nicht befüllten Pflichtspalten, unbekannten Spalten (L 5.7 Daten) | Prüfung liefert lesbare Meldungen mit Block und Feld | 3.2 |
| 3.6 ✅ | **F18** Excel-Import: Blätter zu Tabellen mit abgeleiteten Spaltentypen und Zeilen, Warnungen (Formel verloren, gemischte Werte, leere Blätter), vorbereiteter Import mit `import_id` und `created`, Operation `import.include` in der Pipeline, Limits und verständliche Fehler bei kaputten Dateien (L 8.3, T 2.9) | Beispieldatei liefert die erwarteten Ops (Fixtures), `import.include` zusammen mit weiteren Ops in einem Batch funktioniert, ein Fehler im Batch hinterlässt keine halbe Tabelle | 0.10, 1.2, 1.3 |
| 3.7 ✅ | **F18** Word-Import: Überschriften, Absätze mit Marks, Listen, Felder aus „Bezeichnung: ____“, Kontrollkästchen, leere Tabellen als Zeilenliste, gefüllte Tabellen als Tabelle mit `table_view`, ein Formular ohne Actions mit Warnung, `title`, `owner`, `bind_table` (L 8.3, T 2.9) | Beispieldatei liefert Dokument mit Formular wie erwartet (Fixtures), mit `bind_table` entsteht ein funktionierender „Speichern“-Button | 0.10, 1.2, 1.4, 3.3 |
| 3.8 🚧 | **F18** Import im Browser: Upload auf Home und in der Tabellen-/Dokumentliste, Vorschau mit Warnungen, „Übernehmen“ führt den Import aus | Hochgeladene Excel-Datei erscheint als Tabelle, Word-Datei als Dokument, Warnungen sind sichtbar | 3.6, 3.7, 2.6 |

### P4: Workflow
| ID | Task | Done wenn | Abhängig von |
|---|---|---|---|
| 4.1 ✅ | **F8** Workflow-Definition und Prüfung: anlegen, ändern, löschen, `validate_workflow` mit allen Fehlern und Warnungen aus L 5.7 in agentenlesbarer Form, Veröffentlichen mit Version und eingefrorenen Schritt-Dokumenten (L 5.3) | Eine fehlerhafte Definition liefert konkrete Meldungen, eine korrekte wird als Version v1 gespeichert (Branch `task/4.1-workflow-definition`. Prüfung in `domain/workflows.py` `check_definition`, Codes in `ValidationIssue.code`; `publish` liefert `{version, warnings}`; `workflow.delete` löscht abgeschlossene Runs mit) | 1.2, 0.5 |
| 4.2 ✅ | **F9** Engine für Runs und Aufgaben: Run starten (mit Startberechtigung), Schritt betreten, Zuständige auflösen, Ausschlüsse (Vier-Augen), `can_act`, Übergang nach Outcome, Ende, Abbrechen, Übernehmen/Freigeben, Events (L 5.4, L 5.9, T 2.2 `domain/tasks.py`, `domain/workflows.py`) | Der komplette Bestellprozess läuft in einem Backend-Test durch (inklusive Ablehnung) (Branch `task/4.2-workflow-engine`. Engine in `domain/workflows.py` & `domain/tasks.py`, Handler `run.start|cancel`, `task.claim|release|reassign` in `ops/handlers/workflows.py`. `complete_task` liefert `{status, current_step, task_id|result}` für 4.3 `forms.submit_form`; `record_run_event` und `load_run_bundle` stehen für 4.4 bereit) | 4.1, 3.2 |
| 4.3 ✅ | Verbindung Formular ↔ Run: Absenden schließt die Aufgabe, speichert das Schritt-Ergebnis und löst den Übergang aus. Ausdrücke im Run-Kontext (`run.steps…`), Formulare in abgeschlossenen Schritten schreibgeschützt (L 4.6, L 5.3) | Absenden im Schritt „erfassen“ erzeugt die Aufgabe für `chef`, Ben darf „genehmigung“ nicht absenden (Branch `task/4.3-form-run`: `forms.py` & `handlers/forms.py` mit Run-Kontext, `can_act`, eingefrorenen Dokumenten, `complete_task`; `queries.py` & `routers.py` mit `?run=`-Auswertung) | 4.2, 3.3 |
| 4.4 ✅ | **F10** Status und Benachrichtigungen: Statusansicht, Run-Liste („Meine Anträge“), Aufgabenliste, Kommentare, Benachrichtigungen nach der Tabelle in L 5.10 (T 4 `notifications`) | `get_run` liefert die Struktur aus L 5.10, Benachrichtigung erreicht alle Mitglieder der Rolle live (Branch `task/4.4-run-status`: `domain/run_status.py`, `run.comment`, `OpContext.emit` Post-Commit-Publish, echte REST-Endpunkte in `api/routers.py`, Live-WS-Tests in `test_run_status.py`) | 4.2, 1.5 |
| 4.5 | Frontend „Meine Aufgaben“ (Öffnen, Übernehmen, Freigeben), „Meine Anträge“, Glocke mit Toast bei neuer Benachrichtigung (T 5.7) | neue Aufgabe erscheint ohne Neuladen in der Liste | 2.3, 4.4 (gegen Stubs) |
| 4.6 | **F11** `workflow`-Block (Startknopf nur für Berechtigte, Run-Liste) und Run-Ansicht: Graph automatisch gelayoutet, erledigt/aktuell/offen farbig, Verlauf, Schritt-Dokument bearbeitbar oder schreibgeschützt (L 5.5, T 5.6) | Knoten ändern ihre Farbe live, Klick auf einen Schritt zeigt dessen Dokument | 2.4, 4.4 |

### P5: Suche, MCP, Demo
| ID | Task | Done wenn | Abhängig von |
|---|---|---|---|
| 5.1 ✅ | **F13** Einbetten: Abschnitte aus Dokumenten, Tabellen-Schemata und Workflows, nur Geänderte neu, entprellt (T 3.1, T 3.2) | Änderung an einem Dokument führt nach kurzer Zeit zu neuen Einträgen (Aufruf von enqueue_reembed aus der Pipeline kommt mit 1.2) | 0.3, 0.5 |
| 5.2 ✅ | **F13** Hybride Suche über Bedeutung und Stichwörter, Treffer pro Quelle mit Verweis auf den Block, Rechte vor der Rückgabe prüfen (T 3.3) | Suche „Formular für Bestellungen“ findet das Dokument auch ohne exakten Treffer | 5.1 |
| 5.3 ✅ | **F14** MCP-Server mit allen Tools aus L 8.1. Dazu die Import-Tools `import_xlsx` und `import_docx` (lesen die lokale Datei und rufen den Import auf). Tool-Beschreibungen enthalten Hinweise für Agenten (erst Dateien importieren, `list_roles`, dann **ein** `apply_ops`-Batch mit `import.include`; Fehler lesen und korrigieren). Fehler der Pipeline als lesbare Tool-Fehler (T 2.8). | Ein Agent kann alle Tools gegen die Stubs aufrufen | 0.4 (Import-Tools echt ab 3.6/3.7) |
| 5.4 ✅ | Demo-Dateien `Bestelluebersicht.xlsx` (2–3 Beispielanträge) und `Bestellformular.docx` erstellen, genau nach dem Aufbau aus 0.10 | Beide Dateien importieren ohne Fehler und mit den erwarteten Warnungen (Dateien, Strukturtest und Import-Prüfung in test_demo_files.py laufen grün) | 0.10 |
| 5.5 ✅ | Seed: Nutzer anna/ben/chef mit Rollen, Demo-Tokens, zwei MCP-Konfigurationen (Anna, Ben) | `seed` auf frischer Datenbank, Tokens funktionieren | 1.1 |
| 5.6 ✅ | Demo-Daten als Fallback, falls der Agent hakt: der komplette Bestellprozess als fertiger Batch (L 10.1, mit Rolle `chef` statt `teamleitung`, Import der Demo-Dateien per `import.include`) und ein Skript, das Import und Batch ausführt | Skript legt Tabellen, Workflow und Dokumente an, `validate_workflow` ist ohne Fehler (Branch `task/5.6-fallback`: Batch `demo/fallback_batch.json` mit Platzhaltern für die Import-IDs, Skript `demo/fallback.py` über REST als Anna oder `--direct`, Test `test_fallback.py`. Nebenbei behoben: `queries._row` parste String-Defaults von Spalten doppelt, `GET /api/tables` lieferte 500) | 5.4, 3.6, 3.7 |

### Handover P1 (Backend Core) → andere Tasks

**Stand (2026-11-25):** 1.1 bis 1.5 sind ✅ auf `main`. Backend-Suite: 254 passed, 12 skipped. Die Details stehen in den Docstrings der genannten Dateien. Hier steht nur, was andere Tasks wissen oder tun müssen.

**Für alle:**

- **Handler:** Neue Ops kommen als Modul in `backend/app/ops/handlers/` mit `@register("<op>")`. Die Schnittstelle (`touch`, `changed`, `set_references`, `add_inverse`, `resolve`, `lock_channel`) steht in `backend/app/ops/context.py`. Versionen erhöht die Pipeline, nicht der Handler.
- **Fehlende Handler (Stand jetzt):** Alle Ops außer `table.*`, `column.*`, `row.*`, `doc.*`, `block.*`, `role.*` und `user/agent.set_roles` liefern `VALIDATION` („nicht verfügbar“). Das gilt für `draft.*`, `form.submit`, `workflow.*`, `run.*`, `task.*` und `import.include`-Inhalte ohne Handler. `text.edit` hat seit F15 einen Handler (`ops/handlers/documents.py`).
- **Rechte in der Pipeline:** Nur strukturelle Ops verlangen `einkauf` (`table.*`, `column.*`, `doc.*`, `block.*`, `workflow.*`, `role.*`, `text.edit`, `user/agent.set_roles`). `row.*`, `draft.*`, `form.submit`, `run.*` und `task.*` sind auf Pipeline-Ebene offen. Die fachliche Prüfung (Startberechtigung, `can_act`, Sichtbarkeit) muss der jeweilige Handler machen.
- **Fixtures:** Die In-Memory-Fassung ist `backend/app/ops/memory.py` (Tabellen) plus `memory_documents.py` (Dokumente). Neue Op-Arten registrieren sich mit `@memory_op("<op>")` in einer eigenen Datei. Nicht registrierte Ops werden in `test_fixtures` übersprungen.
- **Positionen:** Fractional Index in Basis 62, `backend/app/domain/positions.py` (Port von `fractional-indexing`). Das Frontend muss dasselbe Verfahren nutzen.
- **`after`:**
  - Bei `column.add`, `row.insert` und `block.insert` hängt ein fehlendes `after` ans Ende.
  - Bei `column.move` und `row.move` setzt `after=None` an den Anfang.
  - Bei Blöcken setzt `after: "^"` an den Anfang (Festlegung von P1, nicht in L).
- **Fehlerpfade (`details.errors`):**
  - Zellfehler unter dem Spalten-Key.
  - Mehrere Zeilen in einem `row.insert`: `rows[i].key`.
  - Definitionen: `columns[i].feld`, `column.feld`, `patch.feld`.

  Die Beispiele stehen in `spec/fixtures/tables/`.
- **Keys:** Tabellen-Keys dürfen nicht mit `tbl_` beginnen, Spalten-Keys nicht mit `col_`. Sie würden sonst als ID gelesen.
- **Rollen-Ops (`backend/app/ops/handlers/roles.py`):**
  - Rollen-Keys: Kleinbuchstaben, Ziffern und `_`, beginnend mit einem Buchstaben, nicht mit `rol_`.
  - `role.delete` liefert `IN_USE`, solange Mitglieder die Rolle haben (`details.members`) oder der Referenz-Index sie nennt (`details.usages`, z. B. Workflow-Zuständige). Die Workflow-Handler müssen die Kanten `step.assignee`, `workflow.starters` und `workflow.managers` melden.
  - `user/agent.set_roles` liefert die neuen Rollen-IDs in `results` und wirkt ab dem nächsten Batch (L 5.8).

**2.2 Login (P2):** `POST /api/auth/signup` (Name, E-Mail, Passwort mit mindestens 8 Zeichen, Rolle `einkauf`, `mitarbeiter` oder `chef`) und `POST /api/auth/login` liefern ein JWT (8 h). `GET /api/me`, `/api/roles` und `/api/users?role=` lesen aus der DB. `X-Demo-User` gibt es nicht mehr, ohne Token kommt 401.

**2.3 Sync-Store und 2.5 Präsenz (P2):**

- **Anmeldung am WebSocket:** `/ws?token=<JWT>` (oder `Authorization: Bearer`). Ohne gültiges Token schließt der Server mit Code `4401`.
- **Eigene Ops kommen zurück:** Der Absender bekommt seine eigenen Ops (gleiche `batch_id`) zusätzlich zum `ack`, damit `seq` lückenlos bleibt. Der Client dedupliziert nach `batch_id`.
- **Abgelehntes Abo:** Der Vertrag hat dafür keinen eigenen Typ. Der Server schickt `reject` mit `batch_id = "subscribe:<kanal>"` (bzw. `"presence:<kanal>"`) und Code `FORBIDDEN`, `NOT_FOUND` oder `VALIDATION`.
- **Nachholen:** Ist `since` älter als 1000 Ops (`CATCHUP_LIMIT`) oder hat das Log Lücken, kommt ein Snapshot statt der Ops.
- **Präsenz:** `editing` verfällt nach 30 s (`EDITING_TTL`). Das Frontend schickt beim Tippen spätestens alle 25 s erneut `presence` mit `editing`. In `doc:` und `run:` entsteht der Präsenz-Eintrag beim Abonnieren automatisch.

**3.1 Tabellen-Editor (P3):** `GET` für gefilterte Zeilen kennt die Operatoren `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `in` und `is_null` sowie `limit` und `offset` (`backend/app/domain/queries.py`). Ausdrücke `{{ }}` in Filterwerten werden seit 3.2 ausgewertet (Fehler: 422).

**3.2 Ausdrücke (P3, fertig, Branch `task/3.2-expressions`):** `domain/expressions.py` mit `evaluate`, `evaluate_deep`, `find_paths`, `lookup_tables`, `syntax_errors`. Unbekannte Pfade sind Fehler, nur in `coalesce` zählen sie als leer. `lookup` liest `context["tables"]` (Key → Zeilen mit Spalten-Keys). Filterwerte mit `{{ }}` in `domain/queries.py` werden mit `user`, `now`, `today` ausgewertet, Fehler sind 422. Das Gegenstück im Frontend (`sync/expressions.ts`) gehört zu 2.3.

**3.3 Formulare (P3):**

- **Rechte:** `form.submit` und `draft.*` prüfen die Rechte selbst, siehe „Rechte in der Pipeline“.
- **Kanäle:** Zusätzlich betroffene Kanäle (z. B. `user:<id>`) mit `ctx.lock_channel` sperren. Das ist ein später Lock mit Deadlock-Restrisiko, also möglichst wenige Kanäle und immer in sortierter Reihenfolge.
- **Verweise:** Die Block-Handler melden schon die Kanten für `field`, `line_items` und Formular-Actions (`set_references`). Wer Actions erweitert, muss die Kanten mitpflegen.
- **Umsetzung (fertig, Branch `task/3.3-forms-backend`):** `domain/forms.py` (Formular lesen, `prepare_values`, `visible_buttons`, `submit_form`), Handler in `ops/handlers/forms.py` (`draft.*`, `form.submit`). Die Actions laufen über die Handler `row.insert`/`row.update`/`row.delete` im selben Batch, ein Fehler rollt alles zurück (Fehler `VALIDATION` mit `details.errors`, Pfade `<feld>`, `<liste>[i].<spalte>`, `actions.<key>…`). Ergebnis von `form.submit` im `BatchResult`: `{results}`, bei erkannter Doppelabsendung `{results, duplicate: true}`. `values` ersetzt den Entwurf komplett. Entwürfe: `form_drafts`, Kanal `user:<id>` bzw. `run:<id>`.
- **Offen für 4.3:** Der Run-Kontext ist noch nicht verdrahtet: `form.submit` mit `run` liefert `VALIDATION`, `visible_buttons(..., run=…)` und Schritt-Dokumente (`owner_workflow`) außerhalb eines Runs liefern keine Buttons (`FORBIDDEN` beim Absenden). Run-Entwürfe (`scope.run`) prüfen nur, dass der Run existiert (`can_act` fehlt). `run.*`-Pfade im Ausdruckskontext und `complete_task` müssen in `submit_form` ergänzt werden (`buttons_allowed` und `base_ctx["run"]`).

**3.5 Formularprüfung (P3, fertig, Branch `task/3.5-validate-form`):** `POST /api/documents/{doc}/blocks/{block}/validate` (und MCP `validate_form`) liefert `{ok, warnings: [{block, field, message}]}` (`ok` = keine Warnungen) aus `domain/forms.validate_form_in_db`. Rein aus Blöcken (ohne DB): `validate_form(blocks, form_block)`. Mit Tabellenschema: `check_form(blocks, form_block, tables)`. Geprüft werden Syntax und Pfade von Ausdrücken (Tippfehler mit „Meinten Sie“), unbekannte Felder, Actions, Buttons und `require`, Reihenfolge von `results.*`, nicht verwendete Actions sowie unbekannte Tabellen und Spalten und nicht befüllte Pflichtspalten der Actions. Das automatische Mitliefern der Warnungen bei `block.insert/update` ist nicht umgesetzt.

**3.6/3.7 Import (P3):**

- **Ergebnis:** `import.include` liefert im `BatchResult` nur `{"included": n}`, nicht die Ergebnisse der einzelnen importierten Ops.
- **Import-Regeln:** Ein Import gehört dem Ersteller (sonst `FORBIDDEN`), gilt 1 h und ist einmalig (`IMPORT_USED`). `used_at` wird erst beim Commit gesetzt.
- **Erzeugte Keys:** Sie müssen die Key-Regel oben einhalten.
- **Markdown für Word:** Ein Markdown-Import ist schon möglich, über `doc.create` mit Feld `markdown` (L 8.2). Im Markdown stehen Tabellen- und Spalten-Keys statt IDs. Fehler kommen als `VALIDATION` mit Zeilennummer.

**4.1 bis 4.4 Workflow (P4):**

- **Prüfungen im Handler:** `run.*` und `task.*` prüfen Startberechtigung und `can_act` im Handler.
- **Löschen und Verweise:** `doc.delete` liefert `IN_USE`, wenn ein Workflow das Dokument nutzt. Die Workflow-Handler müssen dafür ihre Kanten melden (`set_references`).
- **Offen, noch keinem Task zugeordnet (L 9):** `role.delete` und `column.delete` sind nur durch den Entwurf geschützt, nicht durch ältere Workflow-Versionen mit aktiven Runs (gefunden im Review von 4.1).
- **Run-Kontext:** `GET /api/documents/{doc}?run=` ignoriert `run` noch (gehört zu 4.3).
- **Sichtbarkeit:** Wer `run:<id>` abonnieren darf, steht in `backend/app/realtime/access.py`: Antragsteller, Beteiligte an Aufgaben (Person oder Rolle) und `einkauf`. Dass `einkauf` alle Runs sieht, ist eine Festlegung von P1.
- **Rollenänderung bei offener Verbindung:** Abos werden nicht beendet und es kommt kein neuer `user:`-Snapshot (L 7.2/7.3). Das muss mit `user.set_roles` bzw. der Engine kommen.
- **Benachrichtigungen (4.4):** Ereignisse außerhalb der Pipeline über `realtime.hub.publish(channel, event)` verteilen. Mit `seq` geht es per `pg_notify` an alle Instanzen.

**5.2 Suche (P5):** Die Pipeline ruft `enqueue_reembed` nach dem Commit für geänderte Dokumente, Tabellen und Workflows auf. Ausnahme: Läuft `apply_batch` in einer fremden Transaktion, entfällt das.

**5.3 MCP und 5.5 Seed (P5):**

- **MCP-Anmeldung:** Der MCP-Server reicht `Authorization` bzw. `DOCK_TOKEN` weiter, `DOCK_DEMO_USER` gibt es nicht mehr.
- **Agent-Tokens:** Es gibt noch keinen Endpunkt, der sie ausstellt. Vorhanden sind `create_access_token(user_id, roles, actor=Actor(type="agent", id="agt_…", on_behalf_of=user_id))` in `backend/app/auth.py` und ein Eintrag in der Tabelle `agents`. 5.5 sollte darüber die Demo-Tokens für Annas und Bens Agent erzeugen.
- **Seed:** Er kann Nutzer per `POST /api/auth/signup` oder direkt per SQL anlegen. Passwort-Hashes mit `hash_password` aus `auth.py`.
- **JWT-Secret:** Der Dev-Default ist `dev-secret-change-me-please-use-32-bytes-min`.

**Undo (Stretch F16):** Inverse Ops werden für alle Tabellen- und Dokument-Ops ins Op-Log geschrieben. Sie sind gegen die Pipeline nur für Dokumente durchgetestet. Wiederhergestellte Zeilen landen am Ende statt an ihrer alten Position.

**Vom Team abzunicken (Festlegungen von P1, wo L/T offen sind):**

- `einkauf` sieht alle Runs.
- `after: "^"` bei Blöcken.
- Ein einzelner Punkt mit genau drei Nachkommastellen (`"1.234"`) ist ein Tausenderpunkt.
- Referenzspalten haben keinen Standardwert.
- Wird die Anzeigespalte gelöscht, rückt die erste verbleibende Spalte nach.
- Zeilen-Ops erhöhen die Tabellenversion nicht.
- `block.move` über Dokumentgrenzen ist verboten.

---

## Phase 2: Integration (4:00–4:45, **alle zusammen, sequenziell**)

| ID | Task | Owner |
|---|---|---|
| 2.I1 | Alle Stubs durch echte Implementierungen ersetzt, `main` gemergt, frische Umgebung (Befehl siehe `CLAUDE.md`) | P1 leitet |
| 2.I2 | Story **ohne Agent** durchspielen: Demo-Dateien im Browser hochladen (Import) und Fallback-Skript aus 5.6 ausführen → Ben startet den Run im Browser und reicht das Formular ein → Chef-Browser bekommt die Aufgabe live, übernimmt und genehmigt → Annas Browser bekommt die nächste Aufgabe, trägt Bestellnummer ein → Run abgeschlossen, Tabelle zeigt den Status live | alle, P5 protokolliert Bugs |
| 2.I3 | Bugliste priorisieren und verteilen (nur Blocker für die Story) | alle |

---

## Phase 3: Agent-Flows und Feinschliff (4:45–6:30, **parallel**)

| ID | Task | Owner |
|---|---|---|
| 3.F1 | Annas Agent-Flow: beide Dateien importieren, Rollen prüfen → ein `apply_ops`-Batch mit den beiden Importen, Ergänzungen, Workflow, übrigen Dokumenten und Veröffentlichung. Bei Prüffehlern korrigiert der Agent selbst. Prompt so lange proben, bis er stabil ist. | P5 + P4 |
| 3.F2 | Bens Agent-Flow: Suche → `start_run` → `get_task` → `complete_task` für „erfassen“. Dazu Chef-Agent im Auftrag: `list_tasks` → `get_task` → `complete_task` mit „Genehmigt“ (L 10.3). | P5 + P3 |
| 3.F3 | Kennzeichnung in Verlauf, Tabellenzeilen und Blöcken: „von Agent im Auftrag von X“, „von Workflow“ | P1 + P2 |
| 3.F4 | Live-Effekte: Toast bei neuer Aufgabe, Zähler an der Navigation, Graph-Knoten färben sich, neue Zeilen werden hervorgehoben | P2 + P4 |
| 3.F5 | Fehler-Blocker aus 2.I3 | jeweilige Owner |
| 3.F6 | **Stretch**, nur wenn alles läuft, in dieser Reihenfolge: F15 gleichzeitiges Tippen (L 7.5) ✅ (vorgezogen mit 2.5, Branch `task/2-frontend-shell`), Fristen mit `overdue` (L 5.9), Umverteilen, F17 Unter-Workflows (L 5.6), Workflow-Editor im React-Flow-Canvas, Agent mit eigener Identität als Zuständiger, F16 Undo | P1 / P4 / P2 |

---

## Phase 4: Freeze und Proben (6:30–8:00, **sequenziell**)

| ID | Task | Owner |
|---|---|---|
| 4.Z1 | Feature-Freeze, Tag `demo-v1` | P1 |
| 4.Z2 | Komplette Demo dreimal von frischer Datenbank durchspielen | alle |
| 4.Z3 | Backup-Video der kompletten Demo aufnehmen | P5 |
| 4.Z4 | Demo-Rechner vorbereiten: 3 Browserprofile (Anna, Ben, Chef) nebeneinander, damit die Live-Updates sichtbar sind; 2 Terminals mit Claude Code (Anna-MCP, Ben-MCP) | P2 + P5 |

**Freitag, 1 h vor der Demo:** frische Datenbank, Seed, neue Demo-Tokens in die MCP-Konfigurationen, kurzer Durchlauf, Video bereithalten.

---

## Was sequenziell bleiben muss

1. **Phase 0 komplett vor allem anderen.** Schema, Schemas-Paket mit Operationen und Events, Docker, Demo-Dateiformat und die internen Stubs sind Voraussetzung für alles.
2. **1.2 Ausführung von Operationen vor 1.3, 1.4, 3.3, 4.1.** Alles Schreiben läuft darüber.
3. **1.5 Echtzeit vor dem echten Live-Test.** Bis dahin arbeitet P2 mit Fake-Events, alle anderen rufen die Veröffentlichung schon auf.
4. **0.9 Fixtures vor 2.3 und 3.2, 0.10 Dateiaufbau vor 3.6, 3.7 und 5.4.** Frontend und Backend müssen dieselben Fälle prüfen, und Import und Demo-Dateien müssen zusammenpassen.
5. **3.2 Ausdrücke vor 3.3 und 4.2.** Formulare und Workflows brauchen sie.
6. **4.1 Prüfung und Veröffentlichung vor 4.2 Engine**, **4.2 und 3.3 vor 4.3** (Absenden im Run).
7. **4.3 vor 3.F1 und 3.F2.** Die Agent-Flows ergeben nur Sinn, wenn der Prozess läuft.
8. **Phase 2 Integration vor Phase 3.** Erst ohne Agent durchspielen, dann den Agent einbinden.

## Claude Code mit dem Pro-Plan effizient nutzen

- `CLAUDE.md` + Schemas-Paket sind der Kontext. Prompts nennen die Task-ID, die Dateien und die Abschnitte aus L und T, zum Beispiel „Implementiere Task 1.5 laut L 7 und T 2.7, Vertrag im Schemas-Paket“.
- Nach jedem Task `/clear`. Keine Logs, `node_modules` oder `.venv` lesen lassen.
- Für Routine-Tasks das Standardmodell nutzen. Teurere Modelle nur für Operationen-Ausführung (1.2), Echtzeit (1.5), Engine (4.2/4.3), Sync-Store (2.3) und Word-Import (3.7).
- P5 hält Kontingent für Phase 3 und den Freitag zurück, weil P5 die Agent-Demo selbst mit Claude Code fährt.
- Wer am Limit ist, übernimmt manuelle Tests, die Demo-Daten oder Reviews.

## Verifikation (Definition of Done der Demo)

Von frischer Umgebung (Befehl in `CLAUDE.md`):

1. Sign-up mit Rollenwahl funktioniert. Login als `anna`, `ben` und `chef` liefert ein Token mit der richtigen Rolle. Ben versucht, ein Schema zu ändern oder den Workflow zu veröffentlichen, und bekommt **403**.
2. Annas Agent importiert `Bestelluebersicht.xlsx` und `Bestellformular.docx` (Tabelle mit Beispielzeilen, Dokument mit Formular, Warnungen werden gelesen) und legt Tabellen, Workflow, Schritt-Dokumente und das Einstiegsdokument in **einem** Batch an. Eine kaputte oder umbenannte Datei wird mit verständlicher Meldung abgelehnt. Ein absichtlich fehlerhafter Batch inklusive Import wird komplett abgelehnt, es bleibt keine halbe Tabelle zurück, die Meldung nennt die Stelle. Alle Browser zeigen die neuen Dokumente ohne Neuladen.
3. Suche nach „Formular für Bestellungen“ findet das Erfassungs-Dokument, nicht nur bei exaktem Treffer.
4. Zwei Browser öffnen dasselbe Dokument. Ein Edit erscheint im anderen sofort. Ein Agent, der einen gerade bearbeiteten Block ändern will, bekommt `BLOCK_IN_USE`.
5. Bens Agent startet einen Run und reicht das Formular ein. Bestellung und Artikel stehen in den Tabellen (in Annas Browser sofort sichtbar), der Run wartet auf Genehmigung, Ben sieht den Status in „Meine Anträge“.
6. Der Chef bekommt die Aufgabe live, Ben kann **nicht** selbst genehmigen. Ablehnen ohne Kommentar wird verweigert, mit Kommentar endet der Run mit „Abgelehnt“.
7. Zweiter Durchlauf: Chef übernimmt die Aufgabe (andere sehen „In Bearbeitung von …“) und genehmigt. Anna bekommt die Aufgabe für den Einkauf, trägt Bestellnummer und Liefertermin ein, der Run ist „Bestellt“.
8. Der Status in der Tabelle, im Graph, im Verlauf und in `get_run` stimmt in jedem Schritt überein, ohne Neuladen. Der Verlauf nennt auch „Agent im Auftrag von …“.
9. Server neu starten: Clients verbinden sich neu und holen den aktuellen Stand nach (kein Snapshot-Verlust, `seq` ohne Lücke).
