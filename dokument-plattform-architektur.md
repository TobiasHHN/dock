# Architekturvorschlag: Dokument-Plattform mit Text, Tabellen und Workflows

## 1. Die wichtigste Entscheidung: Markdown ist das Austauschformat, nicht das Speicherformat

Markdown eignet sich gut als Format für Agents und für Import und Export. LLMs schreiben und lesen es sehr zuverlässig. Als einzige gespeicherte Quelle der Wahrheit (die kanonische Speicherung) taugt es aber nicht:

- **Keine stabilen IDs.** Ein Agent soll „Absatz X“ oder „Zelle C5 in Tabelle Y“ gezielt ändern können. Eine Workflow-Referenz soll auch nach Umsortierungen noch funktionieren.
- **Tabellen mit Formeln und Workflow-Graphen passen nicht verlustfrei in Markdown.**
- **Gleichzeitiges Bearbeiten** durch mehrere Personen plus Agents geht mit einem Textblob nicht sauber.

**Empfehlung:** Ein Dokument ist ein **Baum aus Blöcken** (ähnlich wie bei Notion oder Coda). Jeder Block hat eine stabile ID und einen Typ, zum Beispiel `paragraph`, `heading`, `list`, `table`, `workflow` oder `embed`. Textblöcke speichern Rich Text, und Markdown wird bei Bedarf daraus erzeugt und wieder eingelesen.

```
Document
 ├─ heading     (b_01)
 ├─ paragraph   (b_02)
 ├─ table       (t_07)   → eigenes Grid/Sheet-Modell
 ├─ paragraph   (b_03)   → enthält Inline-Referenz auf =t_07!Summe
 └─ workflow    (w_03)   → Instanz von Template "freigabe@4"
```

Für Agents gibt es eine Markdown-Darstellung mit Direktiven, in der die IDs erhalten bleiben:

```markdown
---
id: doc_8f2
title: Angebot Q3
---
# Angebot Q3 {#b_01}

Die Gesamtsumme beträgt {=t_07!D_total}. {#b_02}

:::table{#t_07 name="Positionen"}
| Pos | Menge | Preis | Summe      |
|-----|-------|-------|------------|
| A   | 3     | 10    | =B2*C2     |
:::

:::workflow{#w_03 template="tpl_freigabe@4"}
:::
```

## 2. Tabellen

**Zuerst müsst ihr ein Produktkonzept festlegen.** Es gibt zwei Arten von Tabellen:

- **Grid wie Excel:** freie Zellen, A1-Referenzen, Formeln überall.
- **Typisierte Tabelle wie Airtable:** Spalten mit festem Typ, Zeilen sind Datensätze, Formeln gelten pro Spalte.

Für den Ersatz von Excel braucht ihr das Grid. Für Workflows („füge eine Zeile hinzu“, „finde Kunde X“) ist die typisierte Tabelle viel angenehmer. Mein Vorschlag ist ein gemeinsames Modell mit beiden Ansichten. Intern hat jede Zeile und jede Spalte eine stabile ID, und Spalten können optional einen Typ und einen Namen haben.

**Speicherung:**

- Zeilen und Spalten haben eigene IDs und eine Sortierposition (Fractional Indexing). Zellen werden über `(row_id, col_id)` adressiert.
- A1-Adressen wie „B2“ sind nur eine Darstellung. Formeln werden intern auf IDs umgeschrieben. So gehen Referenzen nicht kaputt, wenn jemand eine Zeile einfügt. Excel macht das intern ähnlich.
- Pro Zelle wird gespeichert: `raw` (die Eingabe, zum Beispiel `=SUM(B2:B9)`), `value` (das berechnete Ergebnis) und `format`.

**Formel-Engine:** Sie muss **serverseitig** laufen, damit API, MCP und Workflows berechnete Werte sehen, ohne dass ein Browser offen ist.

- **HyperFormula** (JS): sehr Excel-kompatibel, aber nur unter GPLv3 oder mit kommerzieller Lizenz. Das solltet ihr prüfen.
- **IronCalc** (Rust/WASM, MIT/Apache): läuft auf dem Server und im Browser.
- **Univer**: eine Open-Source-Office-Suite mit Sheets und Docs. Die könntet ihr auch als Basis evaluieren.

Die Engine braucht einen Abhängigkeitsgraphen, auch über Dokumente hinweg, wenn Tabelle A auf Tabelle B verweist. Dann wird bei Änderungen nur das neu berechnet, was betroffen ist.

## 3. Workflows

Hier gibt es drei getrennte Konzepte. Diese Trennung ist der Schlüssel für Wiederverwendbarkeit und Verschachtelung.

| Konzept | Was es ist | Änderbar? |
|---|---|---|
| **Template-Version** | Graph aus Nodes und Edges, Input/Output-Schema | unveränderlich, sobald veröffentlicht (`freigabe@4`) |
| **Instanz** | Workflow-Block im Dokument: Template-Version + Bindings (welche Tabelle, welches Dokument) + Trigger | ja |
| **Run** | eine konkrete Ausführung mit Status pro Node | nur Log |

**Node-Typen (Vorschlag):**

