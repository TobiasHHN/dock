# Bugliste (Phase 2 Integration, 2.I2/2.I3)

Hier landen alle Fehler aus der Integration und den Proben. P5 protokolliert, in 2.I3 priorisiert und verteilt das Team.

## So wird ein Bug eingetragen

1. Nächste freie ID nehmen (`B2`, `B3`, …) und **eine Zeile** in der Tabelle ergänzen.
2. Unter „Details“ einen Abschnitt mit derselben ID anlegen, falls die Zeile nicht reicht (Schritte, Fehlermeldung, Vermutung).
3. Wer einen Bug behebt: Status auf `behoben` setzen, Branch/Commit in die Spalte „Fix“ schreiben. Commit-Message mit der Task-ID **und** der Bug-ID, z. B. `3.F5: B4 Toast fehlt bei neuer Aufgabe`.
4. Nicht reproduzierbar oder kein Fehler: Status `verworfen` mit kurzem Grund.

**Priorität**

- `Blocker`: bricht die Demo-Story (Schritte 1–5 in `hackathon-plan.md`) oder die Definition of Done. Wird in 3.F5 behoben.
- `Hoch`: sichtbar in der Demo, aber umgehbar.
- `Mittel`: macht die Demo deutlich besser, ist aber nicht kaputt. Nach den Blockern und `Hoch`.
- `Niedrig`: Schönheitsfehler, nur wenn Zeit bleibt.

**Art:** `Bug` (etwas ist kaputt) · `UX` (funktioniert, soll anders aussehen/bedient werden) · `Feature` (fehlt noch)

**Status:** `offen` · `in Arbeit` · `behoben` · `verworfen`

**Bereich:** Backend, Frontend, Echtzeit, Workflow, Formulare, Tabellen, Import, Suche, MCP/Agent, Demo-Daten

## Übersicht

Sortiert nach Priorität.

| ID | Titel | Art | Bereich | Priorität | Gefunden in | Owner | Status | Fix |
|---|---|---|---|---|---|---|---|---|
| B1 | Snapshot von `user:` und `run:` scheitert, sobald Benachrichtigungen oder Run-Events existieren | Bug | Echtzeit | Blocker | 2.I2 (E2E-Skript) | P1 | behoben | `task/2.I-integration`, `f1b4077` |
| B2 | Umlaute (ä, ö, ü) kaputt in Benachrichtigungen, Schrittnamen und Dokumenttiteln („auslÃ¶sen“) | Bug | Demo-Daten | Blocker | 2.I2 (Browser) | P5 | offen | |
| B3 | Workflow-Ansicht: Buttons +, − und Vollbild sind weiß auf weiß | Bug | Workflow | Hoch | 2.I2 (Browser) | P4 | offen | |
| B4 | Workflow-Graph: Pfeile laufen teilweise durch die Schritt-Kästen | Bug | Workflow | Hoch | 2.I2 (Browser) | P4 | offen | |
| B5 | Tabellen-Ansicht (`table_view`) lässt sich im Browser nicht in ein Dokument einfügen | Feature | Frontend, Tabellen | Hoch | 2.I2 (Browser) | P3 | offen | |
| B6 | Dokument-Editor: Blöcke per Drag & Drop verschieben statt über Buttons, Design allgemein verbessern | UX | Frontend | Mittel | 2.I2 (Browser) | P2 | offen | |
| B7 | Live-Updates beim gemeinsamen Bearbeiten von Dokumenten wirken unruhig, sollen ruhiger und klarer werden | UX | Frontend, Echtzeit | Mittel | 2.I2 (Browser) | P2 | offen | |
| B8 | Ein Dokument als Arbeitsmappe: Tabellen und Workflows eingebettet, Tabellen als eigene Blätter wie in Excel, Blatt 1 = Dokument | UX | Frontend | Mittel | 2.I2 (Browser) | P2 + P3 + P4 | offen | |
| B9 | Löschen-Button bei Dokumenten und Tabellen ist zu präsent | UX | Frontend | Niedrig | 2.I2 (Browser) | P3 | offen | |
| B10 | „Home“ aus der Topbar entfernen, Klick auf das Logo „dock“ führt schon nach Home | UX | Frontend | Niedrig | 2.I2 (Browser) | P2 | offen | |

## Details

### B1: Snapshot von `user:` und `run:` scheitert

