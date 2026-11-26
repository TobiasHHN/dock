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
| B2 | Umlaute (ä, ö, ü) kaputt in Benachrichtigungen, Schrittnamen und Dokumenttiteln („auslÃ¶sen“) | Bug | Demo-Daten | Blocker | 2.I2 (Browser) | P5 | behoben | `task/3.F5-backend-mcp`, `ae8cd5a` |
| B3 | Workflow-Ansicht: Buttons +, − und Vollbild sind weiß auf weiß | Bug | Workflow | Hoch | 2.I2 (Browser) | P4 | behoben | `task/3.F5-workflow-graph`, `4d68124` |
| B4 | Workflow-Graph: Pfeile laufen teilweise durch die Schritt-Kästen | Bug | Workflow | Hoch | 2.I2 (Browser) | P4 | behoben | `task/3.F5-workflow-graph`, `9f31591` |
| B5 | Tabellen-Ansicht (`table_view`) lässt sich im Browser nicht in ein Dokument einfügen | Feature | Frontend, Tabellen | Hoch | 2.I2 (Browser) | P3 | behoben | `task/3.F5-frontend-docs`, `ee732e0` |
| B11 | MCP über HTTP: `import_xlsx`/`import_docx` mit `file_path` liefern `NOT_FOUND`, weil der Pfad im Backend-Container gesucht wird | Bug | MCP/Agent, Import | Hoch (Blocker, falls die Demo über HTTP läuft) | 3.F1-Probe | P5 | behoben | `task/3.F5-backend-mcp`, `2152670` |
| B6 | Dokument-Editor: Blöcke per Drag & Drop verschieben statt über Buttons, Design allgemein verbessern | UX | Frontend | Mittel | 2.I2 (Browser) | P2 | behoben | `task/3.F5-frontend-docs`, `99bb5d6` |
| B7 | Live-Updates beim gemeinsamen Bearbeiten von Dokumenten wirken unruhig, sollen ruhiger und klarer werden | UX | Frontend, Echtzeit | Mittel | 2.I2 (Browser) | P2 | behoben | `task/3.F5-frontend-docs`, `df9c5dc` |
| B8 | Ein Dokument als Arbeitsmappe: Tabellen und Workflows eingebettet, Tabellen als eigene Blätter wie in Excel, Blatt 1 = Dokument | UX | Frontend | Mittel | 2.I2 (Browser) | P2 + P3 + P4 | behoben | `task/3.F5-workbook`, `6302837` |
| B12 | MCP-Tool-Schemas von `apply_ops`, `edit_document`, `create_document` sind sehr groß (je mehrere zehn KB) | UX | MCP/Agent | Mittel | 3.F1-Probe | P5 | behoben | `task/3.F5-backend-mcp`, `2152670` |
| B9 | Löschen-Button bei Dokumenten und Tabellen ist zu präsent | UX | Frontend | Niedrig | 2.I2 (Browser) | P3 | behoben | `task/3.F5-frontend-docs`, `ac6f93d` |
| B10 | „Home“ aus der Topbar entfernen, Klick auf das Logo „dock“ führt schon nach Home | UX | Frontend | Niedrig | 2.I2 (Browser) | P2 | behoben | `task/3.F5-frontend-docs`, `b3a456f` |
| B13 | Sonderzeichen wie ß kaputt („anschlieÃŸend“) | Bug | Demo-Daten | Blocker | 3.F5 (Browser) | P5 | behoben | Code-Fix = B2. Alte Daten in der DB: frische DB + Seed + Fallback nötig |
| B14 | Alle Rollen sollen Dokumente erstellen können | Feature | Backend, Frontend | Hoch | 3.F5 (Browser) | P1 | behoben | `task/3.F5-bugfixes` |
| B15 | Absende-Button „Einreichen“ statt „Eingereicht“ | UX | Workflow, Demo-Daten | Mittel | 3.F5 (Browser) | P4 | behoben | `task/3.F5-bugfixes` |
| B16 | Verlauf eines Runs unter dem Schritt-Dokument statt daneben | UX | Workflow | Mittel | 3.F5 (Browser) | P4 | behoben | `task/3.F5-bugfixes` |
| B17 | Tabellen-Editor mehr wie Excel | UX | Tabellen | Mittel | 3.F5 (Browser) | P3 | behoben | `task/3.F5-bugfixes` |
| B25 | Beim Ausfüllen von Dokumenten zu viele Kästen in Kästen | UX | Frontend, Formulare | Mittel | 3.F5 (Browser) | P2 | behoben | `task/3.F5-bugfixes`, `0a0d19e` |
| B26 | Viele Dokumente erscheinen live und sind nach dem Neuladen weg | Bug | Echtzeit, Backend | Hoch | 3.F5 (Browser) | P1 | behoben | `task/3.F5-test-db` |
| B27 | Home listet Dokumente willkürlich; gewünscht ist ein Baum je Workflow (Übersichtsdokument, darunter aufklappbar die Schritt-Dokumente, wie in Confluence) | Feature | Backend, Frontend, MCP | Mittel | 3.F5 (Browser) | P1 + P2 | behoben | `task/3.F5-home-workflows` |
| B28 | Workflows lassen sich nicht löschen | Feature | Frontend, MCP | Mittel | 3.F5 (Browser) | P2 + P5 | behoben | `task/3.F5-workflow-delete` |

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

