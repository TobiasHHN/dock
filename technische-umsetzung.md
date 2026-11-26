# Technische Umsetzung

Dieses Dokument setzt die Logik aus `anwendungslogik.md` auf den festgelegten Stack um:

- **Backend:** Python mit FastAPI
- **Frontend:** React mit Vite, React Flow für Workflows
- **Datenbank:** PostgreSQL mit pgvector

Die Abschnittsnummern in Klammern, z. B. (6.2), verweisen auf `anwendungslogik.md`.

---

## 1. Überblick

```
┌──────────────────────────── Browser ────────────────────────────┐
│ React + Vite                                                    │
│  Sync-Store (Zustand) ◄──── WebSocket ────┐   REST (Listen,     │
│  Blöcke · Tabellen · Formulare · Runs      │   Suche, Upload)    │
│  React Flow (Workflow-Editor, Run-Ansicht) │                     │
└────────────────────────────────────────────┼─────────────────────┘
                                             │
┌──────────────────────── FastAPI (n Instanzen) ──────────────────┐
│  /api/*  REST        /ws  WebSocket        /mcp  MCP-Server       │
│        └──────────────┬──────────┴──────────────┘                 │
│                 Op-Pipeline (ein Schreibweg)                      │
│  Domäne: tables · documents · forms · workflows · expressions     │
│                 Realtime-Hub (LISTEN/NOTIFY)                      │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌──────────── PostgreSQL + pgvector ───────────┐   ┌──── Worker ────┐
│ Tabellen, Blöcke, Ops-Log, Runs, Embeddings  │◄──┤ procrastinate  │
│ Job-Queue (procrastinate)                    │   │ Embeddings,    │
└──────────────────────────────────────────────┘   │ Aufräumen      │
                                                   └────────────────┘
```

- **Keine weitere Infrastruktur nötig.** Postgres übernimmt Daten, Vektorsuche, Volltextsuche, Job-Queue und das Verteilen von Änderungen zwischen mehreren FastAPI-Instanzen (`LISTEN/NOTIFY`). Redis kann später dazukommen, wenn die Last es verlangt.
- REST, WebSocket und MCP sind nur **Eingänge**. Geschrieben wird ausschließlich über die Op-Pipeline (6).

---

## 2. Backend

### 2.1 Bibliotheken

| Zweck | Bibliothek |
|---|---|
| Web, WebSocket | `fastapi`, `uvicorn[standard]` |
| Schemas, Validierung | `pydantic` v2 (Discriminated Unions für Ops und Blocktypen) |
| Datenbank | `sqlalchemy` 2.x (async) mit `asyncpg`, Migrationen mit `alembic` |
| Vektoren | `pgvector` (Python-Paket, SQLAlchemy-Typ `Vector`) |
| Hintergrund-Jobs | `procrastinate` (Job-Queue auf Postgres, async) |
| MCP | offizielles `mcp` SDK (`FastMCP`), als ASGI-App unter `/mcp` eingehängt (Streamable HTTP) |
| Import | `openpyxl` (xlsx, nur lesen, Werte statt Formeln), `python-docx` (docx), `python-multipart` (Upload) |
| IDs | `python-ulid` |
| Sortierpositionen | `fractional-indexing` (Python-Port; im Frontend das gleichnamige npm-Paket, gleicher Algorithmus) |
| Markdown mit Direktiven | `markdown-it-py` mit `mdit-py-plugins` (`container`, `attrs`) |
| Ausdrücke `{{ }}` | eigener kleiner Parser (ca. 200 Zeilen) oder `lark` |
| Auth | OAuth 2.1 / JWT, z. B. `authlib` |
| Tests | `pytest`, `pytest-asyncio`, `httpx` |

### 2.2 Projektstruktur

