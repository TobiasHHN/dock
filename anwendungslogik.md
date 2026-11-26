# Anwendungslogik: Tabellen, Dokumente, Formulare und Workflows

Dieses Dokument beschreibt **nur die Logik** der Anwendung: Datenstrukturen, Regeln, Operationen und den Echtzeit-Abgleich. Tech-Stack, Datenbank-Details und UI sind bewusst nicht Teil davon (siehe `technische-umsetzung.md`).

## 0. Kernentscheidungen auf einen Blick

1. **Objekte:** `Table`, `Document`, `Workflow`, `Run` und `Task`. Dazu `User` und `Role` für Zuständigkeiten.
2. **Tabellen sind typisiert** (wie Airtable) und existieren eigenständig im Workspace. Dokumente zeigen sie nur an (`table_view`).
3. **Dokumente sind Blockbäume**, flach gespeichert mit `parent_id` und Sortierposition. Jeder Absatz ist einzeln adressierbar.
4. **Eingaben laufen über Formulare.** Ein `form`-Block enthält Eingabefelder und legt deklarativ fest, was beim Klick auf einen Button passiert (`actions`).
5. **Ein Workflow ist eine Folge von Dokumenten.** Jeder Schritt ist ein Dokument, die Buttons der Formulare bestimmen den nächsten Schritt.
6. **Jeder Schritt hat Zuständige** (Personen und/oder Rollen). Beim Betreten eines Schritts entsteht eine **Aufgabe** (`Task`), die in der Aufgabenliste der Zuständigen erscheint. Der Antragsteller verfolgt den Status seines Runs live.
7. **Ein einziger Schreibweg:** Browser, Agent (MCP) und Workflow-Engine schicken dieselben **Operationen** an den Server. Der Server prüft, speichert, protokolliert und verteilt sie per WebSocket an alle.
8. **Bestehende Dateien lassen sich importieren.** Excel (`.xlsx`) wird zu Tabellen, Word (`.docx`) zu Dokumenten mit Formular (8.3). Der Import erzeugt nur Operationen, es gibt keinen zweiten Schreibweg.

---

## 1. IDs und Keys

Jedes Objekt hat eine **ID** (unveränderlich) und, wo sinnvoll, einen **Key** (lesbar, änderbar, eindeutig im jeweiligen Bereich).

| Objekt | ID-Präfix | Key-Beispiel | Eindeutig in |
|---|---|---|---|
| Nutzer | `usr_` | – | System |
| Agent | `agt_` | – | System |
| Rolle | `rol_` | `einkauf` | Workspace |
| Tabelle | `tbl_` | `bestellungen` | Workspace |
| Spalte | `col_` | `kostenstelle` | Tabelle |
| Zeile | `row_` | – | Tabelle |
| Dokument | `doc_` | – | – |
| Block | `blk_` | – | Dokument |
| Formularfeld | (ist ein Block) | `name` | Formular |
| Workflow | `wf_` | `bestellprozess` | Workspace |
| Workflow-Schritt | – | `erfassen` | Workflow |
| Run | `run_` | – | – |
| Aufgabe | `tsk_` | – | – |
| Formular-Aktion | – | `order` | Formular |

- IDs sind **Präfix + ULID** (z. B. `blk_01JD8X…`). Sie werden **vom Client erzeugt**. Damit kann ein Agent oder Browser in einem einzigen Batch eine Tabelle anlegen und gleich Spalten und Zeilen darauf beziehen, ohne auf Server-IDs zu warten. Der Server prüft nur die Eindeutigkeit. Ausnahme: Nutzer kommen aus dem Identity Provider.
- Die API und MCP akzeptieren überall **ID oder Key** (`tbl_01J…` oder `bestellungen`, `bestellungen.kostenstelle`, `einkauf`). Gespeichert wird immer die ID. So brechen Referenzen nicht, wenn jemand eine Spalte oder Rolle umbenennt.
- Sortierpositionen (`position`) sind **Fractional Indexes** (Strings wie `"a0"`, `"a0V"`). Einfügen zwischen zwei Elementen ändert nur das neue Element.

---

## 2. Tabellen

### 2.1 Datenstruktur

```ts
type Table = {
  id: TableId;
  key: string;                 // "bestellungen"
  name: string;                // "Bestellungen"
  columns: Column[];
  display_column: ColumnId;    // wird bei Referenzen auf diese Tabelle angezeigt
  version: number;             // Schema-Version, steigt bei jeder Schemaänderung
};

type Column = {
  id: ColumnId;
  key: string;                 // "kostenstelle"
  name: string;                // "Kostenstelle"
  type: ColumnType;
  required: boolean;
  unique: boolean;
  default?: Value | "{{now}}" | "{{user.id}}";
  position: string;
};

type ColumnType =
  | { kind: "text" }
  | { kind: "long_text" }
  | { kind: "integer"; min?: number; max?: number }
  | { kind: "number"; decimals: number }
  | { kind: "currency"; currency: "EUR" | string }
  | { kind: "boolean" }
  | { kind: "date" }
  | { kind: "datetime" }
  | { kind: "select"; options: { id: string; label: string }[] }
  | { kind: "user" }
  | { kind: "reference"; table: TableId; on_delete: "restrict" | "cascade" | "set_null" };

type Row = {
  id: RowId;
  table_id: TableId;
  position: string;
  values: Record<ColumnId, Value | null>;
  created_at: string; created_by: Actor;
  updated_at: string; updated_by: Actor;
  version: number;
};
```

### 2.2 Regeln

- **Werte werden beim Schreiben in den Spaltentyp umgewandelt** (z. B. `"12,50"` → `12.5` bei `currency`). Gelingt das nicht, wird die ganze Operation abgelehnt, mit einer Fehlermeldung pro Feld.
- `required`, `unique`, `min`/`max` und gültige Referenzen werden **serverseitig** geprüft.
- `update_row` ändert **nur die übergebenen Spalten**. Zwei Personen, die gleichzeitig verschiedene Zellen derselben Zeile ändern, kommen sich daher nicht in die Quere.
- **Spalte löschen** ist nur erlaubt, wenn sie nirgends mehr verwendet wird (Formular-Aktion, Filter, Feld-Bindung). Sonst kommt ein Fehler mit der Liste der Verwendungen (siehe Abschnitt 9).
- **Spaltentyp ändern** konvertiert bestehende Werte. Was nicht konvertierbar ist, wird `null`. Ist die Spalte `required`, wird die Änderung abgelehnt und die betroffenen Zeilen werden genannt.
- **Zeile löschen** beachtet `on_delete` der Referenzspalten, die auf diese Tabelle zeigen: `restrict` blockiert, `cascade` löscht die abhängigen Zeilen mit, `set_null` leert die Referenz.

---

## 3. Dokumente

### 3.1 Datenstruktur

```ts
type Document = {
  id: DocumentId;
  title: string;
  owner?: { workflow: WorkflowId; step: string | null };  // Schritt-Dokument; step null = Übersichtsdokument des Workflows
  version: number;            // steigt mit jeder Operation am Dokument
};

type Block = {
  id: BlockId;
  doc_id: DocumentId;
  parent_id: BlockId | null;  // null = oberste Ebene
  position: string;           // Reihenfolge unter Geschwistern
  type: BlockType;
  props: BlockProps;          // abhängig vom Typ, siehe 3.2
  version: number;            // für Konflikterkennung pro Block
};
```

Gespeichert wird **flach** (eine Liste von Blöcken). Der Baum ergibt sich aus `parent_id` und `position`. So kann man jeden einzelnen Absatz lesen, ändern, verschieben oder löschen, ohne das ganze Dokument anzufassen.

### 3.2 Blocktypen

| Typ | `props` | Kinder erlaubt |
|---|---|---|
| `heading` | `level: 1–3`, `content: Inline[]` | nein |
| `paragraph` | `content: Inline[]` | nein |
| `list` | `ordered: boolean` | nur `list_item` |
| `list_item` | `content: Inline[]`, `checked?: boolean` | `list` (Verschachtelung) |
| `quote` | – | Textblöcke |
| `code` | `language`, `text` | nein |
| `divider` | – | nein |
| `image` | `asset_id`, `alt` | nein |
| `table_view` | `table`, `columns?`, `filter?`, `sort?`, `editable`, `allow_add`, `allow_delete` | nein |
| `form` | `buttons?`, `actions` (siehe 4) | alle außer `form` |
| `field` | `key`, `label`, `input`, `required`, `column?`, `default?` | nein, nur innerhalb von `form` |
| `line_items` | `key`, `label`, `columns`, `min_rows?` | nein, nur innerhalb von `form` |
| `workflow` | `workflow`, `mode` (siehe 5.5) | nein |

### 3.3 Inline-Inhalt

Text in `heading`, `paragraph` und `list_item` ist eine Liste von Abschnitten:

```ts
type Inline =
  | { t: "text"; text: string; marks?: ("bold" | "italic" | "code" | "strike")[] }
  | { t: "link"; text: string; href: string }
  | { t: "mention"; target: Uri }        // Link auf Dokument, Block, Tabelle, Zeile, Nutzer
  | { t: "value"; expr: string };         // berechneter Wert, z. B. "{{run.steps.erfassen.values.name}}"
```

`mention` und `value` sind die „Referenzen auf Tabellen“ im Fließtext. `value` wird beim Anzeigen ausgewertet (siehe 4.5).

### 3.4 `table_view`: Tabellen im Dokument

Ein `table_view` zeigt eine vorhandene Tabelle an. Er enthält **keine eigenen Daten**.

```json
{
  "type": "table_view",
  "props": {
    "table": "tbl_artikel",
    "columns": ["col_artikelname", "col_anzahl", "col_preis"],
    "filter": [{ "column": "col_bestellung", "op": "eq", "value": "{{run.steps.erfassen.results.order.id}}" }],
    "sort": [{ "column": "col_artikelname", "dir": "asc" }],
    "editable": false,
    "allow_add": false,
    "allow_delete": false
  }
}
```

- `editable: true` heißt: Änderungen an Zellen werden **sofort** als `update_row` gespeichert. Dafür gibt es **keinen** Speichern-Button.
- Filterwerte dürfen Ausdrücke enthalten, zum Beispiel um im Workflow nur die Artikel der aktuellen Bestellung zu zeigen.

### 3.5 Zwei Arten von bearbeitbaren Daten

Diese Unterscheidung ist zentral:

| | **Live-Daten** | **Entwurfsdaten** |
|---|---|---|
| Wo | `table_view` mit `editable`, Text-Blöcke | `field`, `line_items` in einem `form` |
| Wann gespeichert | sofort bei jeder Änderung | erst beim Klick auf einen Button des Formulars |
| Wohin | direkt in Tabelle bzw. Dokument | über die `actions` des Formulars in beliebige Tabellen |
| Button nötig | nein | ja |

---

## 4. Formulare

### 4.1 Datenstruktur

```ts
type FormProps = {
  actions: Action[];                 // was beim Absenden passieren kann
  buttons?: Button[];                // fehlt → automatischer "Speichern"-Button
  reset_after_submit?: boolean;      // Standard: true außerhalb von Workflows
};

type Button = {
  id: string;                        // "save", "approve", "reject"
  label: string;                     // Aufforderung ("Genehmigen", "Ablehnen"); Verlauf und Status zeigen das Ergebnis, siehe 10.1
  style?: "primary" | "secondary" | "danger";
  actions: string[];                 // Keys der auszuführenden Actions, in dieser Reihenfolge
  outcome?: string;                  // für Workflows: bestimmt den nächsten Schritt
  validate?: boolean;                // Standard true: Pflichtfelder prüfen
  require?: string[];                // zusätzliche Pflichtfelder nur für diesen Button
                                     // (z. B. Kommentar nur beim Ablehnen)
  confirm?: string;                  // optionale Rückfrage
};

type FieldProps = {
  key: string;                       // eindeutig im Formular, z. B. "name"
  label: string;
  input: "text" | "textarea" | "integer" | "number" | "currency" | "date"
       | "boolean" | "select" | "reference" | "user";
  required?: boolean;
  column?: ColumnId;                 // optional: übernimmt Typ, Label, Optionen, Pflicht aus dieser Spalte
  default?: Value | string;          // auch Ausdruck möglich
  options?: { id: string; label: string }[];   // für select
  reference_table?: TableId;         // für reference
};

type LineItemsProps = {
  key: string;                       // "artikel"
  label: string;
  columns: {                         // Spalten der Eingabetabelle
    key: string;                     // "preis"
    label?: string;
    column?: ColumnId;               // optional: Typ etc. aus Tabellenspalte übernehmen
    input?: FieldProps["input"];
    required?: boolean;
  }[];
  min_rows?: number;
};
```

`line_items` ist die „leere Tabelle im Formular“: Der Nutzer kann Zeilen hinzufügen, bearbeiten und löschen. Diese Zeilen sind nur Entwurf und landen erst beim Absenden über eine Action in einer echten Tabelle.

**Die Bindung `column`** ist eine Abkürzung: Ein Feld mit `column: "col_kostenstelle"` bekommt automatisch Eingabetyp, Label, Pflichtangabe und Optionen dieser Spalte. Wohin der Wert geschrieben wird, legt trotzdem allein die Action fest. So kann ein Feld auch in mehrere Tabellen schreiben oder gar nicht gespeichert werden (z. B. ein reines Steuerfeld).

### 4.2 Actions

```ts
type Action =
  | { key: string; type: "create_row";  table: TableId; values: Record<ColumnId, Expr> }
  | { key: string; type: "create_rows"; table: TableId; for_each: Expr; values: Record<ColumnId, Expr> }
  | { key: string; type: "update_row";  table: TableId; row: Expr; values: Record<ColumnId, Expr> }
  | { key: string; type: "delete_row";  table: TableId; row: Expr };
```

- Actions laufen **in der Reihenfolge des Buttons** und **in einer Transaktion**. Schlägt eine fehl, wird nichts gespeichert.
- Jede Action legt ihr Ergebnis unter `results.<key>` ab. Spätere Actions können darauf zugreifen: `results.order.id`.
- `create_rows` läuft einmal pro Element von `for_each`. Das aktuelle Element heißt `item`.

### 4.3 Wann wird ein Button angezeigt?

Für jedes `form` wird beim Rendern berechnet:

```
editable_fields = Anzahl der field- und line_items-Blöcke im Formular (rekursiv)

buttons =
  form.buttons                       falls explizit angegeben
  [{ id:"save", label:"Speichern",
     actions: alle Actions }]        falls nicht angegeben UND editable_fields > 0
  []                                 sonst

sichtbar = buttons.length > 0
           UND Nutzer hat Recht "submit" auf das Dokument
           UND (kein Workflow-Kontext
                ODER (run.status = "active"
                      UND run.current_step = Schritt dieses Dokuments
                      UND can_act(Nutzer, offene Aufgabe des Schritts)   // siehe 5.9
                      UND kein wartender Sub-Run offen))                 // siehe 5.6
```

Ein Dokument ohne Formular oder ein Formular ohne Felder zeigt also **keinen** Speichern-Button. Ein Freigabe-Schritt ohne Felder kann trotzdem Buttons haben („Genehmigen“, „Ablehnen“), weil sie explizit angegeben sind.

Wer einen Run sehen darf, aber nicht zuständig ist (z. B. der Antragsteller in Schritt 2), sieht das Schritt-Dokument **schreibgeschützt**. In abgeschlossenen Schritten werden Formulare mit den damals abgeschickten Werten angezeigt.

### 4.4 Entwürfe (Draft)

Die Eingaben im Formular werden serverseitig als Entwurf gehalten. Dadurch sehen andere Personen im selben Run live, was eingetragen wird, und nichts geht beim Neuladen verloren.

```ts
type FormDraft = {
  form_block: BlockId;
  scope: { run: RunId } | { user: UserId };   // im Workflow pro Run, sonst pro Nutzer
  values: Record<string, Value | LineItem[]>; // Key → Wert
  version: number;
};
type LineItem = { id: string; position: string; values: Record<string, Value> };
```

- Im **Workflow** ist der Entwurf an den Run gebunden. Alle, die die Aufgabe erledigen dürfen, sehen und bearbeiten denselben Entwurf.
- **Außerhalb** von Workflows hat jeder Nutzer seinen eigenen Entwurf. Nach dem Absenden wird er geleert (`reset_after_submit`).

### 4.5 Ausdrücke

Eine bewusst kleine Ausdruckssprache, **keine** Formel-Engine. Ausdrücke stehen in `{{ … }}`.

| Pfad | Bedeutung |
|---|---|
| `fields.<key>` | Wert eines Feldes, bei `line_items` die Liste der Zeilen |
| `item.<key>` | aktuelles Element in `create_rows.for_each` |
| `results.<action>.id` | ID der von einer Action angelegten Zeile (bei `create_rows`: `ids`) |
| `run.id`, `run.input.<x>` | aktueller Run und seine Startparameter |
| `run.starter.id`, `run.starter.name` | Antragsteller (wer den Run gestartet hat) |
| `run.steps.<step>.values.<key>` | abgeschickter Feldwert eines früheren Schritts |
| `run.steps.<step>.results.<action>.id` | Ergebnis einer Action eines früheren Schritts |
| `run.steps.<step>.completed_by.id` | wer den Schritt erledigt hat |
| `user.id`, `user.name` | aktueller Nutzer |
| `now`, `today` | Zeitpunkt bzw. Datum |

Erlaubte Funktionen:

| Funktion | Zweck |
|---|---|
| `sum(list, "key")`, `count(list)` | Summen und Anzahl, z. B. über `line_items` |
| `concat(a, b, …)`, `coalesce(a, b, …)` | Text zusammensetzen, Ersatzwert |
| `lookup(table, column, value, result_column)` | Wert aus der ersten Zeile mit `column = value`, z. B. den Verantwortlichen einer Kostenstelle |

Mehr nicht. Besteht ein Wert nur aus einem Ausdruck, bleibt sein Typ erhalten (Zahl bleibt Zahl). Sonst ist das Ergebnis Text.

### 4.6 Ablauf beim Absenden

```
1. Client: form.submit { submission_id, form_block, button, run?, draft_version }
2. Server: lädt das Formular
           (im Run: aus dem eingefrorenen Stand der Workflow-Version, siehe 5.3)
3. Server: prüft die Sichtbarkeitsregel aus 4.3, sonst Fehler FORBIDDEN
4. Server: nimmt die Werte aus dem Entwurf und prüft Felder
           (required, button.require, Typ, min_rows), falls button.validate
           → bei Fehlern: { errors: { "<field>": "..." } }, nichts gespeichert
5. Server: führt die Actions des Buttons in einer Transaktion aus
           → wertet Ausdrücke aus, wandelt Typen um, prüft Tabellenregeln
6. Server: speichert eine Submission (wer, wann, Werte, results) und
           leert ggf. den Entwurf
7. Server: im Run → Aufgabe abschließen, Schritt-Ergebnis speichern,
           Übergang anhand button.outcome (siehe 5.4)
8. Server: alle Änderungen gehen als ein Batch ins Operations-Log und
           per WebSocket an alle Abonnenten (Tabellen, Run, Dokument, Nutzer)
9. Client: { results, run?: { current_step, status } }
```

`submission_id` wird vom Client erzeugt. Kommt dieselbe ID zweimal an (Doppelklick, Netzwerk-Retry), liefert der Server das erste Ergebnis zurück und führt nichts erneut aus.

---

## 5. Workflows

### 5.1 Begriffe

| Begriff | Was es ist |
|---|---|
| **Workflow** | Definition: Schritte (je ein Dokument mit Zuständigen) und Übergänge. Wird bearbeitet und dann veröffentlicht. |
| **Workflow-Version** | Unveränderlicher, veröffentlichter Stand inklusive eingefrorener Schritt-Dokumente. |
| **Run** | Eine konkrete Ausführung, z. B. „Bestellung KS 4711 – Anna“. Gehört fest zu einer Version. |
| **Aufgabe (Task)** | Entsteht, wenn ein Run einen Schritt betritt. Sagt, wer jetzt etwas tun muss. |
| **Antragsteller** | Wer den Run gestartet hat (`run.started_by`). |
| **`workflow`-Block** | Platziert einen Workflow in einem Dokument: Startknopf und Liste der Runs. |

### 5.2 Datenstruktur