### B11: Import per `file_path` scheitert über HTTP

- **Symptom:** Annas Agent ruft `import_xlsx(file_path="…/demo/Bestelluebersicht.xlsx")` auf und bekommt `NOT_FOUND at file_path`, obwohl die Datei auf dem Rechner liegt. Schritt 1 aus `demo/prompts.md` bricht damit beim ersten Aufruf ab. Erst wenn der Agent selbst auf `content_base64` ausweicht, geht es weiter. Das kostet Zeit und wirkt live schlecht.
- **Schritte:** Claude Code mit dem MCP-Server über HTTP (`http://localhost:8000/mcp`) verbinden, `import_xlsx` mit einem lokalen Pfad aufrufen.
- **Ursache (geprüft):** `_read_upload` in `backend/app/mcp/server.py:281` öffnet `file_path` in dem Prozess, in dem der MCP-Server läuft. Über HTTP ist das der Backend-Container, und der hat laut `docker-compose.yml` nur `./backend` unter `/srv` gemountet, nicht `demo/` und nicht den Pfad des Rechners.
- **Umgehung für die Demo:** MCP über stdio anbinden (Variante B), dann läuft der Server auf dem Rechner und findet die Datei.
- **Dauerhafte Lösung (eine davon):**
  - `demo/` in den Backend-Container mounten, und zwar unter demselben Pfad, den der Agent kennt. Unter Windows schwierig, weil Host-Pfade wie `C:\…` im Container nicht existieren.
  - Besser: Bei HTTP liest ein kleiner lokaler MCP-Proxy bzw. der Client den Pfad und schickt `content_base64`. Alternativ die Tool-Beschreibung so ändern, dass Agenten über HTTP direkt `content_base64` nutzen, und `file_path` nur bei stdio anbieten.
- **Priorität:** `Hoch`, weil es mit stdio eine Umgehung gibt. **Blocker**, falls das Team für die Demo HTTP festlegt. Entscheidung in 2.I3 treffen und in `demo/prompts.md` festhalten.

### B12: Sehr große Tool-Schemas

- **Symptom:** `apply_ops`, `edit_document` und `create_document` bringen jeweils den kompletten Block- und Op-Baum (alle Blocktypen, alle 40 Ops, verschachtelte `children`) als JSON-Schema mit, je mehrere zehn KB.
- **Folgen:** Jedes Laden der Tools kostet viel Kontext. Agenten werden langsamer und teurer und haben weniger Platz für die eigentliche Aufgabe. Mit dem Pro-Plan und mehreren Proben vor Freitag spürbar (siehe Abschnitt „Claude Code mit dem Pro-Plan effizient nutzen“ im Plan).
- **Ort:** Tool-Definitionen in `backend/app/mcp/server.py`, Schemas aus `backend/app/schemas/`.
- **Lösungsideen:**
  - Gemeinsame Definitionen nur einmal ausliefern (`$defs` statt Wiederholung je Tool).
  - Ops und Blöcke im Tool-Schema nur als `object` beschreiben und auf eine Doku-Ressource verweisen (z. B. MCP-Resource mit L 6.1 und den Blocktypen). Die Validierung bleibt serverseitig, Fehler kommen wie bisher als lesbare Tool-Fehler zurück.
  - Das volle Schema nur an `apply_ops` hängen, `edit_document` und `create_document` schlank halten (Markdown statt Blockbaum, L 8.2).
- **Achtung:** Der API-Vertrag in `backend/app/schemas/` bleibt unverändert, es geht nur um die Darstellung im MCP-Tool. Nach dem Umbau Annas Agent-Flow (3.F1) erneut proben, damit die Agenten den Batch weiterhin fehlerfrei bauen.