```
backend/
  app/
    main.py                  # FastAPI-App, mountet api, ws, mcp
    config.py
    db/
      models.py              # SQLAlchemy-Modelle (Abschnitt 4)
      session.py
      migrations/            # alembic
    schemas/                 # Pydantic: Block, Column, Op, OpBatch, WS-Nachrichten
      blocks.py
      tables.py
      ops.py
      workflows.py
      ws.py
    domain/                  # reine Logik, ohne FastAPI
      ids.py                 # Präfix + ULID, Key-Auflösung
      tables.py              # Typumwandlung, Pflicht/Unique, on_delete
      documents.py           # Blockbaum, Verschachtelungsregeln
      text_ot.py             # Transformation von text.edit
      forms.py               # Button-Sichtbarkeit (4.3), Submit (4.6)
      workflows.py           # Übergänge, Validierung (5.7), Veröffentlichen
      tasks.py               # Zuständige auflösen, can_act, Claim, Umverteilen (5.9)
      run_status.py          # Statusansicht, Events, Benachrichtigungen (5.10)
      expressions.py         # Parser und Auswertung (4.5)
      references.py          # Referenz-Index (9)
      markdown.py            # Blöcke ⇄ Markdown mit Direktiven (8.2)
    ops/
      pipeline.py            # apply_batch(): der einzige Schreibweg (6.2)
      handlers/              # ein Handler pro Op-Typ
      inverse.py             # inverse Ops für Undo
    realtime/
      hub.py                 # Verbindungen, Kanäle, LISTEN/NOTIFY
      presence.py
    api/                     # REST-Router
    mcp/
      server.py              # MCP-Tools (8.1), rufen ops.pipeline / Lese-Services
    imports/                 # Dateien → Ops (8.3 der Logik)
      xlsx.py                # Blatt → table.create + row.insert, Typableitung
      docx.py                # Absätze, Listen, Felder, Tabellen → doc.create
      store.py               # vorbereitete Imports (import_id → Ops, Warnungen)
    search/
      embeddings.py
      search.py              # hybride Suche
    jobs/                    # procrastinate-Tasks
  tests/
```

**Wichtig:** `domain/` kennt weder FastAPI noch WebSocket. So lässt sich die Logik direkt mit `pytest` testen, und REST, WebSocket und MCP benutzen garantiert dieselben Regeln.

### 2.3 Schemas mit Pydantic

Ops und Blöcke sind Discriminated Unions. Daraus entstehen automatisch Validierung, OpenAPI und die JSON-Schemas für die MCP-Tools.

```python
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field

class RowInsert(BaseModel):
    op: Literal["row.insert"]
    table: str                      # ID oder Key
    rows: list["NewRow"]

class RowUpdate(BaseModel):
    op: Literal["row.update"]
    table: str
    row: str
    values: dict[str, "Value"]

class BlockInsert(BaseModel):
    op: Literal["block.insert"]
    doc: str
    parent: str | None
    after: str | None = None
    block: "BlockIn"

# … alle Ops aus anwendungslogik.md 6.1

Op = Annotated[Union[RowInsert, RowUpdate, BlockInsert, ...], Field(discriminator="op")]

class OpBatch(BaseModel):
    batch_id: str
    base: dict[str, int] = {}
    ops: list[Op]
```

Der `actor` wird **nicht** vom Client übernommen, sondern serverseitig aus der Authentifizierung gesetzt.

### 2.4 Die Op-Pipeline

```python
async def apply_batch(batch: OpBatch, actor: Actor) -> BatchResult:
    if cached := await idempotency.get(batch.batch_id):
        return cached

    async with session.begin():                       # eine Transaktion
        await lock_affected(batch)                    # siehe 2.5
        ctx = OpContext(session, actor)
        ops = [ctx.resolve_keys(op) for op in batch.ops]
        ctx.check_base_versions(batch.base)           # → ConflictError
        for op in ops:
            check_permission(actor, op)
            await HANDLERS[op.op](ctx, op)             # validieren + anwenden
        await references.update(ctx.touched)
        seqs = await oplog.append(ctx)                 # Ops + inverse Ops, seq pro Kanal
        await notify(ctx.channels, batch.batch_id)     # pg_notify, läuft erst bei Commit
    return BatchResult(batch_id=batch.batch_id, seq=seqs, results=ctx.results)
```

`form.submit` ist ein Handler wie jeder andere. Er erzeugt intern weitere Ops (`row.insert`, `row.update`, Run-Änderungen), die im selben Batch landen. So ist der Submit atomar und erscheint bei allen Clients als **ein** Batch.

### 2.5 Nebenläufigkeit in Postgres

- **Reihenfolge pro Kanal:** Für jeden betroffenen Kanal wird in der Transaktion `UPDATE channels SET seq = seq + 1 WHERE id = $1 RETURNING seq` ausgeführt. Die Zeilensperre sorgt dafür, dass Batches auf demselben Kanal nacheinander laufen und `seq` lückenlos bleibt.
- **Deadlocks vermeiden:** Kanäle werden immer in sortierter Reihenfolge gesperrt.
- **Batches auf verschiedenen Dokumenten oder Tabellen** laufen parallel.
- Isolation: `READ COMMITTED` reicht, weil die Kanal-Sperre serialisiert.

### 2.6 Text-OT für `text.edit`