- **Symptom:** Das Abonnieren von `user:<id>` bzw. `run:<id>` liefert keinen Snapshot, im Backend-Log `JSONDecodeError` in `realtime/snapshots.py`. Folge im Browser: „Meine Aufgaben“, Glocke und Run-Ansicht ohne Live-Daten.
- **Schritte:** frische DB, Seed, Fallback, Run starten und absenden, danach `user:usr_ben` oder `run:<id>` abonnieren.
- **Ursache:** `_JSON_COLUMNS` enthielt `type`. In `run_events`, `notifications` und `blocks` ist `type` Text, kein JSON.
- **Fix:** `type` aus `_JSON_COLUMNS` entfernt, Regressionstest `test_snapshot_row_keeps_text_type_columns` in `backend/tests/test_realtime.py`.

### B2: Umlaute kaputt

- **Symptom:** In Benachrichtigungen und an anderen Stellen stehen statt ä, ö, ü Zeichen wie `Ã¶`, z. B. „Bestellung auslÃ¶sen“ als Schritt- und Dokumentname.
- **Schritte:** frische DB, `python demo/seed.py`, `python demo/fallback.py` unter Windows, danach Run starten und Benachrichtigung bzw. Workflow-Graph ansehen.
- **Erwartet:** „Bestellung auslösen“ überall korrekt.
- **Ursache (geprüft):** `demo/fallback.py:93` liest `fallback_batch.json` mit `TEMPLATE.read_text()` ohne `encoding="utf-8"`. Unter Windows wird das als cp1252 gelesen, die falschen Zeichen landen so **in der Datenbank** (`documents.title`, Schrittnamen im Workflow, daraus die Benachrichtigungen). Die Anzeige im Frontend ist nicht schuld.
- **Fix-Vorschlag:** `read_text(encoding="utf-8")`, alle `open()`/`read_text()` in `demo/` und `backend/` auf fehlendes Encoding prüfen, danach frische DB + Seed + Fallback. Test, der den Titel „Bestellung auslösen“ nach dem Fallback prüft. Da die Demo unter Windows läuft: **Blocker**.

### B3: Graph-Steuerung weiß auf weiß

- **Symptom:** In der Workflow-Ansicht sind die Schaltflächen unten links (Vergrößern +, Verkleinern −, Vollbild/Einpassen) nicht zu sehen: weiße Symbole auf weißem Grund.
- **Ort:** `<Controls>` von React Flow in `frontend/src/workflows/WorkflowGraph.tsx:162`. Vermutlich überschreiben die App-Farbvariablen (Dark-/Light-Theme) die Standardfarben von React Flow.
- **Erwartet:** Symbole in Textfarbe auf Flächenfarbe, in hellem und dunklem Theme lesbar.
- **Fix-Vorschlag:** Farben der Klassen `.react-flow__controls-button` (Hintergrund, `fill`/`color` des SVG, Rahmen) an die Theme-Variablen binden. Kleiner Aufwand.

### B4: Pfeile laufen durch die Schritt-Kästen

- **Symptom:** Im Workflow-Graph gehen manche Pfeile quer durch die Kästen anderer Schritte, in denen steht, was zu tun ist. Besonders bei Rücksprüngen und bei Übergängen, die einen Schritt überspringen (z. B. „Abgelehnt → Ende“).
- **Ort:** Layout `frontend/src/workflows/layout.ts`, Kanten in `WorkflowGraph.tsx`.
- **Erwartet:** Pfeile laufen um die Kästen herum oder zwischen ihnen, Beschriftungen der Pfeile überdecken keinen Text.
- **Fix-Vorschlag:** Kantentyp `smoothstep` bzw. `step` statt gerader Linien, Abstand zwischen den Ebenen im Layout vergrößern, Kanten, die Ebenen überspringen, seitlich führen (eigene Handles links/rechts). Im Graph der Demo sichtbar, deshalb **Hoch**.

### B5: Tabellen lassen sich im Browser nicht in Dokumente einbetten

- **Symptom:** Im Dokument-Editor bietet „Block hinzufügen“ nur Textblöcke an (Absatz, Überschriften, Liste, Zitat, Code, Trennlinie). Eine Tabellen-Ansicht (`table_view`) kann man nur per Agent oder Fallback-Skript anlegen.
- **Ort:** `BLOCK_TEMPLATES` in `frontend/src/documents/blockOps.ts`. Der Block selbst existiert schon (3.1).
- **Erwartet:** Im Menü „Tabelle einbetten“: bestehende Tabelle auswählen (oder neue anlegen), danach Spalten, Filter und Sortierung einstellen.
- **Bezug:** F5 „Tabellen im Dokument“ ist ein Muss-Feature (L 3.4, L 3.5). Ohne Agent ist es heute nicht erreichbar, deshalb **Hoch**. Gleiches gilt sinngemäß für `workflow`- und Formular-Blöcke, falls sie im Browser hinzufügbar sein sollen (siehe B8).

