# Demo: Bestellfreigabe im Einkauf (Entwurf)

Status: **Entwurf** (Task 0.1/0.10). Das Team nickt die Prompts und Namen vor Phase 1 ab, Änderungen direkt hier einarbeiten.

## 1. Personen, Rollen, Namen

| Login (E-Mail) | Name | Rolle | Passwort | Agent |
|---|---|---|---|---|
| `anna@demo.local` | Anna Beispiel | `einkauf` | `demo` | Annas Assistent (MCP-Konfiguration Anna) |
| `ben@demo.local` | Ben Mitarbeiter | `mitarbeiter` | `demo` | Bens Assistent (MCP-Konfiguration Ben) |
| `chef@demo.local` | Chef Teamleiter | `chef` | `demo` | optional: Agent im Auftrag des Chefs |

Die Rolle `teamleitung` aus anwendungslogik.md 10 heißt in der Demo `chef`. Workspace: `ws_demo`.
Beispielartikel: **Dell-Monitor** (DELL-U2723, 249,00 €), **Logitech-Maus** (LOG-M185, 19,00 €), **Tastatur** (KEY-K120, 39,90 €). Kostenstelle der Demo: **4711**.

## 2. Ablauf und Prompts

### Schritt 1: Prozess anlegen (Anna, Agent)

> Hier sind unsere Bestellübersicht (`demo/Bestelluebersicht.xlsx`) und das Bestellformular (`demo/Bestellformular.docx`).
> Lege daraus einen Bestellprozess an: Wenn jemand das Bestellformular einreicht, muss der Chef die Bestellung
> genehmigen oder mit Begründung ablehnen (nicht der Antragsteller selbst). Danach bestellt der Einkauf beim Lieferanten
> und trägt Bestellnummer und Liefertermin ein. Der Status jeder Bestellung soll in der Übersicht stehen.
> Lege außerdem ein Einstiegsdokument „Einkauf“ an, von dem aus man eine Bestellung starten kann.

Erwartetes Agent-Verhalten (L 8.3, L 10.1): `import_xlsx` und `import_docx` aufrufen, `list_roles` prüfen, dann **ein** `apply_ops`-Batch mit zwei `import.include`, ergänzten Spalten (`status`, `besteller`, `genehmigt_von`, `kommentar`, `lieferanten_nr`, `liefertermin`, `run`), Artikel-Tabelle, Aktionen und Buttons am Formular, Workflow, übrigen Schritt-Dokumenten, Einstiegsdokument und `workflow.publish`. Prüffehler liest der Agent und korrigiert selbst.

**Dateien übergeben (B11):** Bei MCP über **HTTP** (`http://localhost:8000/mcp`) läuft der Server im Backend-Container und sieht Pfade des Rechners nicht. Der Agent soll die Datei selbst lesen und `import_xlsx`/`import_docx` mit `content_base64` und `filename` aufrufen. `file_path` funktioniert nur bei **stdio** (Server läuft lokal auf dem Rechner) und für Pfade, die der Container sieht: `demo/` ist unter `/srv/demo` read-only gemountet (nach `docker compose up -d` neu starten), und ein nicht gefundener Pfad wird mit gleichem Dateinamen in `demo/` gesucht. Wird nichts gefunden, meldet das Tool `NOT_FOUND` mit dem Hinweis auf `content_base64`. Für den Prompt hilft der Zusatz: „Lies die Dateien selbst und übergib sie per `content_base64`.“

**Schlanke Tool-Schemas (B12):** `apply_ops`, `edit_document` und `create_document` nehmen Ops und Blöcke als generische Objekte, der Server validiert weiterhin strikt. Die Felder je Op-/Blocktyp liefert das Tool `describe_schema` (`topic` = `ops`, `blocks` oder ein Op-Name wie `row.update`, Blocktyp wie `form`).

### Schritt 2: Antrag stellen (Ben, Agent)

> Bestelle 2× Dell-Monitor für Kostenstelle 4711.

Erwartet: `search` findet den Bestellprozess → `start_run` → `get_task` → `complete_task` im Schritt „erfassen“ (Button „Einreichen“). Die Bestellung erscheint live in der Tabelle, der Run wartet auf Genehmigung.

### Schritt 3: Genehmigen (Chef, Browser, optional Agent)