- Jeder Textblock hat eine `version`. Der Client schickt `text.edit` mit der Version, die er zuletzt gesehen hat.
- Der Server holt aus dem Op-Log alle `text.edit` dieses Blocks seit dieser Version und verschiebt `from`/`to` des neuen Edits entsprechend (`domain/text_ot.py`).
- Weil das nur einen String pro Block betrifft, bleibt das überschaubar. Marks werden als Bereiche gespeichert und mit denselben Regeln verschoben.
- Festlegungen (umgesetzt in `domain/text_ot.py` und `frontend/src/sync/textOt.ts`, gemeinsame Fälle in `spec/fixtures/text_ot/`):
  - Positionen zählen Einheiten: jedes Zeichen (Code Point, nicht UTF-16) aus `text`- und `link`-Teilen zählt 1, `mention` und `value` je 1.
  - `marks` im Edit beschreibt die Marks des eingefügten Texts, Bereiche relativ zu `insert`. Fehlt `marks`, erbt der Text die Marks des Zeichens davor.
  - Einfügen an derselben Stelle: der am Server frühere Edit steht vorn. Liegt ein Edit ganz in einem Bereich, den ein früherer Edit ersetzt hat, entfällt er (Löschen gewinnt); bei genau gleichem Bereich gewinnt der frühere.
  - Ins Op-Log und an die Clients geht der transformierte Edit, `version` ist dort die Block-Version vor der Änderung. Der Server sucht die zu berücksichtigenden Edits im Op-Log über diese Version.
  - Der Browser hat pro Block höchstens einen Edit unterwegs und schickt Eingaben danach gesammelt (`frontend/src/documents/textSync.ts`).

### 2.7 WebSocket und Verteilung

```python
@app.websocket("/ws")
async def ws(socket: WebSocket, user = Depends(ws_auth)):
    conn = await hub.connect(socket, user)
    try:
        async for msg in conn.messages():      # Pydantic-validiert
            match msg:
                case Subscribe():   await hub.subscribe(conn, msg.channel, msg.since)
                case Unsubscribe(): hub.unsubscribe(conn, msg.channel)
                case OpsMsg():      await conn.reply(await apply_batch_safe(msg.batch, user))
                case Presence():    await presence.update(conn, msg)
    finally:
        await hub.disconnect(conn)
```

**Verteilung über mehrere Instanzen:**

1. Nach dem Commit ruft die Pipeline `pg_notify('ops', '{"channel":"doc:doc_1","seq":121}')` auf. NOTIFY wird von Postgres erst beim Commit zugestellt, abgebrochene Transaktionen schicken also nichts.
2. Jede FastAPI-Instanz hält **eine** `asyncpg`-Verbindung mit `add_listener('ops', …)`.
3. Bei einer Benachrichtigung liest die Instanz den Batch aus dem Op-Log (die NOTIFY-Payload ist auf 8 KB begrenzt, deshalb nur die Referenz) und schickt ihn an ihre lokalen Abonnenten des Kanals.
4. **Präsenz** wird nicht gespeichert, sondern direkt per `pg_notify('presence', …)` verteilt. Einträge verfallen nach 30 Sekunden ohne Heartbeat.

**Nachholen:** `subscribe` mit `since` liest `oplog WHERE channel = $1 AND seq > $2`. Ist die Lücke größer als z. B. 1000 Ops, schickt der Server einen Snapshot.

### 2.8 MCP-Server

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dock")

@mcp.tool()
async def apply_ops(batch: OpBatch, ctx: Context) -> BatchResult:
    """Führt einen atomaren Batch von Operationen aus (Tabellen, Dokumente, Workflows)."""
    return await apply_batch(batch, actor_from(ctx))

@mcp.tool()
async def get_document(doc: str, format: Literal["md", "json"] = "md") -> str | dict: ...

