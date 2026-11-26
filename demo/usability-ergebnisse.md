# Usability-Test: Ergebnisse

Protokoll zum Test aus `demo/usability-test.md` (Anna arbeitet nur über ihren KI-Assistenten).
Es geht nicht um Zeiten oder Messwerte, sondern darum, was wir daraus lernen: Was klappt gut, was hakt, was ändern wir.

> **Stand:** Abschnitt „W1“ enthält echte Ergebnisse aus einem Agenten-Walkthrough. Alles ab
> „Erwartungen für den Test mit Person“ sind **Annahmen**, noch nicht mit einer Testperson geprüft. Nach dem echten
> Durchlauf jeden Punkt dort als **bestätigt**, **widerlegt** oder **neu** markieren.

## Durchläufe

| # | Datum | Art | Testperson | Agent / Client | Status |
|---|---|---|---|---|---|
| W1 | 26.11.2026 | Agenten-Walkthrough (ohne Testperson) | – | Claude Code (Opus 5.5) über `dock`-MCP als Anna | beide Aufgaben erfolgreich |
| 1 | | Test mit Person | | | geplant |

## W1: Agenten-Walkthrough (tatsächlich durchgeführt)

Ein KI-Agent hat die Aufgaben selbst über die MCP-Tools ausgeführt, auf frischer DB mit Seed, ohne `fallback.py`.
Das zeigt, wo der **Agent** hakt. Ob eine Person die Antworten versteht, beantwortet es nicht, dafür braucht es Durchlauf 1.

### Aufgabe 1: Ergebnis

**Erfolg:** Workflow `bestellprozess` als Version 1 veröffentlicht (Schritte Erfassen → Genehmigung → Bestellung auslösen, Ablehnung führt zum Ende).

Tatsächlicher Ablauf, rund 14 Tool-Aufrufe:

1. `import_xlsx` mit `file_path: demo/Bestelluebersicht.xlsx` → Tabelle „Bestellungen“ (4 Spalten, 3 Zeilen), keine Warnungen.
2. `list_roles` → `chef`, `einkauf`, `mitarbeiter`.
3. `import_docx` mit `bind_table` auf die importierte Tabelle → Warnung „Tabelle nicht gefunden“, Formular ohne Actions.
4. `describe_schema` für `ops`, `workflow.create`, `blocks`, `form`, `field`.
5. Ein `apply_ops`-Batch: beide `import.include`, zwei neue Spalten (Bestellnummer, Liefertermin), Action und Button „Einreichen“ am importierten Formular, zwei neue Schritt-Dokumente (Genehmigung, Bestellung auslösen), `workflow.create`. **Ging beim ersten Versuch durch.**
6. `validate_workflow` → ok, Warnungen `MANAGERS_EMPTY` und dreimal `DOCUMENT_OWNER`.
7. `validate_form` für beide Formulare → ok, keine Warnungen.
8. `workflow.update` mit Managern (`einkauf`) und Run-Titel, danach `publish_workflow` → Version 1, `DOCUMENT_OWNER`-Warnungen bleiben.

### Was gut geklappt hat

- **Import der Altdateien:** Excel kam ohne Warnung an, das Word-Formular mit Feldern (Name, Kostenstelle, Bemerkung) und Positionen (Artikelname, Artikelnummer, Preis, Anzahl).
- **Relativer Dateipfad** `demo/…` funktioniert über MCP (Fix von B11 bestätigt).
- **Tool-Hinweise führen zum richtigen Ablauf:** importieren → Rollen → ein Batch → prüfen → veröffentlichen. Der Agent musste nicht raten, in welcher Reihenfolge.
- **Ein atomarer Batch reicht** für Tabelle, Formular, Dokumente und Workflow. Kein Teilzustand, wenn etwas schiefgeht.
- **`validate_workflow` ist verständlich:** Codes, Schritt und Feld pro Meldung, Text auf Deutsch. `MANAGERS_EMPTY` hat auf eine echte Lücke hingewiesen (niemand außer dem Antragsteller hätte abbrechen können).