```ts
type Workflow = {
  id: WorkflowId;
  key: string;                       // "bestellprozess"
  name: string;
  draft: WorkflowDefinition;         // wird bearbeitet
  latest_version: number | null;     // null = noch nie veröffentlicht
};

type WorkflowDefinition = {
  start: string;                     // Key des ersten Schritts
  steps: Step[];
  transitions: Transition[];
  starters: Assignee[];              // wer Runs starten darf (leer = alle mit Zugriff auf den Workflow)
  managers: Assignee[];              // sehen alle Runs, dürfen umverteilen und abbrechen,
                                     // bekommen Aufgaben ohne auflösbare Zuständige
  run_title?: Expr;                  // Titel eines Runs, wird nach jedem Schritt neu ausgewertet
  starter_can_cancel?: boolean;      // Standard true
  layout?: Record<string, { x: number; y: number }>;   // nur Anzeige (Node-Positionen), von der Engine ignoriert
};

type Step = {
  key: string;                       // "genehmigung"
  name: string;                      // "Genehmigung"
  status_label?: string;             // Text für den Antragsteller, z. B. "Wartet auf Genehmigung"
  document: DocumentId;              // Dokument mit owner = { workflow, step }
  assignees: Assignee[];             // mindestens einer; jeder Kandidat darf die Aufgabe erledigen
  exclude_starter?: boolean;         // Vier-Augen-Prinzip: Antragsteller darf nicht selbst
  exclude_steps?: string[];          // wer diese Schritte erledigt hat, darf hier nicht
  due_in?: string;                   // Frist als ISO-Dauer, z. B. "P2D"
};

type Assignee =
  | { kind: "starter" }                       // der Antragsteller
  | { kind: "user"; user: UserId }            // eine bestimmte Person
  | { kind: "role"; role: RoleId }            // alle mit dieser Rolle
  | { kind: "expr"; expr: string };           // Ausdruck, der User-ID(s) liefert,
                                              // z. B. lookup(kostenstellen, nummer, …, verantwortlich)

type Transition = {
  from: string;                      // Step-Key
  on: string;                        // Outcome eines Buttons, oder "*" für alle
  to: string | "end";
};

type WorkflowVersion = {
  workflow_id: WorkflowId;
  version: number;
  definition: WorkflowDefinition;
  documents: Record<DocumentId, Block[]>;   // eingefrorene Kopie aller Schritt-Dokumente
  published_at: string;
  published_by: Actor;
};

type Run = {
  id: RunId;
  workflow_id: WorkflowId;
  version: number;
  title: string;                     // aus run_title, sonst Workflow-Name + Datum
  status: "active" | "completed" | "cancelled";
  current_step: string | null;       // null, wenn nicht aktiv
  result?: { outcome: string; label: string };   // letzter Button vor "end", z. B. "Bestellt"
  parent?: { run: RunId; step: string; block: BlockId };   // bei Sub-Workflows
  started_by: Actor;
  started_at: string;
  ended_at?: string;
  input: Record<string, Value>;
  steps: Record<string, StepResult>;
};

type StepResult = {
  outcome: string;
  label: string;                         // Label des Buttons
  values: Record<string, unknown>;       // abgeschickte Feldwerte
  results: Record<string, unknown>;      // Ergebnisse der Actions
  completed_by: Actor;
  completed_at: string;
};
```

### 5.3 Schritt-Dokumente

- Jeder Schritt zeigt auf ein **normales Dokument**. Es wird mit denselben Operationen bearbeitet wie jedes andere Dokument, auch per MCP.
- **Beim Veröffentlichen** werden alle Schritt-Dokumente eingefroren und in die Version kopiert. Laufende Runs sehen immer genau den Stand, mit dem sie gestartet wurden. Änderungen am Dokument wirken erst ab der nächsten Version.
- Ein Schritt-Dokument wird **im Kontext eines Runs** angezeigt. Ausdrücke wie `{{run.steps.erfassen.results.order.id}}` in Text, Filtern und Actions werden mit den Daten dieses Runs ausgewertet.

### 5.4 Ablauf

```
start_run(workflow, input?)
  → prüfen: Nutzer ist in definition.starters (falls gesetzt)
  → Run anlegen mit latest_version, status = active
  → Event "started"
  → enter_step(definition.start)

enter_step(S)
  → run.current_step = S
  → Aufgabe anlegen (5.9), Event "step_entered", Zuständige benachrichtigen
  → run.title neu auswerten

form.submit im Schritt S mit Button B
  → Actions ausführen (4.6)
  → Aufgabe: status = done, outcome = B.outcome, completed_by
  → run.steps[S] = { outcome: B.outcome, label: B.label, values, results, … }
  → Event "step_completed", Antragsteller benachrichtigen
  → t = Transition mit from = S und on = B.outcome, sonst on = "*"
  → t.to = "end" → status = completed, result = { B.outcome, B.label },
                   current_step = null, Event "completed"
                   (bei Sub-Run: Eltern-Run wird benachrichtigt, siehe 5.6)
  → sonst        → enter_step(t.to)

cancel_run(reason)
  → erlaubt für Antragsteller (wenn starter_can_cancel) und managers
  → offene Aufgabe: status = cancelled
  → status = cancelled, Event "cancelled", Beteiligte benachrichtigen
```

Ein Schritt kann mehrmals besucht werden (z. B. „Rückfrage“ → zurück zu „erfassen“). `run.steps[S]` enthält dann den letzten Stand, der vollständige Verlauf steht in den Events (5.10). Weil die Actions des Schritts dabei erneut laufen, sollten Schritte, die wiederholt besucht werden können, bestehende Zeilen mit `update_row` ändern statt neue mit `create_row` anzulegen. `validate_workflow` warnt davor (5.7).

### 5.5 Der `workflow`-Block

```ts
type WorkflowBlockProps = {
  workflow: WorkflowId;
  mode: "launcher"      // Startknopf (nur für starters) und Liste der Runs, die der Nutzer sehen darf
      | "run"           // zeigt genau einen Run an
      | "subflow";      // nur in Schritt-Dokumenten: startet einen Kind-Run
  run?: RunId;          // bei mode = "run"
  input?: Record<string, Expr>;   // bei subflow: Übergabe aus dem Eltern-Run
  wait?: boolean;       // bei subflow: Eltern-Schritt kann erst abgeschickt werden,
                        // wenn der Kind-Run abgeschlossen ist
};
```

Damit gilt: Ein **Dokument enthält einen Workflow** (über den Block), und ein **Workflow besteht aus Dokumenten** (über die Schritte).

### 5.6 Verschachtelung und Zyklen

- Ein Kind-Run hat `parent`. Ist `wait: true`, werden die Buttons im Eltern-Schritt erst sichtbar, wenn der Kind-Run `completed` ist.
- Ergebnisse des Kind-Runs sind im Eltern-Run unter `run.children.<block_key>.steps…` lesbar.
- Der Antragsteller eines Kind-Runs ist der Antragsteller des Eltern-Runs. Er sieht Kind-Runs im Status seines Runs (5.10).
- **Zyklen** (Workflow A enthält in einem Schritt Workflow B, B enthält A) werden **beim Veröffentlichen** abgelehnt. Zur Laufzeit gibt es zusätzlich eine maximale Tiefe von 5.

### 5.7 Prüfung vor dem Veröffentlichen (`validate_workflow`)

Der Server liefert eine Liste verständlicher Fehler und Warnungen, damit ein Agent sie selbst beheben kann:

**Struktur**

- `start` zeigt auf keinen Schritt.
- Schritt `bestellung` ist von `start` aus nicht erreichbar.
- Von Schritt `genehmigung` führt kein Weg zu `end`.
- Button `approve` in Schritt `genehmigung` hat Outcome `approved`, aber es gibt keinen passenden Übergang.
- Schritt `erfassen` hat kein Formular mit Buttons, also kann der Run dort nie weiter.
- Zyklus über `wf_b`.

**Zuständigkeit**

- Schritt `genehmigung` hat keine `assignees`.
- Rolle `teamleitung` existiert nicht.
- Rolle `einkauf` hat aktuell keine Mitglieder (Warnung).
- Schritt `genehmigung` hat `exclude_starter`, aber einziger Zuständiger ist `starter`.
- `managers` ist leer, Aufgaben ohne auflösbare Zuständige hätten niemanden (Warnung).

**Daten**

- Action `items` schreibt in Spalte `col_x`, die es in `tbl_artikel` nicht gibt.
- Pflichtspalte `artikel.artikelname` wird von Action `items` nicht befüllt.
- Ausdruck `{{fields.kostenstele}}` verweist auf ein unbekanntes Feld (Tippfehler).
- `run.steps.bestellung` wird in Schritt `genehmigung` verwendet, aber `bestellung` liegt nicht auf jedem Weg davor.
- Schritt `erfassen` kann erneut besucht werden und enthält `create_row` (Warnung, siehe 5.4).

Dieselbe Prüfung für Formulare (ohne den Workflow-Teil) läuft bei jeder Änderung an einem `form`-Block und liefert Warnungen.

### 5.8 Nutzer, Rollen und Akteure

```ts
type User = {
  id: UserId;                 // aus dem Identity Provider
  name: string;
  email: string;
  roles: RoleId[];            // eine Person kann mehrere Rollen haben
  active: boolean;
};

type Role = {
  id: RoleId;
  key: string;                // "einkauf"
  name: string;               // "Einkauf"
};

type Agent = {
  id: AgentId;
  name: string;               // "Einkaufs-Assistent"
  roles: RoleId[];            // eigene Rollen, wenn der Agent selbst Aufgaben übernimmt
};

type Actor =
  | { type: "user";   id: UserId }
  | { type: "agent";  id: AgentId; on_behalf_of?: UserId }
  | { type: "system"; id: "workflow" | "scheduler" };
```

**Agenten handeln auf zwei Arten:**

| Art | Wer ist der Akteur | Welche Rechte und Rollen |
|---|---|---|
| **Im Auftrag einer Person** (`on_behalf_of`) | Agent, angemeldet mit dem Token der Person | die der Person. Erledigt z. B. „Genehmige alle offenen Bestellungen unter 100 €“ für die Teamleitung. |
| **Als eigener Akteur** | Agent mit eigener Identität | die eigenen Rollen des Agenten. Kann so selbst Zuständiger eines Schritts sein (über Rolle oder `{ kind: "user", user: "agt_…" }`). |

Im Verlauf eines Runs steht immer beides: „Genehmigt von Einkaufs-Assistent im Auftrag von Tom Teamleiter“.

Rollen werden **beim Handeln** geprüft, nicht beim Anlegen der Aufgabe. Wer heute die Rolle `einkauf` bekommt, sieht sofort alle offenen Einkaufs-Aufgaben. Wer sie verliert, sieht sie nicht mehr.

### 5.9 Aufgaben (Tasks)

Beim Betreten eines Schritts legt die Engine eine Aufgabe an:

```ts
type Task = {
  id: TaskId;
  run_id: RunId;
  step: string;
  status: "open" | "done" | "cancelled";
  candidates: { users: (UserId | AgentId)[]; roles: RoleId[] };
  excluded: (UserId | AgentId)[];     // aus exclude_starter / exclude_steps
  claimed_by?: Actor;                 // wer die Aufgabe übernommen hat
  created_at: string;
  due_at?: string;                    // aus step.due_in
  completed_by?: Actor;
  completed_at?: string;
  outcome?: string;
};
```

**Zuständige auflösen** (beim Anlegen):

```
für jeden Assignee des Schritts:
  starter → candidates.users += run.started_by
  user    → candidates.users += user
  role    → candidates.roles += role       // bleibt Rolle, wird nicht in Personen aufgelöst
  expr    → candidates.users += Ergebnis (eine oder mehrere IDs)

excluded = [run.started_by] falls exclude_starter
         + completed_by der Schritte in exclude_steps

keine Kandidaten übrig → candidates = definition.managers,
                         Event "unassigned" (Warnung an managers)
```

**Wer darf handeln:**

```
can_act(actor, task) =
     task.status = "open"
 UND actor ∉ task.excluded
 UND (actor ∈ task.candidates.users ODER actor.roles ∩ task.candidates.roles ≠ ∅)
 UND (task.claimed_by fehlt ODER task.claimed_by = actor)
```

Bei `on_behalf_of` wird die vertretene Person geprüft.

**Übernehmen (Claim):** Ist eine Aufgabe an eine Rolle gerichtet, können mehrere Personen sie sehen. Wer anfängt, kann sie mit `task.claim` übernehmen. Dann dürfen nur noch diese Person (und managers) handeln, die anderen sehen „In Bearbeitung von Tom“. `task.release` gibt sie wieder frei. Übernehmen ist optional: Ohne Claim darf jeder Kandidat direkt absenden, wer zuerst absendet, erledigt die Aufgabe.

**Umverteilen:** `task.reassign` ersetzt die Kandidaten, z. B. bei Urlaub. Erlaubt für managers. Event `reassigned` mit altem und neuem Stand.

**Frist:** Ist `due_at` überschritten, setzt der Scheduler ein Event `overdue` und benachrichtigt Kandidaten und managers. Die Aufgabe bleibt offen. Eskalationsregeln sind ein offener Punkt (12).

### 5.10 Status verfolgen

**Events.** Jede Zustandsänderung eines Runs wird als Event gespeichert. Daraus entsteht der Verlauf für den Antragsteller.

```ts
type RunEvent = {
  id: string;
  run_id: RunId;
  at: string;
  actor: Actor;
  type: "started" | "step_entered" | "task_claimed" | "task_released" | "reassigned"
      | "step_completed" | "overdue" | "unassigned" | "comment"
      | "subflow_started" | "subflow_completed" | "completed" | "cancelled";
  step?: string;
  outcome?: string;
  label?: string;                // Button-Label bei step_completed
  text?: string;                 // bei comment, cancelled (Begründung)
};
```

**Wer sieht einen Run:**

- der Antragsteller,
- alle, die in einem Schritt des Runs Kandidat sind oder waren,
- die managers des Workflows.

Im Kontext eines Runs dürfen diese Personen auch die `table_view`s der Schritt-Dokumente lesen, also z. B. die Artikel der eigenen Bestellung, ohne allgemeine Leserechte auf die Tabelle zu haben.

**Statusansicht eines Runs** (für Browser und `get_run` per MCP gleich):

```jsonc
{
  "id": "run_42",
  "title": "Bestellung KS 4711 – Anna Beispiel",
  "workflow": { "id": "wf_best", "name": "Bestellprozess", "version": 1 },
  "status": "active",
  "started_by": { "type": "user", "id": "usr_anna", "name": "Anna Beispiel" },
  "started_at": "2026-11-25T09:12:00Z",
  "current": {
    "step": "genehmigung",
    "label": "Wartet auf Genehmigung",
    "since": "2026-11-25T09:14:30Z",
    "candidates": { "users": [], "roles": [{ "key": "teamleitung", "name": "Teamleitung" }] },
    "claimed_by": null,
    "due_at": "2026-11-27T09:14:30Z"
  },
  "steps": [
    { "step": "erfassen",    "name": "Bestellung erfassen", "state": "done",
      "label": "Eingereicht", "by": "Anna Beispiel", "at": "2026-11-25T09:14:30Z" },
    { "step": "genehmigung", "name": "Genehmigung",          "state": "active" },
    { "step": "bestellung",  "name": "Bestellung auslösen",  "state": "pending" }
  ],
  "events": [ /* RunEvent[], neueste zuletzt */ ]
}
```

`steps` enthält die erledigten Schritte in Reihenfolge, den aktuellen Schritt und danach die noch nicht besuchten Schritte als `pending` in der Reihenfolge der Definition.

**Wo der Antragsteller den Status sieht:**

- **„Meine Anträge“:** alle Runs mit `started_by = ich`, mit Titel, Status, aktuellem `status_label`, Zuständigen und Ergebnis.
- **`workflow`-Block (`launcher`)** im Einstiegsdokument: dieselbe Liste für diesen Workflow.
- **Run-Ansicht:** Graph mit erledigten, aktuellem und offenen Schritten, Verlauf aus den Events, Schritt-Dokumente schreibgeschützt.
- **Live:** über den Kanal `run:<id>` und den persönlichen Kanal `user:<id>` (7.2).

**Benachrichtigungen** (Standard, ohne Konfiguration):

| Ereignis | Empfänger |
|---|---|
| `step_entered` | Kandidaten der neuen Aufgabe (bei Rollen: alle aktuellen Mitglieder) |
| `step_completed`, `completed`, `cancelled` | Antragsteller |
| `comment` | Antragsteller und Kandidaten der offenen Aufgabe |
| `overdue`, `unassigned` | Kandidaten und managers |

Benachrichtigungen landen im Kanal `user:<id>` und in der Aufgaben- bzw. Antragsliste. E-Mail ist ein zusätzlicher Zustellweg, die Logik bleibt gleich.

**Kommentare:** `run.comment` erlaubt Rückfragen am Run, z. B. „Brauchen wir wirklich 10 Stück?“. Kommentieren darf jeder, der den Run sieht.

---

## 6. Operationen: der einzige Schreibweg

Alle Änderungen, egal ob aus dem Browser, von einem Agenten über MCP oder von der Workflow-Engine, sind **Operationen**. Sie werden in Batches geschickt:

```ts
type OpBatch = {
  batch_id: string;                 // vom Client erzeugt, macht Wiederholungen ungefährlich
  base?: Record<EntityRef, number>; // optional: erwartete Versionen, z. B. { "blk_x": 4 }
  ops: Op[];
};
```

Der Akteur (`Actor`, 5.8) wird **nicht** mitgeschickt, sondern vom Server aus der Anmeldung bestimmt. Ein Batch wird **atomar** ausgeführt: ganz oder gar nicht.

### 6.1 Liste der Operationen

**Tabellen**

| Op | Parameter |
|---|---|
| `table.create` | `id, key, name, columns[]` |
| `table.update` | `table, name?, key?, display_column?` |
| `table.delete` | `table` |
| `column.add` | `table, column, after?` |
| `column.update` | `table, column, patch` |
| `column.move` | `table, column, after` |
| `column.delete` | `table, column` |
| `row.insert` | `table, rows[{ id, values, after? }]` |
| `row.update` | `table, row, values` (nur geänderte Spalten) |
| `row.move` | `table, row, after` |
| `row.delete` | `table, rows[]` |

**Dokumente**

| Op | Parameter |
|---|---|
| `doc.create` | `id, title, owner?, blocks?` (Baum, oder Markdown, siehe 8.2) |
| `doc.update` | `doc, title` |
| `doc.delete` | `doc` |
| `block.insert` | `doc, parent, after?, block` (darf Kinder enthalten) |
| `block.update` | `block, props` (flaches Merge pro Prop) |
| `block.move` | `block, parent, after?` |
| `block.delete` | `block` (inklusive aller Kinder) |
| `text.edit` | `block, from, to, insert, marks?` (Textänderung innerhalb eines Blocks) |

**Formulare**

| Op | Parameter |
|---|---|
| `draft.set` | `form_block, scope, key, value` |
| `draft.item_insert` | `form_block, scope, key, item, after?` |
| `draft.item_update` | `form_block, scope, key, item_id, values` |
| `draft.item_delete` | `form_block, scope, key, item_id` |
| `form.submit` | `submission_id, form_block, button, run?, values?` (`values` überschreibt den Entwurf, praktisch für Agenten) |

**Workflows, Runs und Aufgaben**

| Op | Parameter |
|---|---|
| `workflow.create` | `id, key, name, definition, description?`. Die Pipeline ergänzt ein `doc.create` für das Übersichtsdokument (`doc_ov_<…>`, Titel = Name, `owner = { workflow, step: null }`, Absatz mit `description` + `workflow`-Block), außer der Batch legt selbst eines an. Home zeigt die Schritt-Dokumente aufklappbar darunter. |
| `workflow.update` | `workflow, definition` (nur der Entwurf) |
| `workflow.publish` | `workflow` → prüft (5.7) und legt Version an |
| `workflow.delete` | `workflow` (nur ohne aktive Runs). Die Pipeline löscht vorher das Übersichtsdokument mit. |
| `run.start` | `id, workflow, input?` |
| `run.cancel` | `run, reason?` |
| `run.comment` | `run, text` |
| `task.claim` | `task` |
| `task.release` | `task` |
| `task.reassign` | `task, assignees[]` |

**Import** (Details in 8.3)

| Op | Parameter |
|---|---|
| `import.include` | `import_id` (Verweis auf einen vorbereiteten Import, wird vom Server durch dessen Ops ersetzt) |

**Nutzer und Rollen** (Recht „Workspace verwalten“)

| Op | Parameter |
|---|---|
| `role.create` | `id, key, name` |
| `role.update` | `role, key?, name?` |
| `role.delete` | `role` (nur wenn nirgends verwendet, siehe 9) |
| `user.set_roles` | `user, add?: RoleId[], remove?: RoleId[]` |
| `agent.set_roles` | `agent, add?, remove?` |

Runs, Aufgaben und Events werden **nur** über diese Ops und `form.submit` verändert, nie direkt. Die Engine erzeugt die Folge-Änderungen (Aufgabe anlegen, Events) im selben Batch.

### 6.2 Was der Server mit einem Batch macht