app.mount("/mcp", mcp.streamable_http_app())
```

- Die Tool-Schemas kommen direkt aus den Pydantic-Modellen. Ein Agent sieht also exakt dieselbe Struktur wie die REST-API.
- Fehler der Pipeline (`CONFLICT`, `IN_USE`, `BLOCK_IN_USE`, Validierungsfehler mit Pfad) werden als lesbare Tool-Fehler zurückgegeben, damit der Agent selbst korrigieren kann.
- Agenten bekommen einen eigenen Actor-Typ `agent`. Im Browser erscheinen ihre Änderungen mit eigenem Namen und eigener Farbe.
- **Akteur bestimmen** (5.8 der Logik): Meldet sich der Agent mit einem delegierten Token einer Person an (OAuth Authorization Code, Scope z. B. `dock:act_on_behalf`), wird `Actor { type: "agent", id, on_behalf_of: usr_… }`, und Rechte sowie Rollen kommen von der Person. Mit Client Credentials handelt er als eigener Akteur mit seinen eigenen Rollen.

### 2.9 Import von Excel und Word

Umsetzung von 8.3 der Logik.

- **REST:** `POST /api/imports/xlsx` und `POST /api/imports/docx` (multipart, Feld `file`, dazu die Parameter aus 8.3 als Formularfelder). Antwort: `{ import_id, created, warnings }`. Mit `apply=true` führt der Endpunkt den Batch sofort über die Op-Pipeline aus und liefert zusätzlich das `BatchResult`.
- **Parser** in `imports/` sind reine Funktionen `bytes → ImportPlan(ops, created, warnings)` ohne FastAPI und ohne Datenbank. So lassen sie sich mit Beispieldateien aus `spec/fixtures/` testen. Die Typableitung (Excel) und die Felderkennung (Word) stehen dort als Fixtures „Datei → erwartete Ops“.
- **Excel:** `openpyxl.load_workbook(read_only=True, data_only=True)`, damit Formeln durch ihren gespeicherten Wert ersetzt werden und große Dateien nicht komplett im Speicher liegen. Limits: 10 MB Datei, 10 000 Zeilen und 100 Spalten je Blatt, mehr wird mit Fehler abgelehnt.
- **Word:** `python-docx`. Absätze werden über Stil (`Heading 1–3`, `List Bullet`, `List Number`) und `runs` (fett, kursiv, Hyperlinks) in `heading`, `paragraph`, `list` und Inline-Marks übersetzt. Felderkennung per regulärem Ausdruck auf `^(?P<label>[^:]{1,60}):\s*(_{3,}|\.{3,}|\[\s*\])\s*$`. Tabellen werden über „alle Zeilen unter dem Kopf leer?“ entschieden.
- **IDs:** Der Parser erzeugt die IDs (`python-ulid`) und die `position`-Werte (`fractional-indexing`) selbst, damit `created` sie vor der Ausführung nennen kann.
- **`import.include`:** Handler in der Pipeline (vor dem Auflösen der Keys). Er lädt die Ops aus `imports` (Tabelle), prüft, dass der Import vom selben Akteur stammt und noch gültig ist, und hängt sie an die Stelle des Ops in `batch.ops`. Danach läuft alles wie ein normaler Batch, atomar und mit Op-Log. Ein zweiter `import.include` desselben Imports in einem anderen Batch wird abgelehnt, bereits ausgeführte Imports sind „verbraucht“.
- **MCP:** Die Tools `import_xlsx` und `import_docx` (8.1 der Logik) lesen die lokale Datei (`file_path`, bei stdio-Betrieb) oder nehmen `content_base64` (bei HTTP-Betrieb) und rufen die REST-Endpunkte auf.
- **Rechte:** Der Endpunkt verlangt nur Anmeldung. Die Rechte der enthaltenen Ops prüft die Pipeline beim `import.include`.

---

## 3. Suche mit pgvector

### 3.1 Was eingebettet wird

| Quelle | Einheit |
|---|---|
| Dokumente | Abschnitte: eine Überschrift plus folgende Textblöcke bis zur nächsten Überschrift gleicher oder höherer Ebene, max. ca. 500 Tokens |
| Tabellen | Schema-Beschreibung (Name, Spalten) als ein Eintrag; Zeilen optional pro Tabelle zuschaltbar |
| Workflows | Name, Schrittnamen und Text der Schritt-Dokumente |

Abschnitte statt einzelner Absätze, weil einzelne Absätze oft zu wenig Kontext haben. Jeder Eintrag speichert die enthaltenen `block_ids`, damit ein Treffer direkt auf den Block zeigt.

### 3.2 Aktualisierung

- Die Pipeline merkt sich geänderte Dokumente und legt einen Job `reembed(doc_id)` in procrastinate an, **entprellt** (z. B. frühestens 30 Sekunden nach der letzten Änderung, über `queueing_lock` pro Dokument).
- Der Worker berechnet die Abschnitte neu, vergleicht einen Hash pro Abschnitt und erzeugt nur für geänderte Abschnitte neue Embeddings.
- Modell und Dimension stehen in `config.py`. Jedes Embedding speichert den Modellnamen, damit ein Modellwechsel schrittweise migriert werden kann.

### 3.3 Hybride Suche

```sql
WITH vec AS (
  SELECT id, row_number() OVER (ORDER BY embedding <=> $query_vec) AS r
  FROM embeddings
  WHERE workspace_id = $ws
  ORDER BY embedding <=> $query_vec
  LIMIT 50
), fts AS (
  SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, q) DESC) AS r
  FROM embeddings, websearch_to_tsquery('german', $query_text) q
  WHERE workspace_id = $ws AND tsv @@ q
  LIMIT 50
)
SELECT id, sum(1.0 / (60 + r)) AS score          -- Reciprocal Rank Fusion
FROM (SELECT * FROM vec UNION ALL SELECT * FROM fts) x
GROUP BY id
ORDER BY score DESC
LIMIT $limit;
```

Vektorsuche findet Bedeutung, Volltext findet exakte Begriffe wie Artikelnummern oder Kostenstellen. Beides kombiniert ist deutlich besser als eines allein. Rechte werden vor der Rückgabe pro Treffer geprüft.

---

## 4. Datenbankschema

```sql
-- Workspace und Kanäle
workspaces   (id text pk, name text)
channels     (id text pk, seq bigint not null default 0)          -- "doc:…", "table:…", "run:…", "user:…", "workspace:…"