### Was nicht gut geklappt hat

| # | Befund | Folge | Vorschlag |
|---|---|---|---|
| W1-1 | `import_docx` mit `bind_table` auf eine Tabelle aus einem **noch nicht angewendeten** `import_xlsx` meldet „Tabelle nicht gefunden“. Die Tool-Beschreibung empfiehlt aber genau das („auch Excel, damit `bind_table` auf die importierte Tabelle zeigen kann“). | Agent muss Action und Button selbst per `block.update` bauen, dafür braucht er das große Formular-Schema. | `bind_table` auch für Tabellen aus offenen Imports auflösen oder die Tool-Beschreibung korrigieren. |
| W1-2 | `describe_schema` für einen einzelnen Blocktyp (`form`, `field`) liefert jeweils **59 KB**, weil alle 38 Blockdefinitionen mitkommen. | Füllt den Kontext des Agenten. Hier musste der Agent die Antwort lokal filtern. In einem Chat-Client geht das nicht. | Nur die Definition des gefragten Typs plus direkt referenzierte Unterobjekte ausgeben (Fortsetzung von B12). |
| W1-3 | Die **Ausdruckssprache** (`{{fields.name}}`, `{{run.steps.erfassen.results.order.id}}`, `{{today}}`) und der Zielname `end` für Übergänge sind über die MCP-Tools nicht auffindbar. Der Agent hat sie aus `anwendungslogik.md` gelesen. | Ein Agent ohne Repo-Zugriff müsste raten. | `describe_schema(topic="expressions")` oder Kurzreferenz in der Beschreibung von `apply_ops`. |
| W1-4 | Warnung `DOCUMENT_OWNER` lässt sich für importierte oder vorher angelegte Dokumente nicht beheben: `doc.update` kennt nur `title`, eine Op für den Owner fehlt. | Warnung bleibt nach dem Veröffentlichen stehen. Der Agent kann sie nur ignorieren, die Testperson würde fragen, ob etwas falsch ist. | Owner per `doc.update` setzbar machen oder `workflow.create` setzt den Owner der Schritt-Dokumente automatisch. |
| W1-5 | Positionen (`line_items`) des Formulars werden nirgends gespeichert. Die Excel-Liste hat keine Artikel-Tabelle, und `validate_form` warnt nicht, dass die Positionen verloren gehen. Der Schlüssel heißt `artikelname` (nach der ersten Spalte) statt z. B. `artikel`. | Bens „2× Dell-Monitor“ landet nur im Run, nicht in einer Tabelle. | `validate_form`-Warnung „Positionen werden nicht gespeichert“, Import schlägt eine Artikel-Tabelle vor, sprechenderer Schlüssel. |
| W1-6 | **Gesamtbetrag lässt sich nicht berechnen:** `sum(list, "key")` summiert nur eine Spalte, Preis × Anzahl geht nicht. | Spalte „Gesamtbetrag“ bleibt bei neuen Bestellungen leer. | `sum` mit Ausdruck pro Element erlauben oder berechnete Spalte in den Positionen. |
| W1-7 | `workflow.update` verlangt die **komplette Definition**, auch wenn nur `managers` ergänzt wird. | Lange Aufrufe, Risiko, beim Abschreiben etwas zu verlieren. | Patch-Semantik oder eigene Ops für einzelne Felder. |

### Zwischenschritt Testteam

Ben und Chef wurden per REST mit ihren Seed-Tokens gespielt (nicht per Agent):

- Ben startet den Run, trägt Name, Kostenstelle 4711 und eine Position „Dell-Monitor P2723D, 289,00 €, Anzahl 2“ ein und klickt „Einreichen“. Es entsteht eine neue Zeile in „Bestellungen“, die Aufgabe geht an die Rolle `chef`, Ben ist per Vier-Augen-Prinzip ausgeschlossen.
- Chef klickt „Genehmigen“, die Aufgabe geht an die Rolle `einkauf`.