```
1. Akteur aus der Anmeldung bestimmen
2. Rechte prüfen (pro Op)
3. `import.include` durch die gespeicherten Ops ersetzen, dann Keys in IDs auflösen
4. base-Versionen prüfen, falls angegeben → sonst CONFLICT mit aktuellem Stand
5. Ops validieren und anwenden (eine DB-Transaktion), inkl. Folge-Änderungen der Engine
6. Versionen der betroffenen Objekte erhöhen
7. Referenz-Index aktualisieren (siehe 9)
8. Batch ins Operations-Log schreiben, inkl. inverser Ops für Undo
9. An alle betroffenen WebSocket-Kanäle verteilen, Benachrichtigungen erzeugen
10. Antwort: { batch_id, seq, results }
```

---

## 7. Echtzeit über WebSockets

### 7.1 Grundprinzip

- **Der Server ist die einzige Quelle der Wahrheit.** Es gibt kein CRDT. Clients wenden ihre eigenen Änderungen sofort lokal an (optimistisch) und gleichen sie mit dem ab, was der Server bestätigt.
- **Agenten sind normale Teilnehmer.** Eine MCP-Operation geht durch denselben Ablauf wie ein Tastendruck im Browser. Alle offenen Browser sehen sie sofort, gekennzeichnet mit dem Agenten als Autor.
- Weil die Operationen **fachlich und kleinteilig** sind (eine Zelle, ein Block, ein Formularfeld), gibt es kaum echte Konflikte.

### 7.2 Kanäle

| Kanal | Enthält |
|---|---|
| `doc:<id>` | Blöcke des Dokuments, Präsenz |
| `table:<id>` | Schema und Zeilen (Clients abonnieren auch alle Tabellen, die ihr Dokument anzeigt) |
| `run:<id>` | Run-Status, Aufgabe, Events, Entwürfe der Formulare im Run, Präsenz |
| `user:<id>` | persönliche Aufgabenliste, eigene Anträge (Statusänderungen), Benachrichtigungen |
| `workspace` | Liste von Dokumenten, Tabellen, Workflows, Rollen (anlegen, umbenennen, löschen) |

Jeder Kanal hat eine eigene, lückenlos steigende Nummer `seq`.

Aufgaben an Rollen erscheinen im Kanal `user:<id>` **aller** aktuellen Mitglieder der Rolle. Ändern sich die Rollen einer Person, schickt der Server ihr die neue Aufgabenliste als Snapshot.

### 7.3 Nachrichten

```jsonc
// Client → Server
{ "type": "subscribe",   "channel": "doc:doc_1", "since": 118 }   // since fehlt → Snapshot
{ "type": "unsubscribe", "channel": "doc:doc_1" }
{ "type": "ops",         "batch": { /* OpBatch */ } }
{ "type": "presence",    "channel": "doc:doc_1", "state": { "cursor": { "block": "blk_7", "offset": 12 }, "editing": "blk_7" } }

// Server → Client
{ "type": "snapshot", "channel": "doc:doc_1", "seq": 120, "data": { /* … */ } }
{ "type": "ops",      "channel": "doc:doc_1", "seq": 121, "batch_id": "…", "actor": { … }, "ops": [ … ] }
{ "type": "ack",      "batch_id": "…", "seq": { "doc:doc_1": 121 }, "results": { … } }
{ "type": "reject",   "batch_id": "…", "error": { "code": "CONFLICT", "message": "…", "details": { … } } }
{ "type": "presence", "channel": "doc:doc_1", "actors": [ { "actor": { … }, "state": { … } } ] }
```

- **Wiederverbinden:** Der Client schickt `subscribe` mit der letzten bekannten `seq`. Der Server schickt die fehlenden Ops aus dem Log. Liegt die Lücke zu weit zurück, schickt er einen neuen Snapshot.
- Ein Batch, der mehrere Kanäle betrifft (z. B. `form.submit` schreibt in zwei Tabellen, ändert den Run und die Aufgabenlisten), wird in jedem Kanal mit derselben `batch_id` verteilt.
- Jeder Client sieht nur Kanäle, für die er Leserechte hat. Bei `subscribe` wird geprüft, bei Rechteänderungen werden Abos beendet.

### 7.4 Optimistisches Anwenden im Client

```
Client-Zustand = bestätigter Server-Stand + Liste ausstehender eigener Batches

eigene Änderung   → Batch lokal anwenden, an Liste anhängen, senden
fremde Ops        → ausstehende zurücknehmen, fremde anwenden, ausstehende erneut anwenden
ack               → Batch aus der Liste entfernen (ist jetzt Teil des Server-Stands)
reject            → Batch verwerfen, Zustand neu berechnen, Hinweis anzeigen
```

`form.submit`, `run.start` und `task.*` werden **nicht** optimistisch angewendet, weil die Folgen (Übergang, neue Aufgabe) erst der Server kennt. Der Button zeigt bis zum `ack` einen Ladezustand.

### 7.5 Konfliktregeln

| Situation | Regel |
|---|---|
| Zwei ändern verschiedene Zellen derselben Zeile | beide gewinnen (Merge pro Spalte) |
| Zwei ändern dieselbe Zelle | die zuletzt am Server angekommene gewinnt |
| Zwei ändern verschiedene Props eines Blocks | beide gewinnen (Merge pro Prop) |
| Zwei tippen im selben Textblock | `text.edit` mit Positionen; der Server verschiebt Positionen anhand der zwischenzeitlich angewendeten Edits desselben Blocks (einfache Operational Transformation auf einem einzelnen String) |
| Zwei Kandidaten senden dieselbe Aufgabe ab | der erste gewinnt, der zweite bekommt `TASK_DONE` mit Name und Ergebnis |
| Zwei übernehmen dieselbe Aufgabe | der erste gewinnt, der zweite bekommt `TASK_CLAIMED` |
| Änderung an gelöschtem Block / gelöschter Zeile | wird abgelehnt (`NOT_FOUND`) |
| Agent schickt `base`-Version, die veraltet ist | `CONFLICT` mit aktuellem Stand, Agent liest neu und versucht erneut |

**Präsenz als Schutz für Agenten:** Wer einen Textblock gerade bearbeitet, meldet `editing: blk_x`. Schreibt ein Agent auf diesen Block, bekommt er `BLOCK_IN_USE` mit dem Namen der Person zurück und kann später erneut versuchen oder einen anderen Block wählen. Die Markierung verfällt nach 30 Sekunden ohne Eingabe. So überschreiben Agenten nie Text, an dem gerade ein Mensch tippt.

### 7.6 Formularentwürfe live

Jede Eingabe in ein Feld ist eine `draft.set`-Op im Kanal `run:<id>`. Mehrere Personen im selben Run sehen also live, was die anderen eintragen. Bei `line_items` hat jede Zeile eine eigene ID, gleichzeitiges Hinzufügen funktioniert daher ohne Konflikt.

---

## 8. MCP

### 8.1 Tools

Der MCP-Server ist eine dünne Schicht über den Operationen aus Abschnitt 6. Alle Tools akzeptieren IDs oder Keys. Rechte und Zuständigkeiten gelten genauso wie im Browser (5.8).

| Bereich | Tool | Entspricht |
|---|---|---|
| Finden | `search(query, kinds?)` | Volltext- und Vektorsuche über Dokumente, Tabellen, Workflows |
| Tabellen | `list_tables`, `get_table(table)` | Schema |
| | `query_rows(table, filter?, sort?, limit?)` | Zeilen lesen |
| | `create_table`, `update_table`, `add_column`, `update_column`, `delete_column` | Schema-Ops |
| | `insert_rows`, `update_row`, `delete_rows` | Zeilen-Ops |
| Dokumente | `get_document(doc, format = "md" \| "json", run?)` | Markdown mit Block-IDs oder Blockliste, optional im Kontext eines Runs ausgewertet |
| | `create_document(title, markdown \| blocks)` | `doc.create` |
| | `edit_document(doc, ops[], base_version?)` | `block.*`, `text.edit` |
| Import | `import_xlsx(file, sheet?, apply?)`, `import_docx(file, title?, owner?, bind_table?, apply?)` | 8.3 |
| Formulare | `validate_form(doc, block)` | Prüfung aus 5.7 |
| Workflows | `list_workflows`, `get_workflow`, `create_workflow`, `update_workflow` | Definition |
| | `validate_workflow(workflow)` | 5.7 |
| | `publish_workflow(workflow)` | `workflow.publish` |
| | `delete_workflow(workflow, delete_documents=true)` | `workflow.delete` + `doc.delete` der Schritt-Dokumente mit `owner.workflow` (Übersichtsdokument löscht die Pipeline) |
| Runs | `start_run(workflow, input?)` | `run.start` |
| | `list_runs(workflow?, started_by? = "me", status?)` | „Meine Anträge“ und Übersicht |
| | `get_run(run)` | Statusansicht aus 5.10 inkl. Events |
| | `cancel_run(run, reason?)`, `comment_run(run, text)` | `run.cancel`, `run.comment` |
| Aufgaben | `list_tasks(assigned_to? = "me", status? = "open", workflow?)` | Aufgabenliste |
| | `get_task(task)` | Aufgabe mit Schritt-Dokument im Run-Kontext, verfügbaren Buttons und Feldern |
| | `claim_task`, `release_task`, `reassign_task` | `task.*` |
| | `complete_task(task, button, values)` | `form.submit` für das Formular des Schritts |
| Rollen | `list_roles`, `list_users(role?)` | Lesen |
| | `create_role`, `set_user_roles`, `set_agent_roles` | `role.*`, `user.set_roles` |
| Allgemein | `apply_ops(batch)` | beliebiger Batch, für zusammenhängende Änderungen |

- `apply_ops` ist wichtig: Ein Agent legt damit Rollen, Tabellen, Dokumente und Workflow **in einem atomaren Batch** an. Entweder klappt alles oder nichts.
- `get_task` liefert alles, was ein Agent zum Erledigen braucht: welche Buttons es gibt, welche Felder Pflicht sind (inkl. `require` pro Button) und welche Daten im Schritt-Dokument stehen. `complete_task` schickt dann Button und Werte in einem Aufruf.

### 8.2 Markdown-Darstellung für Agenten

`get_document(format = "md")` liefert Markdown mit Block-IDs. `create_document` akzeptiert dieselbe Syntax. Der Server parst sie in Blöcke.

```markdown
# Bestellung erfassen {#blk_h1}

Bitte Name, Kostenstelle und die benötigten Artikel angeben. {#blk_p1}

:::form{#blk_form}
::field{#blk_name key=name label="Name" column=bestellungen.name}
::field{#blk_ks key=kostenstelle label="Kostenstelle" column=bestellungen.kostenstelle}
::line_items{#blk_items key=artikel label="Artikel" columns="artikelname,preis,artikelnummer,anzahl" from=artikel}
:::
```