-- Nutzer, Rollen, Agenten (5.8)
users        (id text pk, external_id text unique, name text, email text, active bool)
agents       (id text pk, workspace_id text fk, name text, client_id text unique, active bool)
roles        (id text pk, workspace_id text fk, key text, name text,
              unique (workspace_id, key))
member_roles (workspace_id text, member_id text,                  -- usr_… oder agt_…
              role_id text fk roles on delete restrict,
              primary key (member_id, role_id))

-- Tabellen (2)
tables       (id text pk, workspace_id text fk, key text, name text,
              display_column text, version int,
              unique (workspace_id, key))
columns      (id text pk, table_id text fk on delete cascade, key text, name text,
              type jsonb, required bool, "unique" bool, "default" jsonb,
              position text collate "C",
              unique (table_id, key))
rows         (id text pk, table_id text fk on delete cascade, position text collate "C",
              values jsonb not null,                              -- { col_id: value }
              version int, created_at, created_by jsonb, updated_at, updated_by jsonb)
row_links    (from_row text fk rows on delete cascade, column_id text,
              to_row text fk rows,                                -- Referenzspalten, für on_delete und Rückwärtssuche
              primary key (from_row, column_id))

-- Dokumente (3)
documents    (id text pk, workspace_id text fk, title text,
              owner_workflow text null, owner_step text null, version int, updated_at)
blocks       (id text pk, doc_id text fk on delete cascade, parent_id text null,
              position text collate "C", type text, props jsonb, version int)

-- Formulare (4)
form_drafts       (form_block text, scope text,                   -- "run:run_42" oder "user:u_1"
                   values jsonb, version int, updated_at,
                   primary key (form_block, scope))
form_submissions  (id text pk,                                    -- = submission_id vom Client
                   form_block text, run_id text null, button text,
                   values jsonb, results jsonb, actor jsonb, created_at)

-- Workflows (5)
workflows          (id text pk, workspace_id text fk, key text, name text,
                    draft jsonb, latest_version int null,
                    unique (workspace_id, key))
workflow_versions  (workflow_id text fk, version int, definition jsonb,
                    documents jsonb,                              -- eingefrorene Blöcke je Dokument
                    published_at, published_by jsonb,
                    primary key (workflow_id, version))
runs               (id text pk, workflow_id text fk, version int, title text, status text,
                    current_step text null, result jsonb null,
                    parent_run text null, parent_step text null, parent_block text null,
                    input jsonb, steps jsonb,
                    started_by jsonb, started_by_id text,                 -- für "Meine Anträge"
                    started_at, ended_at, updated_at)
tasks              (id text pk, run_id text fk runs, step text, status text,
                    candidate_users text[], candidate_roles text[], excluded text[],
                    claimed_by jsonb null, claimed_by_id text null,
                    created_at, due_at null, completed_by jsonb null, completed_at null,
                    outcome text null)
run_events         (id text pk, run_id text fk runs, at timestamptz, actor jsonb,
                    type text, step text null, outcome text null, label text null, text text null)
notifications      (id text pk, recipient_id text, run_id text null, task_id text null,
                    type text, payload jsonb, created_at, read_at null)

-- Querschnitt
oplog        (channel text, seq bigint, batch_id text, actor jsonb,
              ops jsonb, inverse jsonb, created_at,
              primary key (channel, seq))
batches      (batch_id text pk, result jsonb, created_at)          -- Idempotenz, nach 24 h aufräumen
imports      (id text pk, workspace_id text, actor jsonb, source text,   -- "xlsx" | "docx"
              ops jsonb, created jsonb, warnings jsonb,
              used_at timestamptz null, created_at)                -- nach 1 h bzw. nach Verbrauch aufräumen