### Aufgabe 2: Ergebnis

**Erfolg:** Aufgabe erledigt, Run `completed` mit Ergebnis „Bestellt“. Bestellnummer `LF-2026-0815` und Liefertermin `2026-12-03` stehen in Bens Zeile der Tabelle.

Tatsächlicher Ablauf, 3 Tool-Aufrufe: `list_tasks` → genau eine offene Aufgabe „Bestellung auslösen“ → `get_task` (Felder und Button-ID) → `complete_task` mit Button `bestellt`. Zur Kontrolle danach `get_run` und `query_rows`.

### Was gut geklappt hat

- **Kurz und eindeutig:** Bei einer offenen Aufgabe gab es nichts zu raten. `get_task` liefert Pflichtfelder und Button-IDs, wie die Tool-Beschreibung verspricht.
- **Kein Übernehmen nötig:** `complete_task` ging bei einer Rollen-Aufgabe direkt durch, ohne vorheriges `claim_task`.
- **Datum aus Alltagssprache:** „3. Dezember“ → `2026-12-03` hat der Agent selbst umgesetzt, das Datumsfeld hat den Wert angenommen.
- **Nachvollziehbarer Verlauf:** `get_run` zeigt jeden Schritt mit Person, Zeit und Button. Annas Schritt steht als „Annas Assistent im Auftrag von Anna Beispiel“ drin.
- **Rückschreiben in die Tabelle:** Die `update_row`-Action über `{{run.steps.erfassen.results.order.id}}` hat genau Bens Zeile getroffen.

### Was nicht gut geklappt hat

| # | Befund | Folge | Vorschlag |
|---|---|---|---|
| W1-8 | Die vom Agenten gebauten Schritt-Dokumente **zeigen nicht, worum es geht:** Der Chef sieht nur ein Kommentarfeld und zwei Buttons, Anna nur Bestellnummer und Liefertermin, keine Artikel, keine Kostenstelle. Weder `validate_workflow` noch die Tool-Hinweise haben darauf hingewiesen. | Chef genehmigt blind, Anna weiß nicht, was sie bestellen soll. Für die Demo ist das der größte inhaltliche Mangel. | Warnung in `validate_workflow`, wenn ein späterer Schritt keine Werte früherer Schritte anzeigt. Tool-Hinweis: Genehmigungs-Dokument mit Zusammenfassung (`{{run.steps.erfassen.values…}}`) anlegen. |
| W1-9 | Bestätigt W1-5 und W1-6: Die Position „2× Dell-Monitor“ steht nirgends in einer Tabelle, „Gesamtbetrag“ ist in Bens neuer Zeile leer (alte Excel-Zeilen haben ihn). | Die Übersichtstabelle ist für neue Bestellungen unvollständig. | siehe W1-5, W1-6 |
| W1-10 | Run-Titel „Bestellung Ben Mitarbeiter (Ben Mitarbeiter)“: Das Formularfeld „Name“ ist der Name des Bestellers, also doppelt mit dem Antragsteller. Der Fehler liegt beim Agenten, das Formular gibt aber auch keinen Hinweis. | Unschön in „Meine Aufgaben“ und Benachrichtigungen. | Import setzt für ein Feld „Name“ den Default `{{user.name}}`. Tool-Hinweis mit einem guten Beispiel für `run_title`. |
| W1-11 | Positionen heißen im Formular „Artikelname“ (Label und Schlüssel), weil der Import die erste Spalte als Namen nimmt. | Verwirrend für Ben im Browser und für den Agenten (`artikelname: [{artikelname: …}]`). | Beim Import den Tabellentitel oder „Artikel“/„Positionen“ als Label verwenden. |

### Abgleich mit den Erwartungen