- **Trigger:** manuell, Zeitplan, Dokument geändert, Zelle oder Zeile geändert, Webhook, Agent-Aufruf
- **Aktionen:** Dokument erstellen oder ändern, Zeile schreiben, HTTP-Aufruf, E-Mail, LLM-/Agent-Schritt
- **Logik:** Bedingung, Schleife über Zeilen, Parallel, Warten, menschliche Freigabe
- **Sub-Workflow:** referenziert `template_id@version` und hat ein Input/Output-Mapping. Das ist die Verschachtelung.

**Verschachtelung:**

- Ein Sub-Workflow-Node ist intern einfach ein Kind-Run mit `parent_run_id`.
- Zyklen (A ruft B, B ruft A) werden beim Veröffentlichen erkannt und abgelehnt. Zur Laufzeit gibt es zusätzlich eine maximale Tiefe.
- Versionen werden standardmäßig fest gepinnt. Bei einer neuen Version zeigt die Oberfläche „Update verfügbar“, statt automatisch zu migrieren.

**Eine Ausdruckssprache für alles:** Nutzt die Formelsprache der Tabellen auch für das Daten-Mapping in Workflows, zum Beispiel `=Positionen!Summe * 1.19` oder `=nodes.fetch.output.total`. Dann müssen Nutzer und Agents nur eine Syntax lernen.

**Ausführung:** Workflows mit Wartezeiten, Freigaben und Retries brauchen **dauerhafte Ausführung** (Durable Execution), die Abstürze und Neustarts übersteht.

- **MVP:** eine Job-Queue auf Postgres (pg-boss oder graphile-worker) und ein eigener Interpreter, der den Graphen Schritt für Schritt abarbeitet. Der Zustand jedes Schritts liegt in der Datenbank.
- **Später:** Temporal oder Restate. Verschachtelte Workflows entsprechen dort direkt den „Child Workflows“, Warten und Freigaben gibt es eingebaut.

**Sicherheit:** Legt fest, *mit wessen Rechten* ein Workflow läuft: Ersteller, auslösende Person oder Service-Account. Das ist besonders wichtig, wenn Agents Workflows starten.

## 4. Referenzen

Verwendet ein einheitliches URI-Schema und speichert jede Referenz zusätzlich in einer eigenen Tabelle:

```
doc://doc_8f2
doc://doc_8f2/block/b_02
doc://doc_8f2/table/t_07/range/B2:D9      (intern: Row/Col-IDs)
doc://doc_8f2/table/t_07/column/Summe
wf://tpl_freigabe@4
```

Die Referenz-Tabelle liefert:

- Backlinks („wo wird dieses Dokument verwendet?“)
- Abhängigkeiten für die Neuberechnung
- Warnungen vor dem Löschen („3 Workflows referenzieren diese Tabelle“)
- Rechteprüfungen

## 5. Datenbank: PostgreSQL als Kern

Postgres reicht für alles in diesem Vorschlag. `jsonb` speichert die flexiblen Inhalte, `pgvector` übernimmt die semantische Suche für Agents, und die Volltextsuche ist eingebaut.

```sql
documents        (id, workspace_id, title, created_by, version, updated_at)
blocks           (id, document_id, parent_id, position, type, props jsonb, content jsonb)
doc_crdt_state   (document_id, snapshot bytea, updated_at)   -- falls Yjs

sheets           (id, document_id, block_id, name)
sheet_columns    (id, sheet_id, position, name, type, formula)
sheet_rows       (id, sheet_id, position)
cells            (sheet_id, row_id, col_id, raw text, value jsonb, format jsonb)

workflow_templates          (id, workspace_id, name, latest_version)
workflow_template_versions  (template_id, version, graph jsonb,
                             input_schema jsonb, output_schema jsonb, published_at)
workflow_instances          (id, document_id, block_id, template_id, version,
                             bindings jsonb, triggers jsonb, run_as)
workflow_runs               (id, instance_id, template_version, parent_run_id,
                             status, input jsonb, output jsonb, started_at, ended_at)
workflow_run_steps          (run_id, node_id, attempt, status, input, output, error)

references       (source_doc, source_block, target_uri, kind)
operations       (id, document_id, seq, actor_type user|agent|workflow,
                  actor_id, ops jsonb, created_at)               -- Audit + Undo
embeddings       (block_id, vector)                               -- pgvector
```

Dateianhänge kommen in S3-kompatiblen Speicher.

**Die Tabelle `operations` ist für Agents zentral.** Jede Änderung ist nachvollziehbar mit wer, wann, welcher Agent und welcher Workflow-Run. Sie kann rückgängig gemacht werden. Und ihr könnt einen **Vorschlagsmodus** anbieten: Änderungen eines Agents erscheinen als Vorschlag, den eine Person annimmt. Das würde ich früh einplanen.

## 6. Echtzeit-Zusammenarbeit

Wenn mehrere Leute gleichzeitig editieren sollen, nehmt einen **CRDT** (ein Datenmodell, das gleichzeitige Änderungen automatisch zusammenführt). Die Standardwahl ist **Yjs**, zum Beispiel mit TipTap/ProseMirror oder BlockNote als Editor.