references   (source_kind text, source_id text, target_kind text, target_id text, via text)
embeddings   (id bigserial pk, workspace_id text, source_kind text, source_id text,
              block_ids text[], chunk_hash text, content text,
              tsv tsvector generated always as (to_tsvector('german', content)) stored,
              embedding vector(N), model text, updated_at)
```

**Indizes:**

```sql
create index on blocks (doc_id, parent_id, position);
create index on rows (table_id, position);
create index on rows using gin (values jsonb_path_ops);           -- Filter auf Spaltenwerte
create index on row_links (to_row);                               -- on_delete, Rückwärtssuche
create index on references (target_kind, target_id);
create index on runs (workflow_id, status);
create index on runs (started_by_id, status);                     -- "Meine Anträge"
create index on tasks (status) where status = 'open';
create index on tasks using gin (candidate_users) where status = 'open';
create index on tasks using gin (candidate_roles) where status = 'open';
create index on run_events (run_id, at);
create index on notifications (recipient_id, created_at) where read_at is null;
create index on embeddings using hnsw (embedding vector_cosine_ops);
create index on embeddings using gin (tsv);
```

**Anmerkungen:**

- `position` mit `collate "C"`, damit Fractional Indexes byteweise sortiert werden, genau wie im Frontend.
- Zeilenwerte liegen in einem `jsonb` pro Zeile. Das passt zu den Partial Updates (`values || $patch`) und braucht keine Migration, wenn ein Agent Spalten anlegt. Filter aus `table_view` werden in `jsonb`-Ausdrücke übersetzt (`values->>'col_x' = $1`). Für häufig gefilterte Spalten können später Ausdrucks-Indizes angelegt werden.
- **Aufgabenliste** eines Nutzers ist eine Abfrage, keine gespeicherte Liste:
  ```sql
  select * from tasks
  where status = 'open'
    and not ($me = any(excluded))
    and ($me = any(candidate_users) or candidate_roles && $my_roles)
    and (claimed_by_id is null or claimed_by_id = $me);
  ```
  Rollen bleiben in `candidate_roles` als Rollen stehen. Wer eine Rolle neu bekommt, sieht offene Aufgaben dadurch sofort.
- `row_links` spiegelt Referenzspalten, weil Postgres keine Fremdschlüssel in `jsonb` kennt. Die Pipeline schreibt beide Stellen in derselben Transaktion. `on_delete` setzt die Domäne um, nicht die Datenbank, weil das Verhalten pro Spalte verschieden ist.

---

## 5. Frontend

### 5.1 Bibliotheken

| Zweck | Bibliothek |
|---|---|
| Basis | React, Vite, TypeScript |
| Workflows | `@xyflow/react`, Layout mit `elkjs` |
| Live-Zustand | `zustand` (ein Store für alle abonnierten Kanäle) |
| Nicht-live Daten | `@tanstack/react-query` (Suche, Listen, Run-Historie) |
| Tabellen | `@tanstack/react-table` mit `@tanstack/react-virtual` |
| Text-Editor | TipTap (ProseMirror), eine schlanke Instanz pro Textblock |
| Drag & Drop von Blöcken | `@dnd-kit/core` |
| Typen | `openapi-typescript` erzeugt TS-Typen aus dem FastAPI-OpenAPI-Schema; WS-Nachrichten werden als Pydantic-Modelle ins Schema aufgenommen |
| Sortierpositionen | `fractional-indexing` |
| IDs | `ulid` |

### 5.2 Struktur

```
frontend/src/
  api/              # generierte Typen, REST-Client
  sync/
    socket.ts       # Verbindung, Reconnect mit since, Heartbeat
    store.ts        # Zustand: confirmed + pending (7.4 der Logik)
    apply.ts        # Ops auf den lokalen Zustand anwenden (Spiegel der Backend-Handler)
    presence.ts
  documents/
    DocumentView.tsx
    blocks/         # eine Komponente pro Blocktyp
      Paragraph.tsx Heading.tsx List.tsx TableView.tsx
      Form.tsx Field.tsx LineItems.tsx WorkflowBlock.tsx
  tables/           # Tabellen-Editor (Schema + Zeilen)
  workflows/
    WorkflowEditor.tsx   # React Flow, bearbeitet den Entwurf
    RunView.tsx          # Run-Fortschritt + aktuelles Schritt-Dokument
    RunTimeline.tsx      # Verlauf aus run_events, Kommentare
  inbox/
    TaskList.tsx         # "Meine Aufgaben" (Kanal user:<id>)
    MyRequests.tsx       # "Meine Anträge" mit Status
    Notifications.tsx
  search/