- **Widerlegt:** „Übernehmen vor Erledigen erzeugt Fehler“ (E5). `complete_task` ging direkt durch.
- **Widerlegt:** „Dateipfade beim Import“ (E3). Der relative Pfad funktioniert.
- **Bestätigt:** Technische IDs in den Antworten (E2). Alle Rückgaben enthalten nur IDs (`wf_…`, `row_…`), keine Links. Ein Agent müsste sie für die Testperson selbst übersetzen.
- **Neu:** W1-1 bis W1-4, W1-8, W1-10, W1-11. Vor allem W1-8: Inhaltsleere Genehmigungsschritte stehen nicht in den Erwartungen.
- **Nicht prüfbar ohne Person:** Wartezeit-Gefühl, Verständlichkeit der Antworten, Rückfragen (E1, E4, E6).

# Erwartungen für den Test mit Person (noch nicht geprüft)

## Aufgabe 1: Bestellprozess aus Word + Excel bauen lassen

**Erwarteter Ablauf beim Agenten:** `import_xlsx` und `import_docx` → `list_roles` → ein `apply_ops`-Batch mit `import.include` → `validate_workflow` → `publish_workflow`.

### Was vermutlich gut klappt

- **Einstieg ohne Fachbegriffe.** Die Testperson beschreibt den Prozess in eigenen Worten („Mitarbeiter füllt aus, Chef genehmigt, dann bestelle ich“), und der Agent findet daraus die Schritte. Die Hinweise in den Tool-Beschreibungen (erst importieren, dann Rollen, dann ein Batch) führen ihn auf den richtigen Weg.
- **Import der Altdateien.** Spalten aus `Bestelluebersicht.xlsx` und Felder aus `Bestellformular.docx` kommen sauber an. Die Testperson erkennt „ihre“ Felder wieder, das schafft Vertrauen.
- **Fehler korrigiert der Agent selbst.** Meldet `validate_workflow` etwas (z. B. fehlende Zuständige), baut der Agent nach, ohne dass die Testperson eingreifen muss.
- **Ergebnis ist im Browser sichtbar.** Der Workflow-Graph mit „Erfassen → Genehmigung → Bestellung auslösen“ zeigt der Testperson, dass „wirklich etwas entstanden ist“.

### Was vermutlich nicht so gut klappt

- **Wartezeit ohne Rückmeldung.** Der Agent arbeitet mehrere Tool-Aufrufe hintereinander ab. Die Testperson weiß in der Zeit nicht, ob noch etwas passiert, und fragt nach („Ist er fertig?“).
- **Dateipfade.** Die Testperson sagt „die Dateien im Ordner demo“. Der Agent muss den Pfad erraten oder nachfragen. Mit relativem Pfad kann der erste Import scheitern.
- **Rückfragen, die die Testperson nicht beantworten kann.** Fragt der Agent nach Rollen-IDs, Pflichtfeldern oder dem Ablehnungsfall („Was passiert, wenn der Chef ablehnt?“), zögert die Testperson. Den Ablehnungsfall hat sie in der Aufgabe nicht bedacht.
- **„Veröffentlicht“ ist kein Alltagswort.** Ob der Workflow nur angelegt oder schon nutzbar ist, ist für die Testperson aus der Agenten-Antwort nicht klar.
- **Lange, technische Agenten-Antwort.** Die Zusammenfassung nennt IDs (`wf_…`, `tbl_…`) und Op-Namen. Die Testperson liest darüber hinweg und sucht nur nach „hat geklappt“.

## Aufgabe 2: Bestellnummer und Liefertermin eintragen

**Erwarteter Ablauf beim Agenten:** `list_tasks` → passende Aufgabe zu Bens Antrag finden → ggf. `claim_task` → `complete_task` mit Bestellnummer `LF-2026-0815` und Liefertermin `2026-12-03`.

### Was vermutlich gut klappt