### Stand nach 3.F5 (Sammel-Branch `task/3.F5-bugfixes`)

Alle Fixes per Unit-Tests geprüft (Backend 396 grün, Frontend 392 grün), **noch nicht im Browser**. Offen bzw. nachzuprüfen:

- **B5:** „Neue Tabelle“ im Einbetten-Dialog legt die Tabelle sofort an. Bricht man danach ab, bleibt eine ungenutzte Tabelle übrig. Ob das Backend die neuen `table_view`- und `workflow`-Props annimmt, ist im Browser zu prüfen.
- **B8:** Getroffene Entscheidungen: Workflows bekommen ein eigenes Blatt mit Graph. Eine Tabelle hat keinen Besitzer und erscheint in jedem Dokument, das sie einbettet. Nicht eingebettete Tabellen (z. B. nach dem Import) sind über `/tables/:id` erreichbar (der Button „In Dokument einbetten …“ dort wurde mit B28 wieder entfernt; einbetten geht über „Block hinzufügen“ im Dokument). Der Hinweis „Eingebettet in: …“ fehlt, weil es keine API für die Rückwärtssuche gibt.
- **B10:** In der mobilen Tab-Leiste bleibt „Home“, weil das Logo dort nicht sichtbar ist.
- **B11:** Zusätzlich sucht `_read_upload` eine nicht gefundene Datei per Dateiname in `demo/`. Der Backend-Container muss neu gestartet werden, damit der Mount `./demo:/srv/demo:ro` greift.
- **B12:** Agenten holen Op- und Blockfelder jetzt über das neue Tool `describe_schema`. **Annas Agent-Flow (3.F1) neu proben.**

### B13–B17 (Rückmeldung nach 3.F5)

- **B13 ß/Umlaute:** In der Datenbank stehen noch Texte, die vor dem B2-Fix falsch eingelesen wurden (z. B. `anschlieÃŸend`, `auslÃ¶sen`). Der Code ist korrekt, die Daten müssen neu angelegt werden: `docker compose down -v && docker compose up -d`, dann `python demo/seed.py` und `python demo/fallback.py`.
- **B14 Dokumente für alle Rollen:** Freie Dokumente (ohne `owner_workflow`) dürfen alle Rollen anlegen und bearbeiten (`doc.*`, `block.*`, `text.edit`). Schritt-Dokumente, neue Tabellen, Import und Workflows bleiben bei `einkauf`. Prüfung in `_check_permission` (`backend/app/ops/pipeline.py`), im Frontend `canEditDocument`.
- **B15 „Einreichen“:** Label des Buttons `submit` in `demo/fallback_batch.json`, `demo/prompts.md` und Beispiel in `anwendungslogik.md`. Im Verlauf steht jetzt „Einreichen“, die Entscheidungen bleiben als Ergebnis formuliert. Wirkt erst nach neuem Fallback (siehe B13).
- **B16 Verlauf unten:** `.run-layout` einspaltig.
- **B17 Excel-Optik:** Zeilennummern, Spaltenbuchstaben, Gitterlinien, fixierte Kopfzeile und Zeilennummern, aktive Zelle mit Rahmen. Pfeiltasten und Enter wechseln die Zelle, mehrere Zellen aus Excel/Sheets lassen sich einfügen (überzählige Zeilen werden angehängt). Logik in `tables/tableModel.ts` (`pasteOps`, `gridMove`, `parseClipboard`, `columnLetter`), getestet.

### B18–B24 (UI-Feinschliff nach 3.F5, Branch `task/3.F5-ui-feinschliff`)

- **B18 Anmelden-Button:** Schrift saß oben, weil die Dokument-Klasse `.block` (`display:flex; align-items:flex-start`) auch `button.block` traf. Klasse heißt jetzt `full`.
- **B19 Schritt mehrfach angezeigt:** Aufgabenleiste „Aktueller Schritt“, Kopf über dem Schritt-Dokument, eingebetteter Dokumenttitel und Schritt-Buttons unter dem Graph entfernt. Zuständig, Frist, „Übernehmen“/„Freigeben“ und „Ablauf abbrechen“ stehen im Seitenkopf. Im Schritt-Block steht nur noch das Dokument.
- **B20 Verlauf:** schlanke Zeitleiste (Punkt + Linie, keine Kästen), Kommentar als unauffällige Zeile mit rundem Senden-Knopf, der erst bei Text erscheint.
- **B21 Benachrichtigungen:** neuer Endpunkt `DELETE /api/notifications/{id}` (nur eigene, 204/403/404), Entfernen-Knopf je Eintrag, „Alle gelesen“ heißt „Als gelesen markieren“.
- **B22 Button-Labels:** Buttons als Aufforderung („Genehmigen“, „Ablehnen“, „Bestellung abschließen“) in `demo/fallback_batch.json`, Doku und Plan. Status und Verlauf zeigen über `resultLabel` das Ergebnis („Genehmigt“, „Abgelehnt“, „Bestellt“). Bestehende Workflows behalten ihre Labels bis zum Neu-Anlegen bzw. Neu-Veröffentlichen.
- **B23 Blatt-Leiste:** schwebende, runde Leiste fest am unteren Bildschirmrand (auch bei kurzen Dokumenten), aktives Blatt dunkel hervorgehoben.
- **B24 Tabellen:** Spaltenbuchstaben (A, B, C …) entfernt, nur noch der Spaltenname.