Actions und Buttons eines Formulars stehen nicht im Markdown, sondern in der JSON-Darstellung (`get_document(format = "json")`) bzw. werden mit `block.update` gesetzt. Markdown bleibt so lesbar.

### 8.3 Import von Excel und Word

Anna hat meist schon eine Excel-Übersicht und ein Word-Formular. Statt alles neu zu beschreiben, übergibt sie die Dateien, der Server macht daraus Operationen, und der Agent ergänzt, was in den Dateien nicht stehen kann (Aktionen, Buttons, Workflow).

**Ablauf (für Browser und Agent gleich):**

```
1. Datei hochladen (import_xlsx / import_docx)
2. Server liest die Datei und bereitet einen Import vor:
   → erzeugt die Ops (table.create + row.insert bzw. doc.create mit Blöcken),
     vergibt dafür IDs und speichert sie unter import_id (1 Stunde gültig)
   → schreibt noch nichts in den Workspace
3. Antwort: { import_id, created, warnings }
   created = IDs und Keys dessen, was angelegt würde (Tabellen, Spalten, Dokument, Formular, Felder)
4. Der Aufrufer nimmt den Import in einen Batch auf:
   { "op": "import.include", "import_id": "imp_…" }
   und ergänzt in demselben Batch Ops, die auf die IDs aus created verweisen
   (Aktionen, Buttons, Workflow, Spaltentypen). Mit apply = true wird der Import ohne Ergänzung sofort ausgeführt.
```

Der Import ist so Teil **eines** atomaren Batches. Entweder entsteht alles (Tabelle, Dokument, Workflow) oder nichts. Ausnahme zur Regel „Client erzeugt IDs“ (1): Hier vergibt der Server die IDs, weil der Client die Dateistruktur vorher nicht kennt. Sie stehen im Ergebnis.

**Excel (`.xlsx`) → Tabelle**

- Jedes Blatt wird eine Tabelle. Mit `sheet` lässt sich ein Blatt auswählen. Blattname → `key` und `name`.
- Erste Zeile = Spaltennamen. Leere Spaltenköpfe und komplett leere Zeilen werden übersprungen (Warnung).
- Der **Spaltentyp wird aus den Werten abgeleitet**: nur ganze Zahlen → `integer`, Zahlen mit Nachkommastellen → `number`, Währungsformat → `currency`, Datum → `date`/`datetime`, Wahrheitswerte → `boolean`, sonst `text` (lange Texte → `long_text`). Gemischte Spalten werden `text` (Warnung). Spalten mit nur wenigen verschiedenen Werten bleiben `text`, der Aufrufer kann sie zu `select` machen.
- Formeln werden durch ihren zuletzt berechneten Wert ersetzt (Warnung: „Formel verloren“). Es gibt keine Formeln in Tabellen (11).
- Jede Zeile wird eine Zeile in der Tabelle, in der Reihenfolge der Datei. Die erste Spalte wird `display_column`.
- Fehlen Spalten, die der Prozess braucht (z. B. `Status`), legt der Aufrufer sie im selben Batch mit `column.add` an. Der Import erfindet keine.

**Word (`.docx`) → Dokument mit Formular**

| Inhalt in Word | Ergebnis |
|---|---|
| Überschrift 1–3 | `heading` |
| Absatz (mit fett, kursiv, Links) | `paragraph` mit `Inline`-Marks |
| Aufzählung, Nummerierung | `list` und `list_item` |
| Zeile der Form „Bezeichnung: ____“, „Bezeichnung: …….“ oder „Bezeichnung: [ ]“ | `field` mit `label` = Bezeichnung und `key` aus dem Label |
| Kontrollkästchen „☐ Text“ | `field` vom Typ `boolean` |
| Tabelle, deren Zeilen unter dem Kopf leer sind | `line_items` mit den Kopfzeilen als Spalten |
| Tabelle mit ausgefüllten Zeilen | eigene Tabelle (wie bei Excel) und ein `table_view` darauf |
| Bilder, Kopf-/Fußzeilen, Kommentare | werden ausgelassen (Warnung) |

- Alle erkannten Felder und Zeilenlisten kommen in **einen** `form`-Block, an der Stelle des ersten Feldes. Text davor und danach bleibt als normale Blöcke erhalten.
- **Feldtypen** werden aus dem Label abgeleitet: „Datum“, „am“ → `date`; „Menge“, „Anzahl“ → `integer`; „Preis“, „Betrag“, „Summe“ → `currency`; sonst `text`. Pflichtfelder erkennt der Import an einem Stern im Label (`Name*`).
- `title` überschreibt den Dokumenttitel (sonst Dateiname oder erste Überschrift). `owner` macht das Dokument gleich zum Schritt-Dokument eines Workflows (`{ workflow, step }`).
- Das Formular hat **keine Actions und keine Buttons**. Damit nichts unbemerkt verloren geht, warnt der Import: „Formular schreibt nirgends hin“ (siehe 4.3).
- **Abkürzung `bind_table`:** Wird eine Tabelle genannt (auch eine aus demselben Import), bindet der Import Felder, deren Label zu einem Spaltennamen passt (Groß-/Kleinschreibung egal), über `column` und erzeugt eine Action `create_row` mit einem Button „Speichern“. Nicht zuordenbare Felder stehen in den Warnungen.

**Warnungen** sind Texte, die ein Agent lesen und beheben kann, z. B. „Blatt ‚Tabelle2‘ ist leer“, „Spalte C: gemischte Werte, als text angelegt“, „Feld ‚Datum‘ ohne Typ erkannt, als text angelegt“. Dateien, die sich nicht lesen lassen (kein gültiges xlsx/docx, passwortgeschützt, zu groß), werden mit einem Fehler abgelehnt. Das Limit steht in `technische-umsetzung.md`.

**Rechte:** Wer den Import in einen Batch aufnimmt, braucht die Rechte für alle enthaltenen Ops (Tabellen anlegen, Dokumente anlegen). Der Import selbst prüft nichts außer dem Dateiinhalt.

---

## 9. Referenz-Index und Integrität

Der Server pflegt bei jeder Op einen Index aller Verweise:

```ts
type Reference = {
  source: { kind: "block" | "column" | "workflow"; id: string };
  target: { kind: "table" | "column" | "document" | "workflow" | "row" | "role" | "user"; id: string };
  via: "table_view" | "field.column" | "action.table" | "action.value" | "filter"
     | "mention" | "reference_column" | "step.document" | "step.assignee"
     | "workflow.starters" | "workflow.managers" | "workflow_block";
};
```

Er liefert:

- **Löschschutz:** `column.delete` auf `artikel.preis` → `IN_USE: verwendet von Formular blk_form (Action items), Ansicht blk_tv2`. Ebenso `role.delete` auf `einkauf` → `IN_USE: Bestellprozess, Schritt bestellung`.
- **Backlinks:** „Wo wird die Tabelle Bestellungen verwendet?“
- **Zyklenerkennung** für Workflows.
- **Abonnements:** Welche `table:`-Kanäle ein Client für ein Dokument braucht.

Workflow-Versionen verweisen auf ihre eingefrorenen Dokumente, nicht auf die aktuellen. Eine Spalte oder Rolle, die nur noch von einer alten Version verwendet wird, kann trotzdem nicht gelöscht werden, solange es aktive Runs dieser Version gibt.

Wird ein Nutzer deaktiviert, der Kandidat offener Aufgaben ist, bekommen die managers ein Event `unassigned` für jede Aufgabe, bei der dadurch kein Kandidat mehr übrig ist.

---

## 10. Vollständiges Beispiel: Bestellprozess

Ablauf:

```
erfassen ──submitted──► genehmigung ──approved──► bestellung ──ordered──► Ende (Bestellt)
(Antragsteller)          (Teamleitung,  │           (Einkauf)
                          nicht der     └─rejected──────────────────────► Ende (Abgelehnt)
                          Antragsteller)
```

| Schritt | Zuständig | Was passiert | Status der Bestellung |
|---|---|---|---|
| `erfassen` | Antragsteller | Name, Kostenstelle, Artikel eingeben | `eingereicht` |
| `genehmigung` | Rolle `teamleitung`, nicht der Antragsteller | genehmigen oder mit Begründung ablehnen | `genehmigt` / `abgelehnt` |
| `bestellung` | Rolle `einkauf` | Bestellung beim Lieferanten auslösen, Bestellnummer und Liefertermin eintragen | `bestellt` |

### 10.1 Was der Agent per MCP anlegt

Der Agent prüft zuerst mit `list_roles`, welche Rollen es gibt, und schickt dann einen einzigen `apply_ops`-Aufruf:

```jsonc
{
  "batch_id": "b_01JDAGENT0001",
  "ops": [
    // ── Rollen (nur falls noch nicht vorhanden) ─────────────────────────
    { "op": "role.create", "id": "rol_tl", "key": "teamleitung", "name": "Teamleitung" },
    { "op": "role.create", "id": "rol_ek", "key": "einkauf",     "name": "Einkauf" },

    // ── Tabelle Bestellungen ────────────────────────────────────────────
    { "op": "table.create", "id": "tbl_best", "key": "bestellungen", "name": "Bestellungen",
      "columns": [
        { "id": "col_b_name",   "key": "name",         "name": "Name",         "type": { "kind": "text" }, "required": true },
        { "id": "col_b_ks",     "key": "kostenstelle", "name": "Kostenstelle", "type": { "kind": "text" }, "required": true },
        { "id": "col_b_status", "key": "status",       "name": "Status",
          "type": { "kind": "select", "options": [
            { "id": "eingereicht", "label": "Eingereicht" },
            { "id": "genehmigt",   "label": "Genehmigt" },
            { "id": "abgelehnt",   "label": "Abgelehnt" },
            { "id": "bestellt",    "label": "Bestellt" } ] },
          "default": "eingereicht" },
        { "id": "col_b_by",     "key": "besteller",       "name": "Besteller",        "type": { "kind": "user" }, "default": "{{user.id}}" },
        { "id": "col_b_gen",    "key": "genehmigt_von",   "name": "Genehmigt von",    "type": { "kind": "user" } },
        { "id": "col_b_komm",   "key": "kommentar",       "name": "Kommentar",        "type": { "kind": "long_text" } },
        { "id": "col_b_lnr",    "key": "lieferanten_nr",  "name": "Bestellnr. Lieferant", "type": { "kind": "text" } },
        { "id": "col_b_lt",     "key": "liefertermin",    "name": "Liefertermin",     "type": { "kind": "date" } },
        { "id": "col_b_run",    "key": "run",             "name": "Vorgang",          "type": { "kind": "text" } }
      ],
      "display_column": "col_b_name" },

    // ── Tabelle Artikel ─────────────────────────────────────────────────
    { "op": "table.create", "id": "tbl_art", "key": "artikel", "name": "Artikel",
      "columns": [
        { "id": "col_a_name",  "key": "artikelname",   "name": "Artikelname",   "type": { "kind": "text" }, "required": true },
        { "id": "col_a_preis", "key": "preis",         "name": "Preis",         "type": { "kind": "currency", "currency": "EUR" }, "required": true },
        { "id": "col_a_nr",    "key": "artikelnummer", "name": "Artikelnummer", "type": { "kind": "text" } },
        { "id": "col_a_anz",   "key": "anzahl",        "name": "Anzahl",        "type": { "kind": "integer", "min": 1 }, "required": true },
        { "id": "col_a_best",  "key": "bestellung",    "name": "Bestellung",
          "type": { "kind": "reference", "table": "tbl_best", "on_delete": "cascade" }, "required": true }
      ],
      "display_column": "col_a_name" },

    // ── Workflow (Entwurf) ──────────────────────────────────────────────
    { "op": "workflow.create", "id": "wf_best", "key": "bestellprozess", "name": "Bestellprozess",
      "definition": {
        "start": "erfassen",
        "starters": [],
        "managers": [{ "kind": "role", "role": "rol_ek" }],
        "run_title": "{{concat(\"Bestellung KS \", coalesce(run.steps.erfassen.values.kostenstelle, \"…\"), \" – \", run.starter.name)}}",
        "steps": [
          { "key": "erfassen", "name": "Bestellung erfassen", "status_label": "In Erfassung",
            "document": "doc_s1",
            "assignees": [{ "kind": "starter" }] },
          { "key": "genehmigung", "name": "Genehmigung", "status_label": "Wartet auf Genehmigung",
            "document": "doc_s2",
            "assignees": [{ "kind": "role", "role": "rol_tl" }],
            "exclude_starter": true,
            "due_in": "P2D" },
          { "key": "bestellung", "name": "Bestellung auslösen", "status_label": "Wird vom Einkauf bestellt",
            "document": "doc_s3",
            "assignees": [{ "kind": "role", "role": "rol_ek" }],
            "due_in": "P3D" }
        ],
        "transitions": [
          { "from": "erfassen",    "on": "submitted", "to": "genehmigung" },
          { "from": "genehmigung", "on": "approved",  "to": "bestellung" },
          { "from": "genehmigung", "on": "rejected",  "to": "end" },
          { "from": "bestellung",  "on": "ordered",   "to": "end" }
        ]
      } },

    // ── Schritt 1: Bestellung erfassen ──────────────────────────────────
    { "op": "doc.create", "id": "doc_s1", "title": "Bestellung erfassen",
      "owner": { "workflow": "wf_best", "step": "erfassen" },
      "blocks": [
        { "id": "blk_s1_h", "type": "heading", "props": { "level": 1, "content": [{ "t": "text", "text": "Bestellung erfassen" }] } },
        { "id": "blk_s1_p", "type": "paragraph", "props": { "content": [{ "t": "text", "text": "Bitte Name, Kostenstelle und die benötigten Artikel angeben." }] } },
        { "id": "blk_s1_form", "type": "form",
          "props": {
            "actions": [
              { "key": "order", "type": "create_row", "table": "tbl_best",
                "values": {
                  "col_b_name":   "{{fields.name}}",
                  "col_b_ks":     "{{fields.kostenstelle}}",
                  "col_b_status": "eingereicht",
                  "col_b_run":    "{{run.id}}"
                } },
              { "key": "items", "type": "create_rows", "table": "tbl_art",
                "for_each": "{{fields.artikel}}",
                "values": {
                  "col_a_name":  "{{item.artikelname}}",
                  "col_a_preis": "{{item.preis}}",
                  "col_a_nr":    "{{item.artikelnummer}}",
                  "col_a_anz":   "{{item.anzahl}}",
                  "col_a_best":  "{{results.order.id}}"
                } }
            ],
            "buttons": [
              { "id": "submit", "label": "Einreichen", "style": "primary",
                "actions": ["order", "items"], "outcome": "submitted" }
            ]
          },
          "children": [
            { "id": "blk_s1_name", "type": "field", "props": { "key": "name", "label": "Name", "column": "col_b_name", "default": "{{user.name}}" } },
            { "id": "blk_s1_ks",   "type": "field", "props": { "key": "kostenstelle", "label": "Kostenstelle", "column": "col_b_ks" } },
            { "id": "blk_s1_items", "type": "line_items",
              "props": { "key": "artikel", "label": "Artikel", "min_rows": 1,
                "columns": [
                  { "key": "artikelname",   "column": "col_a_name" },
                  { "key": "preis",         "column": "col_a_preis" },
                  { "key": "artikelnummer", "column": "col_a_nr" },
                  { "key": "anzahl",        "column": "col_a_anz" }
                ] } }
          ] }
      ] },

    // ── Schritt 2: Genehmigung durch Teamleitung ────────────────────────
    { "op": "doc.create", "id": "doc_s2", "title": "Genehmigung",
      "owner": { "workflow": "wf_best", "step": "genehmigung" },
      "blocks": [
        { "id": "blk_s2_h", "type": "heading", "props": { "level": 1, "content": [{ "t": "text", "text": "Genehmigung" }] } },
        { "id": "blk_s2_p", "type": "paragraph", "props": { "content": [
            { "t": "text", "text": "Bestellung von " },
            { "t": "value", "expr": "{{run.steps.erfassen.values.name}}" },
            { "t": "text", "text": " für Kostenstelle " },
            { "t": "value", "expr": "{{run.steps.erfassen.values.kostenstelle}}" },
            { "t": "text", "text": ", Summe: " },
            { "t": "value", "expr": "{{sum(run.steps.erfassen.values.artikel, \"preis\")}}" }
        ] } },
        { "id": "blk_s2_tv", "type": "table_view", "props": {
            "table": "tbl_art",
            "columns": ["col_a_name", "col_a_nr", "col_a_anz", "col_a_preis"],
            "filter": [{ "column": "col_a_best", "op": "eq", "value": "{{run.steps.erfassen.results.order.id}}" }],
            "editable": false, "allow_add": false, "allow_delete": false } },
        { "id": "blk_s2_form", "type": "form",
          "props": {
            "actions": [
              { "key": "approve", "type": "update_row", "table": "tbl_best",
                "row": "{{run.steps.erfassen.results.order.id}}",
                "values": { "col_b_status": "genehmigt", "col_b_gen": "{{user.id}}", "col_b_komm": "{{fields.kommentar}}" } },
              { "key": "reject", "type": "update_row", "table": "tbl_best",
                "row": "{{run.steps.erfassen.results.order.id}}",
                "values": { "col_b_status": "abgelehnt", "col_b_komm": "{{fields.kommentar}}" } }
            ],
            "buttons": [
              { "id": "approve", "label": "Genehmigen", "style": "primary",
                "actions": ["approve"], "outcome": "approved" },
              { "id": "reject",  "label": "Ablehnen", "style": "danger",
                "actions": ["reject"], "outcome": "rejected",
                "require": ["kommentar"], "confirm": "Bestellung wirklich ablehnen?" }
            ]
          },
          "children": [
            { "id": "blk_s2_komm", "type": "field", "props": { "key": "kommentar", "label": "Kommentar", "input": "textarea" } }
          ] }
      ] },

    // ── Schritt 3: Bestellung durch Einkauf ─────────────────────────────
    { "op": "doc.create", "id": "doc_s3", "title": "Bestellung auslösen",
      "owner": { "workflow": "wf_best", "step": "bestellung" },
      "blocks": [
        { "id": "blk_s3_h", "type": "heading", "props": { "level": 1, "content": [{ "t": "text", "text": "Bestellung auslösen" }] } },
        { "id": "blk_s3_p", "type": "paragraph", "props": { "content": [
            { "t": "text", "text": "Genehmigt von " },
            { "t": "value", "expr": "{{run.steps.genehmigung.completed_by.name}}" },
            { "t": "text", "text": ". Bitte beim Lieferanten bestellen und anschließend Bestellnummer und Liefertermin eintragen." }
        ] } },
        { "id": "blk_s3_tv", "type": "table_view", "props": {
            "table": "tbl_art",
            "columns": ["col_a_name", "col_a_nr", "col_a_anz", "col_a_preis"],
            "filter": [{ "column": "col_a_best", "op": "eq", "value": "{{run.steps.erfassen.results.order.id}}" }],
            "editable": false } },
        { "id": "blk_s3_form", "type": "form",
          "props": {
            "actions": [
              { "key": "ordered", "type": "update_row", "table": "tbl_best",
                "row": "{{run.steps.erfassen.results.order.id}}",
                "values": { "col_b_status": "bestellt", "col_b_lnr": "{{fields.lieferanten_nr}}", "col_b_lt": "{{fields.liefertermin}}" } }
            ],
            "buttons": [
              { "id": "ordered", "label": "Bestellung abschließen", "style": "primary",
                "actions": ["ordered"], "outcome": "ordered" }
            ]
          },
          "children": [
            { "id": "blk_s3_lnr", "type": "field", "props": { "key": "lieferanten_nr", "label": "Bestellnummer Lieferant", "column": "col_b_lnr", "required": true } },
            { "id": "blk_s3_lt",  "type": "field", "props": { "key": "liefertermin",   "label": "Liefertermin",            "column": "col_b_lt" } }
          ] }
      ] },

    // ── Einstiegsdokument mit Startknopf und eigenen Anträgen ───────────
    { "op": "doc.create", "id": "doc_einkauf", "title": "Einkauf",
      "blocks": [
        { "id": "blk_e_h", "type": "heading", "props": { "level": 1, "content": [{ "t": "text", "text": "Einkauf" }] } },
        { "id": "blk_e_p", "type": "paragraph", "props": { "content": [{ "t": "text", "text": "Hier neue Bestellungen starten und den Stand der eigenen Bestellungen verfolgen." }] } },
        { "id": "blk_e_wf", "type": "workflow", "props": { "workflow": "wf_best", "mode": "launcher" } }
      ] },

    // ── Prüfen und veröffentlichen ──────────────────────────────────────
    { "op": "workflow.publish", "workflow": "wf_best" }
  ]
}
```