- **Natürliche Sprache reicht.** „Ich habe bestellt, Nummer LF-2026-0815, Lieferung am 3. Dezember“ genügt. Der Agent findet die offene Aufgabe von selbst und wandelt das Datum ins richtige Format um.
- **Deutlich schneller als Aufgabe 1.** Ein bis zwei Prompts, die Testperson wirkt sicherer, weil sie den Ablauf jetzt kennt.
- **Status ist sofort sichtbar.** Im Browser springt der Run live auf „Bestellt“, Ben bekommt die Benachrichtigung. Das ist der Moment, in dem der Nutzen klar wird.

### Was vermutlich nicht so gut klappt

- **Welche Bestellung?** Gibt es mehrere offene Aufgaben, fragt der Agent nach oder nimmt die falsche. Die Testperson nennt „die von Ben“, der Agent muss den Antrag über den Antragsteller zuordnen.
- **Übernehmen vor Erledigen.** Ist die Aufgabe der Rolle `einkauf` zugewiesen, muss der Agent sie erst übernehmen. Scheitert `complete_task` zuerst, sieht die Testperson eine Fehlermeldung, die sie nicht versteht.
- **Feldnamen passen nicht genau.** Heißt das Feld im Formular z. B. „Lieferdatum“ statt „Liefertermin“, rät der Agent oder fragt nach.

## Schlussfragen: erwartete Aussagen der Testperson

- **Einfach:** „Ich musste nichts über die Plattform wissen, nur sagen, was ich will.“ – „Dass meine Excel-Liste und das Word-Formular übernommen wurden.“
- **Unklar:** „Ich wusste nicht, ob der Assistent fertig ist oder noch arbeitet.“ – „Ich hätte gern gesehen, was er gebaut hat, bevor es live geht.“ – „Wo sehe ich das jetzt, ohne den Assistenten zu fragen?“

## Erkenntnisse und mögliche Maßnahmen

| # | Erkenntnis | Mögliche Maßnahme | Wo | Priorität |
|---|---|---|---|---|
| E1 | Testperson ist unsicher, wann der Agent fertig ist | Tool-Beschreibungen: Agent soll am Ende kurz in Alltagssprache zusammenfassen („Der Bestellprozess ist eingerichtet und kann ab jetzt genutzt werden“) und den Link zum Workflow nennen | MCP-Tool-Hinweise | Hoch |
| E2 | IDs und Fachbegriffe in Agenten-Antworten | Rückgaben von `publish_workflow`/`complete_task` um lesbare Namen und eine URL ergänzen, damit der Agent die nennen kann | MCP/Backend | Mittel |
| E3 | Dateipfade beim Import | Fehlermeldung bei unbekanntem Pfad mit Hinweis „absoluten Pfad verwenden“, Pfad im Vorlesetext nennen | MCP, Testablauf | Mittel |
| E4 | Ablehnungsfall wird nicht bedacht | Agent soll einen Standard vorschlagen („Bei Ablehnung endet der Antrag, Ben wird benachrichtigt – passt das?“) statt offen zu fragen | MCP-Tool-Hinweise | Mittel |
| E5 | Übernehmen vor Erledigen erzeugt Fehler | `complete_task` übernimmt eine freie Rollen-Aufgabe automatisch oder die Fehlermeldung sagt, was zu tun ist | Backend/MCP | Mittel |
| E6 | Vorschau vor dem Veröffentlichen gewünscht | Agent zeigt zuerst Schritte und Zuständige und veröffentlicht erst nach Bestätigung | MCP-Tool-Hinweise | Niedrig |

Neue Bugs aus dem Test zusätzlich in `demo/bugs.md` eintragen (Bereich `MCP/Agent`, „Gefunden in: Usability-Test“).

## Notizen aus dem echten Durchlauf

_Hier nach dem Test eintragen: Zitate der Testperson, Stellen, an denen sie gezögert hat, was der Agent anders gemacht hat als erwartet._