Unit-Tests grün (Backend 397, Frontend 398), Typecheck sauber. **Noch nicht im Browser geprüft.**

### B26: Geister-Dokumente

- **Symptom:** In der Dokumentliste erscheinen plötzlich viele Dokumente (z. B. „ZZ37 Formular“), nach dem Neuladen sind sie weg.
- **Ursache (geprüft):** Die Backend-Tests liefen gegen die Demo-Datenbank `dock`. Sie legen über die echte Pipeline Dokumente an (Op-Log + `pg_notify`), offene Browser bekommen diese live über den Kanal `workspace`. Danach löschen die Tests ihre Daten, der Snapshot beim Neuladen enthält sie nicht mehr.
- **Fix:** `backend/tests/conftest.py` setzt `TEST_DATABASE_URL`/`DATABASE_URL` auf eine eigene Datenbank `dock_test`, legt sie bei Bedarf aus `db/init.sql` an und erzeugt sie neu, wenn sich `init.sql` ändert. Bricht ab, falls jemand die Tests auf `dock` richtet.
- **Rest:** Im Op-Log der Demo-DB stehen noch alte Test-Einträge. Ein Browser, der mit alter `seq` neu verbindet, kann sie einmal nachgeholt bekommen. Sauber wird es mit frischer DB (`docker compose down -v`, Seed).

### B27: Home als Baum je Workflow

- **Wunsch:** Jeder neue Workflow (auch über MCP) bekommt als Erstes ein Dokument, das nur eine Beschreibung und den Workflow enthält. Darunter hängen die Dokumente des Workflows. Auf Home lässt sich das je Workflow aufklappen.
- **Fix:** Die Pipeline ergänzt nach `workflow.create` ein `doc.create` für das Übersichtsdokument `doc_ov_<…>` (Titel = Name, `owner = { workflow, step: null }`, Absatz aus dem neuen optionalen Feld `description` + `workflow`-Block). Legt der Batch selbst ein Dokument mit `step: null` an, entfällt das (so in `demo/fallback_batch.json`: `doc_einkauf`). Vor `workflow.delete` löscht die Pipeline das Übersichtsdokument mit. Der Workspace-Snapshot liefert jetzt `owner` je Dokument und `documents` (Schritt-Dokumente) je Workflow. Home gruppiert in `frontend/src/home/homeModel.ts`, Aufklappzustand pro Browser in `localStorage`, Standard zugeklappt.
- **Rest:** Bestehende Workflows in der Demo-DB haben noch kein Übersichtsdokument. Home zeigt sie trotzdem als Gruppe (Klick führt dann auf die Workflow-Seite). Sauber wird es mit frischer DB + Seed + Fallback.

### B28: Workflows löschen

- **Fix:** Button „Workflow löschen“ auf der Workflow-Seite und im Übersichtsdokument (statt „Dokument löschen“). Ein Batch: `workflow.delete`, danach `doc.delete` für alle Schritt-Dokumente mit `owner.workflow`; das Übersichtsdokument ergänzt die Pipeline (B27). Bestätigungsdialog nennt die betroffenen Dokumente. Neues MCP-Tool `delete_workflow(workflow, delete_documents=true)`.
- **Grenzen:** Mit aktiven Runs oder `workflow`-Blöcken in anderen Dokumenten lehnt der Server ab (IN_USE, Meldung im Toast). Abgeschlossene Runs gehen mit. Nur für `einkauf`.

<!-- Vorlage für neue Details:

### B<n>: <Titel>

- **Symptom:**
- **Schritte:**
- **Erwartet:**
- **Ursache (falls bekannt):**
- **Fix:**
-->