```

**Navigation und Arbeitsmappe:** Home listet nur Dokumente. Ein Dokument ist eine Arbeitsmappe: Eine Blatt-Leiste am unteren Rand zeigt Blatt 1 = Dokument, danach je ein Blatt pro eingebetteter Tabelle (`table_view`, voller Tabellen-Editor) und pro eingebettetem Workflow (`workflow`, Graph und Abläufe), jeweils in Dokumentreihenfolge und ohne Doppelte (`documents/workbookModel.ts`). Das aktive Blatt steht in der Adresse (`/documents/:id?sheet=<Tabellen- oder Workflow-ID>`). Die Routen `/tables/:id` und `/workflows/:id` bleiben für Links aus Suche, Benachrichtigungen und Import und bieten „In Dokument einbetten …“ an. Das Datenmodell bleibt unverändert, ein Besitzer-Feld gibt es nicht.

### 5.3 Sync-Store

```ts
type ChannelState<T> = {
  seq: number;          // zuletzt bestätigte seq
  confirmed: T;         // Server-Stand
  pending: OpBatch[];   // eigene, noch nicht bestätigte Batches
  view: T;              // confirmed + pending, daraus rendert React
};
```

- Komponenten lesen nur `view`. Eine eigene Änderung erzeugt einen Batch mit clientseitigen IDs, wendet ihn auf `view` an und schickt ihn ab.
- `sync/apply.ts` ist die TypeScript-Fassung der Backend-Handler, aber **ohne** Validierung. Weicht das Ergebnis ab, gewinnt der Server: Mit dem `ack` bzw. den eingehenden Ops wird `view` neu berechnet.
- **Tests gegen Abweichungen:** Ein gemeinsamer Ordner `spec/fixtures/*.json` enthält Fälle der Form „Zustand + Ops → erwarteter Zustand“. Dieselben Dateien laufen in `pytest` und `vitest`. Das gilt auch für Ausdrücke (4.5) und Text-OT.

### 5.4 Textblöcke

- Jeder Text-Block (`paragraph`, `heading`, `list_item`) ist eine eigene, kleine TipTap-Instanz. Das passt zum flachen Blockmodell: Ein Block ist eine Einheit für Änderungen, Präsenz und Konflikte.
- ProseMirror-Transaktionen werden in `text.edit`-Ops übersetzt und gebündelt (z. B. alle 300 ms oder bei Pause).
- Enter → Rest des Blocks per `text.edit` entfernen und als neuen Block einfügen (`block.insert`). Backspace am Anfang → Text an den vorigen Block anhängen (`text.edit` dort) und den Block löschen (`block.delete`).
- Fokus auf einen Block sendet `presence { editing: blk_x }`. Blöcke, die gerade jemand anderes bearbeitet, zeigen dessen Namen, bleiben für Menschen aber bearbeitbar (gleichzeitiges Tippen). Agenten bekommen dort `BLOCK_IN_USE`.

### 5.5 Formulare

- `Field` und `LineItems` lesen ihren Wert aus dem Draft im Kanal `run:<id>` bzw. aus dem eigenen User-Draft und schreiben jede Änderung als `draft.set` (entprellt).
- Die Button-Sichtbarkeit (4.3) wird im Frontend **nach derselben Regel** berechnet, nur für die Anzeige. Ob ein Submit erlaubt ist, entscheidet der Server.
- Feldfehler aus der Submit-Antwort (`errors: { "artikel[2].preis": "…" }`) werden direkt am Feld angezeigt.

### 5.6 Workflows mit React Flow

**Editor (Entwurf):**

- Jeder Schritt ist ein Custom Node mit Name, Zuständigen (Personen, Rollen, Antragsteller, Ausdruck), Vier-Augen-Markierung, Frist und einer Vorschau des Schritt-Dokuments. Doppelklick öffnet das Dokument, ein Seitenpanel bearbeitet die Zuständigkeit.
- Jeder **Outcome-Button** des Formulars im Schritt erscheint als eigener Ausgangs-Handle. Eine Kante von diesem Handle zu einem anderen Schritt ist eine `Transition { from, on, to }`. Damit sieht man sofort, welcher Button wohin führt und welcher noch keinen Übergang hat.
- Ein fester Node „Ende“ steht für `to: "end"`.
- Änderungen am Graphen sind `workflow.update`-Ops. Fehler aus `validate_workflow` werden an Nodes und Kanten markiert.
- **Ergänzung zur Logik:** Node-Positionen werden in `definition.layout: { [step_key]: { x, y } }` gespeichert. Das Feld ist nur für die Anzeige und wird von der Engine ignoriert. Fehlt es (z. B. weil ein Agent den Workflow angelegt hat), berechnet `elkjs` ein Layout.

**Run-Ansicht:**

- Derselbe Graph schreibgeschützt: erledigte Schritte mit Button-Label und Person, aktueller Schritt hervorgehoben mit Zuständigen, „in Bearbeitung von …“ und Frist, Sub-Runs als aufklappbare Nodes.
- Daneben der Verlauf (`RunTimeline`) und das Schritt-Dokument: bearbeitbar, wenn `can_act` gilt, sonst schreibgeschützt. So sieht der Antragsteller dieselbe Ansicht wie die Zuständigen, nur ohne Buttons.

### 5.7 Aufgaben und Anträge

- Der Client abonniert nach dem Login immer `user:<eigene id>`. Darüber kommen neue Aufgaben, Statusänderungen der eigenen Anträge und Benachrichtigungen.
- **„Meine Aufgaben“:** offene Aufgaben mit Run-Titel, Schritt, Frist, Claim-Status. Aktionen: Öffnen, Übernehmen, Freigeben.
- **„Meine Anträge“:** eigene Runs mit `status_label` des aktuellen Schritts, Zuständigen, Ergebnis. Ein Klick öffnet die Run-Ansicht.
- Ein Zähler an der Navigation zeigt offene Aufgaben und ungelesene Benachrichtigungen.

---

## 6. Querschnittsthemen

- **Auth:** Nutzer per OAuth/OIDC, Agenten per OAuth 2.1 Client Credentials mit Scopes pro Workspace (passt zur MCP-Spezifikation). Der WebSocket authentifiziert sich beim Verbindungsaufbau mit einem kurzlebigen Token.
- **Undo:** Das Op-Log speichert inverse Ops. Undo ist ein neuer Batch mit den inversen Ops und `base`-Versionen. Hat sich der Block seither geändert, wird Undo abgelehnt statt fremde Änderungen zu überschreiben.
- **Fristen** (procrastinate, periodisch jede Minute): offene Aufgaben mit `due_at < now()` ohne `overdue`-Event bekommen das Event und Benachrichtigungen. Optional E-Mail-Versand als eigener Job pro Benachrichtigung.
- **Aufräumen** (procrastinate, periodisch): abgelaufene Präsenz, `batches` älter als 24 h, `imports` älter als 1 h, Drafts abgeschlossener Runs, Op-Log komprimieren (Snapshots), sobald das Log für einen Kanal sehr lang wird.
- **Lokale Entwicklung:** `docker compose` mit dem Image `pgvector/pgvector`, Backend mit `uvicorn --reload`, Frontend mit `vite`, Vite-Proxy für `/api`, `/ws`, `/mcp`.

---

## 7. Reihenfolge der Umsetzung

1. **Fundament:** Postgres-Schema, Pydantic-Schemas, Op-Pipeline mit Op-Log, Tabellen-Ops. Tests mit gemeinsamen Fixtures.
2. **MCP-Server** mit Tabellen-Tools. Ab hier können Agenten das System testen.
3. **Dokumente:** Blöcke, Markdown-Import und -Export, REST und MCP.
4. **Echtzeit:** WebSocket-Hub, LISTEN/NOTIFY, Sync-Store im Frontend, Dokument- und Tabellen-Ansicht.
5. **Formulare:** Drafts, Ausdrücke, Submit mit Actions. Danach **Import** von Excel und Word (2.9), weil er Tabellen, Dokumente und Formulare erzeugt.
6. **Nutzer und Rollen:** Anmeldung, Rollen, Agenten-Identitäten inkl. `on_behalf_of`.
7. **Workflows:** Definition, Veröffentlichen, Runs, Aufgaben, Events, Aufgabenliste und „Meine Anträge“, React-Flow-Editor und Run-Ansicht. Danach ist das Bestellbeispiel (10) komplett lauffähig, im Browser und per MCP.
8. **Suche:** Embeddings-Worker und hybride Suche.
9. **Feinschliff:** Text-OT mit mehreren gleichzeitigen Schreibern, Präsenz, Undo, Sub-Workflows, Fristen.

## 8. Offene technische Entscheidungen

- **Embedding-Modell:** extern per API oder selbst gehostet? Bestimmt die Vektordimension `N` und ob Dokumente das Haus verlassen.
- **Zeilen pro Tabelle:** Bis zu einigen hunderttausend Zeilen ist `jsonb` mit GIN-Index unproblematisch. Werden Tabellen deutlich größer, lohnen sich Ausdrucks-Indizes pro gefilterter Spalte.
- **Mandantentrennung:** `workspace_id` in jeder Abfrage genügt am Anfang. Row-Level Security in Postgres wäre eine zusätzliche Sicherung.