Hinweise:

- Alle Buttons sind als Aufforderung formuliert („Einreichen“, „Genehmigen“, „Ablehnen“, „Bestellung abschließen“). Als Status und im Verlauf zeigt das Frontend das Ergebnis: Bekannte Outcomes (`approved`, `rejected`, `ordered`, `submitted`, …) erscheinen als „Genehmigt“, „Abgelehnt“, „Bestellt“, „Eingereicht“, sonst das Button-Label (`resultLabel` in `frontend/src/inbox/inboxModel.ts`). `run.result.label` bleibt das Button-Label.
- Soll statt einer Rolle eine **bestimmte Person** genehmigen, ersetzt man den Assignee durch `{ "kind": "user", "user": "usr_tom" }`. Soll der **Verantwortliche der Kostenstelle** genehmigen, gibt es eine Tabelle `kostenstellen` mit einer Spalte `verantwortlich` (Typ `user`) und den Assignee `{ "kind": "expr", "expr": "{{lookup(\"kostenstellen\", \"nummer\", run.steps.erfassen.values.kostenstelle, \"verantwortlich\")}}" }`.
- Statt Tabelle `bestellungen` und Schritt-Dokument 1 von Hand zu beschreiben, kann der Agent sie aus der bestehenden Excel-Übersicht und dem Word-Formular importieren (8.3). Er nimmt beide Importe mit `import.include` in denselben Batch auf und ergänzt Actions, Buttons, Workflow und die übrigen Schritt-Dokumente.
- Das Formular in Schritt 2 hat ein optionales Kommentarfeld, das nur beim Ablehnen Pflicht ist (`require`).

### 10.2 Was zur Laufzeit passiert

```
1. Anna öffnet "Einkauf" und klickt im Workflow-Block auf "Starten"
   → run.start { id: run_42, workflow: wf_best }
   → Run v1, Aufgabe tsk_1 (erfassen, Kandidat: Anna), Event started, step_entered

2. Anna füllt doc_s1 aus und klickt "Einreichen"
   → Transaktion:
       order: row.insert tbl_best { name, kostenstelle, status: eingereicht, besteller: Anna, run: run_42 } → row_B1
       items: row.insert tbl_art  { …, bestellung: row_B1 } × Anzahl Artikel
   → tsk_1 done, run.steps.erfassen gespeichert
   → Übergang submitted → genehmigung
   → Aufgabe tsk_2 (genehmigung, Kandidaten: Rolle teamleitung, ausgeschlossen: Anna, fällig in 2 Tagen)
   → run.title = "Bestellung KS 4711 – Anna Beispiel"
   → WebSocket:
       user:<jedes Mitglied von teamleitung>  neue Aufgabe
       user:usr_anna                          Status "Wartet auf Genehmigung"
       table:tbl_best, table:tbl_art           neue Zeilen

   Ist Anna selbst Teamleitung, sieht sie tsk_2 nicht als Aufgabe (exclude_starter).

3. Tom (Rolle teamleitung) öffnet seine Aufgabenliste, klickt tsk_2 an und übernimmt sie
   → task.claim → andere Teamleiter sehen "In Bearbeitung von Tom"
   → Anna sieht im Verlauf: "Tom Teamleiter bearbeitet die Genehmigung"

4. Tom klickt "Genehmigen"
   → update_row row_B1 { status: genehmigt, genehmigt_von: Tom }
   → Übergang approved → bestellung, Aufgabe tsk_3 an Rolle einkauf (fällig in 3 Tagen)
   → Anna: "Genehmigt von Tom Teamleiter", jetzt "Wird vom Einkauf bestellt"

   Alternativ "Ablehnen": Kommentar ist Pflicht, status = abgelehnt,
   Run endet mit result "Abgelehnt", Anna sieht den Kommentar im Verlauf.

5. Eva (Rolle einkauf) bestellt beim Lieferanten, trägt Bestellnummer und Liefertermin ein
   und klickt "Bestellung abschließen"
   → update_row row_B1 { status: bestellt, lieferanten_nr, liefertermin }
   → Übergang ordered → end, run.status = completed, run.result = "Bestellt"
   → Anna: "Bestellt am 26.11. von Eva Einkauf, Liefertermin 03.12."
```

### 10.3 Dasselbe per Agent

**Teamleiter lässt einen Agenten genehmigen** (Agent handelt im Auftrag von Tom):

```
list_tasks(assigned_to = "me", workflow = "bestellprozess")
  → [{ id: tsk_2, run: run_42, step: genehmigung, title: "Bestellung KS 4711 – Anna Beispiel", due_at: … }]
get_task(tsk_2)
  → Schritt-Dokument als Markdown (Werte ausgewertet), Artikel,
    buttons: [{ id: approve, label: Genehmigen }, { id: reject, label: Ablehnen, require: [kommentar] }]
complete_task(tsk_2, button = "approve", values = { kommentar: "Passt." })
  → { run: { status: active, current_step: bestellung } }
```

Im Verlauf steht: „Genehmigt von Einkaufs-Assistent im Auftrag von Tom Teamleiter“.

**Einkaufs-Agent als eigener Zuständiger:** Hat der Agent `agt_einkauf` die Rolle `einkauf`, erscheint `tsk_3` auch in seiner Aufgabenliste. Er kann die Bestellung über ein Lieferanten-System auslösen und dann `complete_task(tsk_3, "ordered", { lieferanten_nr, liefertermin })` aufrufen.

**Antragstellerin fragt ihren Assistenten nach dem Stand** (im Auftrag von Anna):

```
list_runs(started_by = "me", status = "active")
get_run(run_42)
  → "Wartet auf Genehmigung seit 2 Stunden, zuständig: Teamleitung, fällig am 27.11."
```

---

## 11. Verbesserungen gegenüber den bisherigen Entwürfen

| Bisher | Jetzt | Warum |
|---|---|---|
| Grid wie Excel **und** typisierte Tabelle, A1-Referenzen, Formel-Engine (HyperFormula/IronCalc) | nur typisierte Tabellen, kleine Ausdruckssprache | Formulare und Workflows brauchen Datensätze mit Spalten, keine Zellen. Spart Lizenzfrage und Abhängigkeitsgraph. Berechnete Spalten können später kommen. |
| Tabellen gehören zu einem Dokument (`sheets.document_id`) | Tabellen sind eigenständig, Dokumente zeigen sie per `table_view` | Eine Tabelle „Bestellungen“ wird von vielen Dokumenten und Workflows genutzt. |
| Yjs-CRDT als Quelle der Wahrheit plus Projektion in die DB | Server-autoritatives Operations-Log, Verteilung per WebSocket | Ein Schreibweg für Browser, Agent und Workflow. Kein Abgleich zwischen CRDT und DB. Für Textblöcke reicht OT auf einem String pro Block. |
| Template, Instanz und Run als drei Konzepte, Graph aus generischen Nodes | Workflow (mit Versionen) und Run. Schritte sind Dokumente, Übergänge kommen aus Button-Outcomes | Entspricht direkt dem gewünschten Modell „Workflow besteht aus Dokumenten“. Für Agenten viel leichter zu erzeugen. |
| „Menschliche Freigabe“ als ein Node-Typ unter vielen | Jeder Schritt hat Zuständige (Person, Rolle, Antragsteller, Ausdruck), daraus entstehen Aufgaben mit Claim, Frist und Verlauf | Freigabeketten sind der Normalfall, nicht die Ausnahme. Aufgabenliste und Statusverfolgung ergeben sich daraus ohne Zusatzlogik. |
| Zeile schreiben als Workflow-Node | Formular mit deklarativen `actions` | Funktioniert auch ohne Workflow, in jedem Dokument. |
| Formeln auch als Mapping-Sprache | `{{ }}`-Pfade mit wenigen Funktionen | Gut prüfbar (`validate_workflow` findet Tippfehler), leicht für Agenten. |
| Server vergibt IDs | Client erzeugt präfixierte ULIDs, dazu lesbare Keys | Ganze Strukturen in einem atomaren Batch anlegen. Keys machen MCP-Aufrufe lesbar. |
| Verschachtelter Baum | flache Blockliste mit `parent_id` und Fractional Index | Einzelne Absätze gezielt ändern, robust für LLMs (siehe README). |
| Laufende Workflows sehen geänderte Dokumente | Dokumente werden beim Veröffentlichen eingefroren | Ein Run kann nicht kaputtgehen, weil jemand das Formular umbaut. |

---

## 12. Offene Punkte

- **Rechte allgemein:** Wer darf Tabellen-Schemata ändern, wer nur Zeilen schreiben? Läuft eine Formular-Action mit den Rechten des Absenders oder des Formular-Autors? Vorschlag: mit den Rechten des Workflows bzw. Formular-Autors, damit z. B. die Teamleitung über das Formular den Status einer Bestellung setzen kann, ohne allgemeine Schreibrechte auf die Tabelle zu haben.
- **Eskalation:** Was passiert nach einer überschrittenen Frist, außer der Benachrichtigung? Z. B. automatische Umverteilung an managers. Passt als `Step.on_overdue`.
- **Vertretung:** Abwesenheiten, bei denen Aufgaben automatisch an eine Vertretung gehen. Passt als Regel beim Auflösen der Zuständigen (5.9).
- **Mehrere Genehmigungen pro Schritt:** z. B. „zwei von drei müssen zustimmen“. Lässt sich heute mit aufeinanderfolgenden Schritten abbilden, später eventuell als `Step.quorum`.
- **Automatische Schritte:** HTTP-Aufruf, E-Mail, LLM-Schritt. Passt als zusätzlicher Step-Typ `automation`, der statt eines Dokuments eine Liste von Actions hat und ein Outcome zurückgibt.
- **Bedingungen in Übergängen:** z. B. „Summe > 1000 → zusätzliche Genehmigung durch Leitung“. Passt als `Transition.when: Expr`.
- **Rückfragen mit Korrektur:** Zurück zu `erfassen` mit Bearbeitung der bestehenden Artikel braucht Formulare, die vorhandene Zeilen laden und abgleichen (`line_items` mit Quelle). Bis dahin endet eine Ablehnung den Run, und für Rückfragen gibt es Kommentare.
- **Berechnete Spalten** (`kind: "formula"`) mit derselben Ausdruckssprache.
- **Vorschlagsmodus für Agenten:** Agent-Batches als Vorschlag speichern, den ein Mensch annimmt. Das Operations-Log macht das leicht möglich.
- **Migration laufender Runs** auf eine neue Workflow-Version: zunächst nicht vorgesehen.