Browser: Benachrichtigung erscheint live, Aufgabe öffnen, **Übernehmen**, „Genehmigen“. Ben darf selbst nicht genehmigen (Vier-Augen). Ablehnen verlangt einen Kommentar.

Agent im Auftrag des Chefs (Stretch):

> Zeig mir meine offenen Genehmigungen und genehmige die Bestellung von Ben, wenn der Betrag unter 1000 € liegt.

### Schritt 4: Bestellen (Anna, Browser)

Neue Aufgabe erscheint live, Bestellnummer (z. B. `LF-2026-0815`) und Liefertermin eintragen, „Bestellung abschließen“. Der Run ist abgeschlossen, die Tabelle in Annas offenem Browser zeigt den Status live.

### Schritt 5: Status (Ben, Agent)

> Wie ist der Stand meiner Bestellung?

Erwartet: `list_runs` → `get_run`, Antwort mit aktuellem Schritt, Zuständigen und Verlauf („von Bens Assistent im Auftrag von Ben Mitarbeiter“).

## 3. Aufbau der Demo-Dateien (Task 0.10)

Beide Dateien erzeugt Task 5.4 so, dass sie **ohne Handarbeit** importierbar sind (Regeln: anwendungslogik.md 8.3). Die Parser-Erwartungen stehen als Fixtures in `spec/fixtures/imports/`, Beispiele für den Aufbau in `spec/make_sample_files.py`.

### `Bestelluebersicht.xlsx`

Ein Blatt **„Bestellungen“** (wird Tabelle `bestellungen`). Erste Zeile = Spaltenköpfe, keine Leerzeilen, keine Formeln.

| Spalte | Beispielwerte (Zeilen 2–4) | Abgeleiteter Typ | Zellformat |
|---|---|---|---|
| Name | Anna Beispiel, Ben Mitarbeiter, Anna Beispiel | `text` (wird `display_column`) | Standard |
| Kostenstelle | 4710, 4711, 4712 (als **Text** gespeichert) | `text` | Text (`@`) |
| Bestelldatum | 03.11.2026, 10.11.2026, 17.11.2026 | `date` | `DD.MM.YYYY` |
| Gesamtbetrag | 498,00 €, 125,50 €, 39,90 € | `currency` (EUR) | `#,##0.00 "€"` |

Erwartung: **keine Warnungen.** Es fehlt bewusst eine Spalte `Status`. Die ergänzt der Agent im Batch mit `column.add` (L 8.3). 2–3 Beispielanträge in der Übersicht, damit der Live-Effekt der neuen Zeile sichtbar ist.

### `Bestellformular.docx`

Aufbau von oben nach unten:

1. Überschrift 1: **Bestellformular** (wird Titel des Dokuments)
2. Absatz: „Bitte Name, Kostenstelle und die benötigten Artikel angeben.“
3. Feldzeilen: `Name*: ____` (Pflicht durch Stern) und `Kostenstelle*: ____`
4. Tabelle mit Kopfzeile **Artikelname | Artikelnummer | Preis | Anzahl** und **3 leeren Zeilen** (wird `line_items` mit Schlüssel `artikelname`; Typen aus den Labels: Preis → `currency`, Anzahl → `integer`)
5. Feldzeile `Bemerkung: ____` (optional, wird `text`)
6. Absatz: „Vielen Dank.“

Erwartete Warnungen beim Import ohne `bind_table`: genau **eine**, „Formular schreibt nirgends hin“. Bilder, Kopf-/Fußzeilen oder Kommentare kommen nicht vor.

> Hinweis zur Fixture-Festlegung: In `spec/fixtures/imports/docx_form.json` ist der Schlüssel der Zeilenliste der Slug der ersten Kopfzeile. Für die Demo-Datei ergibt das `artikelname`. Der Agent bindet die Spalten der Zeilenliste im Batch an die Artikel-Tabelle (`column`-Bindung) und schreibt sie über `create_rows` mit `for_each: "{{fields.artikelname}}"`.

## 4. Offene Punkte zum Abnicken

- [ ] Rolle des Chefs als Agent in der Demo zeigen oder nur im Browser?
- [ ] Reicht eine Kostenstelle (4711), oder soll `kostenstellen` mit Verantwortlichem als Tabelle dazu (Ausdruck-Assignee, L 10.1 Hinweise)? Vorschlag: nein, Stretch.
- [ ] Sprache der Prompts: Deutsch wie oben.