### B6: Dokument-Editor mit Drag & Drop und besserem Design

- **Wunsch:** Blöcke per Drag & Drop verschieben (Griff links am Block, Einfügemarke beim Ziehen), statt über Hoch/Runter-Buttons. Die Buttons können entfallen oder in ein Menü am Griff wandern.
- **Design allgemein:** weniger sichtbare Bedienelemente im Ruhezustand (erst beim Hover am Block), mehr Weißraum, Lesebreite begrenzen, einheitliche Abstände zwischen Blöcken. Ziel ist ein ruhiger Editor in der Art von Notion.
- **Technik:** Verschieben bleibt `block.move` mit Fractional Index (`domain/positions.py` bzw. Frontend-Port). Keine neue Dependency ohne Absprache (die HTML5-Drag-&-Drop-API reicht).
- **Priorität Mittel:** In der Demo legt der Agent die Dokumente an, gezeigt wird das Bearbeiten nur kurz.

### B7: Live-Updates beim Bearbeiten ruhiger gestalten

- **Symptom:** Wenn andere im selben Dokument arbeiten, wirken die Updates unruhig: Inhalte springen, Markierungen und Hinweise erscheinen abrupt.
- **Erwartet:** Fremde Änderungen blenden sanft ein (kurze Hervorhebung, die ausblendet), Präsenz als dezente Avatare bzw. farbiger Rand am bearbeiteten Block, „X bearbeitet“ nur am betroffenen Block. Kein Springen der Scrollposition.
- **Ort:** `frontend/src/documents/DocumentView.tsx`, `TextBlock.tsx`, Präsenz aus 2.5.
- **Priorität Mittel:** Zwei Browser im selben Dokument sind Teil der Definition of Done (Punkt 4). Es funktioniert schon, soll aber besser aussehen.

### B8: Ein Dokument als Arbeitsmappe

- **Wunsch:** Die Trennung in Dokumente, Tabellen und Workflows ist als Datenstruktur richtig, soll aber **nicht** so angezeigt werden. Stattdessen:
  - Es gibt nur Dokumente. Tabellen und Workflows sind darin eingebettet und lassen sich über „Block hinzufügen“ anlegen oder einfügen (siehe B5).
  - Unten im Dokument gibt es Blätter wie in Excel bzw. Google Sheets. **Blatt 1 ist immer das Dokument selbst**, jede eingebettete Tabelle hat ein eigenes Blatt mit der vollen Tabellenansicht (Editor aus 3.1).
  - Home zeigt nur noch Dokumente (keine getrennten Listen für Tabellen und Workflows).
- **Offene Fragen:** Wo erscheinen Workflows (eigenes Blatt mit Graph oder nur als Block)? Was passiert mit Tabellen, die in mehreren Dokumenten stecken oder in keinem (z. B. nach dem Excel-Import)? Welches Dokument „besitzt“ eine Tabelle?
- **Bezug:** ändert Routing und Navigation aus 2.1 und Home aus 2.6, nicht das Datenmodell aus L. Vor dem Umbau kurz im Team abstimmen und prüfen, ob T 5 (Frontend) angepasst werden muss.
- **Priorität Mittel, großer Aufwand:** Erst nach den Blockern und `Hoch`. Wenn die Zeit vor Freitag nicht reicht, nur Blatt-Leiste für eingebettete Tabellen umsetzen und die getrennten Listen auf Home ausblenden.

### B9: Löschen-Button zu präsent

- **Symptom:** In Dokument- und Tabellenansicht fällt der Löschen-Button sofort ins Auge (groß, rot, in der Hauptleiste).
- **Erwartet:** Löschen in ein Menü „…“ verschieben oder als unauffälliger Text-/Icon-Button, rot erst beim Hover. Der Bestätigungsdialog (`ui/confirm`) bleibt.
- **Ort:** Tabellen-Editor (`frontend/src/tables/TableEditor.tsx`) und Dokument-Ansicht (`DocumentView.tsx`).

### B10: „Home“ aus der Topbar entfernen

- **Symptom:** Die Topbar hat einen Link „Home“, obwohl ein Klick auf das Logo „dock“ ebenfalls zur Startseite führt.
- **Erwartet:** Link „Home“ entfällt, das Logo bleibt der Weg zur Startseite (mit Hover-Zustand, damit klar ist, dass es klickbar ist).
- **Ort:** `frontend/src/layout/AppShell.tsx:93` (und `:126`, falls das die mobile Navigation ist).

<!-- Vorlage für neue Details:

### B<n>: <Titel>

- **Symptom:**
- **Schritte:**
- **Erwartet:**
- **Ursache (falls bekannt):**
- **Fix:**
-->