- Der Yjs-Zustand ist die Quelle für Live-Editing.
- Der Server schreibt laufend eine Projektion in `blocks` und `cells`. Daraus lesen API, Suche, MCP und Workflows.
- **Agents und Workflows schreiben nie roh in den CRDT.** Sie rufen fachliche Operationen auf (siehe API). Der Server übersetzt diese in Yjs-Updates, und alle verbundenen Clients sehen die Änderung live.

## 7. API

```
REST (oder tRPC)
GET    /documents/{id}?format=json|md
POST   /documents                       (aus JSON oder Markdown)
POST   /documents/{id}/ops              Batch fachlicher Operationen, mit baseVersion
GET    /tables/{id}/range?a1=B2:D9      Werte + Formeln
POST   /tables/{id}/rows                Zeilen anhängen
POST   /tables/{id}/query               Filter/Sortierung
GET/POST /workflow-templates[/{id}/versions]
POST   /workflow-instances/{id}/runs    Workflow starten
GET    /runs/{id}                       Status + Schritte
WS     /documents/{id}/live             Yjs-Sync
```

Fachliche Operationen sehen zum Beispiel so aus:

```json
[
  {"op":"insert_block","after":"b_02","block":{"type":"paragraph","md":"Neuer Text"}},
  {"op":"set_cells","table":"t_07","cells":{"C2":"12","D2":"=B2*C2"}},
  {"op":"add_node","workflow":"tpl_freigabe","node":{"type":"approval","id":"n5"}},
  {"op":"connect","workflow":"tpl_freigabe","from":"n4.out","to":"n5.in"}
]
```

Die Operationen laufen atomar. `baseVersion` sorgt für optimistisches Sperren: Hat sich das Dokument seit dem letzten Lesen geändert, lehnt der Server ab, und der Client liest neu.

## 8. MCP-Server

Der MCP-Server ist **eine dünne Schicht über derselben API**, ohne eigene Logik. Für die Authentifizierung nutzt ihr OAuth 2.1 (laut MCP-Spezifikation) mit Scopes pro Workspace.

Gebt den Agents fachliche Tools, kein generisches „schreibe JSON“:

| Bereich | Tools |
|---|---|
| Finden | `search_documents` (Volltext + semantisch), `list_documents` |
| Lesen | `get_document` (Markdown mit Block-IDs), `get_table_range`, `query_table` |
| Schreiben | `create_document` (aus Markdown), `edit_document` (Ops-Batch), `set_cells`, `append_rows` |
| Workflows | `list_templates`, `get_template`, `create_template_version` (Graph als JSON), `validate_workflow`, `run_workflow`, `get_run` |

Dazu kommen MCP-Resources für `doc://…` und `wf://…`.

Zwei Punkte machen die Bedienung für Agents deutlich besser:

- **`validate_workflow`** gibt verständliche Fehler zurück, zum Beispiel „Node n5 hat keinen Eingang“ oder „Zyklus über tpl_b“. Damit kann der Agent selbst korrigieren.
- **`get_table_range`** liefert Werte *und* Formeln. So versteht der Agent, warum eine Zelle einen bestimmten Wert hat.

## 9. Tech-Stack (Vorschlag)

- **TypeScript durchgängig.** Formel-Engine und Validierung laufen dann im Browser und auf dem Server.
- **Editor:** TipTap/ProseMirror oder BlockNote, mit Yjs
- **Grid:** Glide Data Grid oder AG Grid, alternativ Univer als Ganzes
- **Workflow-Canvas:** React Flow (xyflow)
- **Backend:** Node (Fastify oder NestJS), Hocuspocus als Yjs-Server
- **Daten:** Postgres + pgvector, S3, anfangs eine Queue auf Postgres, später Temporal
- **Schemas** einmal in Zod/JSON Schema definieren. Daraus entstehen API-Validierung, MCP-Tool-Definitionen und Typen.

## 10. Vorschlag für die Reihenfolge

1. Block-Dokumente mit Markdown-Import und -Export, Postgres und REST-API
2. **MCP-Server von Anfang an**, als Härtetest für die API
3. Tabellen mit Formel-Engine (serverseitig) und Referenzen zwischen Dokumenten
4. Workflow-Templates und -Instanzen, einfache Trigger und Aktionen, Run-Log
5. Sub-Workflows, Freigaben und Warten, gegebenenfalls Umstieg auf Temporal
6. Echtzeit-Zusammenarbeit mit Yjs und Vorschlagsmodus für Agents

## Offene Fragen, die die Architektur beeinflussen

- **Grid, typisierte Tabelle oder beides?**
- **Echtzeit-Zusammenarbeit ab Tag 1?** Wenn nicht, wird es deutlich einfacher: Ops-API mit Versionen, ohne CRDT.
- **Self-Hosting oder On-Prem?** Das spricht eher gegen Temporal und für eine schlanke Queue auf Postgres.
- **Wie wichtig ist Kompatibilität mit .xlsx und .docx beim Import und Export?** Das bestimmt, wie Excel-treu die Formel-Engine sein muss.
