# Hackathon-Plan: Dokument-Plattform – Demo „Bestellfreigabe im Einkauf“

## Kontext

5 Engineers, ca. 1 Arbeitstag, Demo am Freitag (in 48 h). Jeder hat Claude Code (Pro-Plan, 20 $).

Gezeigt wird eine Plattform, auf der Dokumente aus Text, Tabellen, Formularen, Unterschriften und Workflows bestehen. Agents bedienen sie per MCP.

**Demo-Story:**
1. Anna (Rolle `einkauf`) gibt ihrem Agent die beiden Dateien `Bestelluebersicht.xlsx` und `Bestellformular.docx` plus eine Beschreibung des Prozesses, zum Beispiel: *„Wenn jemand das Bestellformular einreicht, muss der Chef digital unterschreiben, danach wird der Antrag in die Übersicht eingetragen.“*
2. Der Agent schickt beides **in einem API-Aufruf** an das Backend. Das Backend erzeugt daraus **zwei Dokumente**:
   - **„Bestellanträge – Übersicht“**: Beschreibungstext, Tabelle aus der Excel-Datei (die Übersicht aller Anträge) und ein Workflow-Block, der auf das Formular verweist
   - **„Bestellformular“**: Text und Formularfelder aus der Word-Datei, zum Ausfüllen
3. Ben (Rolle `mitarbeiter`) sagt seinem Agent: *„Bitte das Bestellformular ausfüllen: 2× Dell-Monitor, Kostenstelle 4711.“* Der Agent füllt das Formular aus und reicht es ein. Dadurch entsteht „Antrag #N“, und der Workflow startet.
4. Alle Nutzer mit der Rolle `chef` bekommen **live per WebSocket** eine Benachrichtigung, öffnen „Antrag #N“ und unterschreiben digital. Unterschreiben darf nur, wer laut JWT die Rolle `chef` hat.
5. Der Workflow trägt den Antrag in Annas Übersichtstabelle ein. Annas offener Browser zeigt die neue Zeile sofort, ebenfalls per WebSocket.

**Vorgaben:**
- Sign-up und Sign-in mit **JWT und Rollen** (`einkauf`, `mitarbeiter`, `chef`)
- Postgres + pgvector für die Dokumentsuche
- Frontend in React + React Flow
- Backend in Python/FastAPI im Docker-Container
- Semi-Kollaboration über **WebSockets**: Schreiben läuft per REST, Änderungen werden per WebSocket an alle verteilt

---

## Architektur auf einen Blick

```
docker-compose
 ├─ db      pgvector/pgvector:pg16        (init.sql beim ersten Start)
 ├─ api     FastAPI (uvicorn, 1 Worker)   :8000  REST + WebSocket /ws
 ├─ worker  selbes Image, python -m app.worker   (Workflow-Engine + Embeddings)
 └─ web     Vite + React + React Flow     :5173
mcp/        Python FastMCP (stdio), läuft lokal bei jedem Agent, ruft die REST-API

Event-Fluss:  REST-Schreibzugriff / Worker
                 → pg_notify('events', json)
                 → API lauscht (LISTEN events)
                 → WebSocket-Hub verteilt an alle Abonnenten
```

Postgres `LISTEN/NOTIFY` ersetzt einen Message-Broker. Auch Änderungen aus dem Worker-Container (Workflow trägt eine Zeile ein, erzeugt eine Benachrichtigung) landen so live im Browser. Redis ist nicht nötig.

### Repo-Struktur

```
docker-compose.yml
CLAUDE.md                     ← Stack, Regeln, Verweis auf schemas.py (für Claude Code)
db/init.sql                   ← komplettes Schema (keine Migrationen)
api/
  Dockerfile, pyproject.toml
  app/main.py                 ← FastAPI-App, Router einbinden, CORS, Start des LISTEN-Tasks
  app/db.py                   ← SQLAlchemy 2 Engine/Session
  app/models.py               ← ORM (inkl. pgvector.sqlalchemy.Vector)
  app/schemas.py              ← Pydantic = API-Vertrag inkl. WebSocket-Events (Single Source of Truth)
  app/auth.py                 ← signup/login, JWT erzeugen/prüfen, current_user, require_role()
  app/events.py               ← publish(event) → pg_notify; Hub: Verbindungen + Abos; LISTEN-Loop
  app/routers/{auth,documents,blocks,processes,forms,search,workflows,notifications,ws}.py
  app/services/{parsing,embeddings,engine}.py
  app/worker.py               ← Loop: Runs + Embedding-Jobs
mcp/server.py                 ← FastMCP-Tools → REST
web/src/
  api/types.ts                ← generiert: npx openapi-typescript http://localhost:8000/openapi.json
  api/ws.ts                   ← WebSocket-Client: Verbinden, Abonnieren, Reconnect, Query-Cache aktualisieren
  pages/{Login,Signup,Home,Document}.tsx
  blocks/{TextBlock,TableBlock,FormBlock,SignatureBlock,WorkflowBlock}.tsx
demo/
  Bestelluebersicht.xlsx, Bestellformular.docx   ← selbst erstellt, passend zum Parser
  seed.py                     ← Users anna/ben/chef mit Rollen, Fallback-Templates, Demo-JWTs ausgeben
  prompts.md                  ← exakte Agent-Prompts für die Demo
```

### Datenmodell (`db/init.sql`)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
users(id, email UNIQUE, name, password_hash,
      role TEXT CHECK (role IN ('einkauf','mitarbeiter','chef')), created_at)
documents(id, title, kind TEXT,                 -- overview|form|antrag|plain
          owner_id, version INT DEFAULT 0, created_at, updated_at)
blocks(id, document_id, position FLOAT, type TEXT,          -- text|table|form|signature|workflow
       content JSONB, plain_text TEXT, version INT,
       updated_by, updated_via TEXT,             -- 'ui' | 'agent' | 'workflow'
       updated_at, locked_by, locked_until)
block_embeddings(block_id PK, document_id, embedding VECTOR(384))
workflow_templates(id, name, version, graph JSONB, description TEXT, created_by, created_at)
workflow_instances(id, document_id, block_id, template_id,
                   bindings JSONB)              -- {"form_document_id", "form_block_id", "table_block_id"}
workflow_runs(id, instance_id, template_id, parent_run_id, status,   -- ready|running|waiting|waiting_child|done|failed
              context JSONB, current_node, created_at, updated_at)
run_steps(id, run_id, node_id, status, output JSONB, created_at)
notifications(id, user_id, text, link, read BOOL, created_at)
jobs(id, kind, payload JSONB, status, created_at)                     -- z. B. reembed_document
```

Gegenüber der vorherigen Version fällt die Tabelle `presence` weg. Wer ein Dokument offen hat, weiß der WebSocket-Hub im Speicher. Die Spalte `users.token` entfällt ebenfalls, weil JWTs nicht gespeichert werden.

### Block-Inhalte (`content` JSONB)

| type | content |
|---|---|
| text | `{"md": "## Überschrift\nText …"}` |
| table | `{"columns":["Nr","Artikel","Menge","Kostenstelle","Antragsteller","Status","Unterzeichnet"], "rows":[[…]]}` |
| form | `{"fields":[{"key":"artikel","label":"Artikel","type":"text","required":true}], "values":{}, "submitted_by":null}` |
| signature | `{"signer_role":"chef", "signed_by":null, "image":null, "signed_at":null, "content_hash":null}` |
| workflow | `{"instance_id":"…", "template_id":"…"}` |

### Auth: JWT mit Rollen

- **Bibliothek:** `PyJWT` (HS256), Secret aus der Umgebungsvariable `JWT_SECRET`, Passwörter mit `bcrypt`.
- `POST /auth/signup` `{email, name, password, role}`: Für die Demo darf man die Rolle bei der Registrierung wählen, per Dropdown im Sign-up-Formular.
- `POST /auth/login` → `{access_token, user}`. Claims: `sub` (User-ID), `name`, `role`, `exp` (24 h).
- Es gibt keine Refresh-Tokens. Nach 24 h meldet man sich neu an.
- Dependencies:
  - `current_user` liest `Authorization: Bearer <jwt>` und prüft die Signatur.
  - `require_role("chef")` schützt die Endpunkte, die eine Rolle verlangen.
- **Wo Rollen greifen:**
  - Unterschreiben ist nur für `signature.signer_role == user.role` erlaubt, sonst kommt **403**.
  - `POST /processes` (Prozess anlegen) ist nur für die Rolle `einkauf` erlaubt.
  - Der Node `notify` adressiert eine Rolle (`config.role: "chef"`), nicht einen einzelnen Nutzer.
- **Frontend:** JWT in `localStorage`. Den Namen und die Rolle zeigt es aus dem dekodierten Token im Header an.
- **MCP:** `seed.py` gibt Demo-JWTs für Anna und Ben aus, mit 7 Tagen Laufzeit. Sie kommen als `API_TOKEN` in die jeweilige MCP-Konfiguration.
- **WebSocket:** Browser können beim WebSocket keine Header setzen, deshalb läuft die Anmeldung über `ws://…/ws?token=<jwt>`.

### Semi-Kollaboration über WebSockets

**Prinzip:** Geschrieben wird weiter per REST, mit `base_version` und **409** bei Konflikten. Der WebSocket dient nur zum **Verteilen** von Änderungen und für Presence und Sperren. So bleibt die Logik einfach und testbar.

- **Verbindung:** eine Verbindung pro Browser-Tab bzw. pro MCP-Client: `GET /ws?token=<jwt>`.
- **Client → Server:**
  - `{"type":"subscribe","document_id":"…"}` und `{"type":"unsubscribe",…}`
  - `{"type":"lock","block_id":"…"}` und `{"type":"unlock","block_id":"…"}`: weiche Sperre, verfällt nach 30 s ohne Erneuerung oder sofort beim Verbindungsabbruch
- **Server → Client** (Pydantic-Modelle in `schemas.py`):
  - `block.upserted {document_id, block, version}`
  - `block.deleted {document_id, block_id, version}`
  - `document.created {document}`, zum Beispiel wenn ein Antrag entsteht. Geht an alle, damit sich der Home-Screen aktualisiert.
  - `presence {document_id, users:[{id,name,role}]}`
  - `lock {document_id, block_id, user|null}`
  - `run.updated {run_id, instance_id, status, current_node}`
  - `notification {notification}`: geht nur an den Nutzerkanal des Empfängers
- **Kanäle im Hub:** `doc:<id>` (Abonnenten des Dokuments), `user:<id>` (automatisch beim Verbinden), `global` (für `document.created`).
- **Ablauf:** Jede Schreiboperation in API oder Worker ruft `events.publish(channel, event)` auf. Das läuft über `pg_notify('events', …)`. Der LISTEN-Task in der API verteilt an die Sockets.
  - Payload-Limit von pg_notify (8 KB) beachten: Bei großen Blöcken nur die `block_id` senden, der Client lädt den Block per REST nach.
- **Reconnect:** Bricht die Verbindung ab, wartet der Client exponentiell länger und lädt danach das offene Dokument einmal komplett per REST neu, als Catch-up. Er abonniert dann neu.
- **Wichtig:** uvicorn mit **einem** Worker-Prozess starten (`--workers 1`), weil der Hub im Speicher liegt.

### Prozess-Anlage aus Excel + Word + Beschreibung

**Endpunkt:** `POST /processes` (nur Rolle `einkauf`), multipart mit folgenden Feldern:
- `overview_file` (xlsx)
- `form_file` (docx)
- `description` (Text)
- `workflow` (JSON-Graph, optional, siehe unten)

**Das Backend macht in einer Transaktion:**
1. Excel parsen (`openpyxl`, erstes Sheet). Daraus wird der `table`-Block. Fehlende Spalten `Status`, `Unterzeichnet` und `Antragsteller` ergänzt das Backend automatisch.
2. Word parsen (`python-docx`). Absätze werden zu `text`-Blöcken. Zeilen `Label: ____` und Tabellenzeilen werden zu Feldern eines `form`-Blocks.
3. Dokument **„Bestellformular“** (`kind=form`) mit diesen Blöcken anlegen.
4. Workflow-Template anlegen und validieren, aus `workflow` oder aus dem Standard-Template, siehe unten.
5. Dokument **„Bestellanträge – Übersicht“** (`kind=overview`) anlegen: Beschreibung als `text`-Block, dann `table`-Block, dann `workflow`-Block. Dazu kommt eine Workflow-Instanz mit den Bindings `form_document_id`, `form_block_id` und `table_block_id`.
6. Für beide Dokumente `document.created` veröffentlichen und das Neu-Einbetten anstoßen.
7. Antwort: `{overview_document_id, form_document_id, template_id, warnings:[…]}`, zum Beispiel mit der Warnung „Feld ‚Datum‘ ohne Typ erkannt“.

**Wer macht aus der Beschreibung den Workflow-Graphen? Empfehlung: der Agent.**

Annas Agent (Claude Code) ist das LLM. Das MCP-Tool `create_process` beschreibt die erlaubten Node-Typen und enthält einen Beispielgraphen. Der Agent erzeugt aus der Beschreibung den Graphen und schickt ihn als Feld `workflow` mit. Bei Validierungsfehlern antwortet das Backend mit **422** und verständlichen Meldungen. Der Agent korrigiert dann selbst.

Damit braucht das Backend keinen API-Key und keine eigene LLM-Integration. Der Pro-Plan von Claude Code enthält keine API-Credits.

**Fallback:** Fehlt `workflow`, nimmt das Backend das Standard-Template „Bestellfreigabe“ aus dem Seed und speichert die Beschreibung nur als Text. So funktioniert die Demo auch, wenn der Agent hakt.

### Suche (pgvector)

- Embeddings mit `fastembed` (ONNX, leicht, ohne API-Key) und dem Modell `paraphrase-multilingual-MiniLM-L12-v2` (384 Dimensionen, kann Deutsch). Das Modell wird beim Docker-Build vorab geladen.
- Der Worker bettet `plain_text` jedes Blocks ein.
- `GET /search?q=` sortiert nach Kosinus-Distanz und gruppiert pro Dokument. Als Fallback dient die Postgres-Volltextsuche über `plain_text`.

### Workflow-Engine (Worker)

- Endlosschleife, alle 1 s: `SELECT … FROM workflow_runs WHERE status='ready' FOR UPDATE SKIP LOCKED`. Der Worker führt Nodes aus, bis der Run fertig ist oder warten muss. Jeder Statuswechsel veröffentlicht `run.updated`.
- Graph-Format: `{"nodes":[{"id","type","config"}], "edges":[{"from","to"}]}`. Die Abarbeitung ist linear entlang der Edges.
- 6 Node-Typen:
  - `trigger.form_submitted`
  - `doc.create_from_form`: erzeugt „Antrag #N“ (`kind=antrag`) mit den Formularwerten (schreibgeschützt) und einem `signature`-Block mit `signer_role` aus `config`
  - `subworkflow` (`config.template_id`): legt einen Kind-Run an, der Eltern-Run geht auf `waiting_child`. Ist das Kind fertig, wird der Eltern-Run wieder `ready`.
  - `notify` (`config.role`, `config.text`): legt eine Benachrichtigung für jeden Nutzer mit dieser Rolle an und veröffentlicht sie an `user:<id>`
  - `wait.signature`: Status `waiting`. `POST …/sign` setzt den Run wieder auf `ready`.
  - `table.append_row` (`config.mapping`, Ziel aus den Instanz-Bindings): veröffentlicht `block.upserted` an `doc:<overview>`
- `validate_graph(graph)` prüft: genau ein Trigger, keine unbekannten Typen, Pflicht-`config` vorhanden, alle Edges zeigen auf existierende Nodes, keine Zyklen bei Sub-Workflows. Die Fehlermeldungen sind für Agents lesbar formuliert.

**Workflow der Demo:**

```
[trigger.form_submitted]
  → [doc.create_from_form  signer_role=chef]
  → [subworkflow "Unterschrift einholen"]
        → [notify role=chef "Neuer Bestellantrag #N"]
        → [wait.signature]
  → [table.append_row  Status=freigegeben, Unterzeichnet={{signed_by}}]
```

---

## Rollen im Team

| Kürzel | Rolle | Schwerpunkt |
|---|---|---|
| **P1** | Backend Core | Docker, DB, JWT-Auth mit Rollen, Dokument-/Block-API, **WebSocket-Hub + LISTEN/NOTIFY** |
| **P2** | Frontend Shell | Login/Sign-up (mit Rolle), Home-Screen, Dokument-Screen, WebSocket-Client |
| **P3** | Blöcke + Prozess-Anlage | Tabellen-, Formular- und Unterschriftsblock (Frontend), Parsing + `POST /processes`, Endpunkte zum Einreichen und Unterschreiben (Backend) |
| **P4** | Workflow | Engine/Worker, Template-Validierung, Workflow-Block mit React Flow, Benachrichtigungen |
| **P5** | Suche + MCP + Demo | pgvector-Suche, MCP-Server, Demo-Dateien, Seed, Prompts, Proben |

---

## Phase 0: Fundament (0:00–1:00, **alle zusammen, sequenziell**)

Hier lässt sich nicht parallelisieren. Ohne den gemeinsamen Vertrag arbeiten alle aneinander vorbei.

| ID | Task | Owner | Done wenn |
|---|---|---|---|
| 0.1 | Demo-Story und Prompts final abnicken (15 min) | alle | `demo/prompts.md` steht als Entwurf |
| 0.2 | Repo + `docker-compose.yml` (db, api, worker, web), Hello-World-FastAPI, Vite-App | P1 (+P2 für `web/`) | `docker compose up` → `localhost:5173` und `localhost:8000/docs` erreichbar |
| 0.3 | `db/init.sql` komplett (Schema oben) | P1 + P4 | Tabellen existieren nach `docker compose up` |
| 0.4 | `app/schemas.py`: alle Pydantic-Modelle **inklusive WebSocket-Events** + **Stub-Router**, die Fixtures zurückgeben | P3 + P5 (mit allen abgestimmt) | `/docs` zeigt alle Endpunkte, Frontend kann gegen Stubs bauen |
| 0.5 | Interne Schnittstellen als Funktions-Stubs: `events.publish(channel, event)`, `engine.create_template(graph)`, `engine.attach(doc_id, block_id, template_id, bindings)`, `engine.start_runs_for_form(doc_id, block_id, values, user)`, `engine.resume_after_signature(run_id)`, `embeddings.enqueue_reembed(doc_id)` | P1 + P4 + P5 | Signaturen in `app/events.py` / `app/services/*.py`, Body `pass` |
| 0.6 | Stub für `current_user`: liefert immer Anna (Rolle `einkauf`), bis 1.1 fertig ist; Header `X-Demo-User: ben\|chef` schaltet um | P1 | alle können ohne echtes Login testen |
| 0.7 | `CLAUDE.md`: Stack, Ordner, „schemas.py ist der Vertrag“, „keine neuen Dependencies ohne Absprache“, „uvicorn --workers 1“, Startbefehle | P2 | im Repo |
| 0.8 | `api/types.ts` generieren (`openapi-typescript`) | P2 | TS-Typen im Frontend nutzbar |
| 0.9 | Format der Demo-Dateien festlegen (Spalten der Excel-Datei, Feldzeilen im Word-Dokument) | P3 + P5 | kurze Notiz in `demo/prompts.md` |

**Exit-Kriterium:** Alle können `git pull && docker compose up` ausführen und gegen die Stubs entwickeln.

---

## Phase 1: Paralleles Bauen (1:00–4:00, **voll parallel**)

### P1: Backend Core
| ID | Task | Abhängig von |
|---|---|---|
| 1.1 | `auth.py`: signup (mit Rolle), login, JWT erzeugen/prüfen (PyJWT), `current_user`, `require_role()`; Stub aus 0.6 entfernen | 0.3 |
| 1.2 | Dokumente: `GET /documents` (Filter `kind`), `POST /documents`, `GET /documents/{id}` (mit Blöcken), `DELETE`, `GET /documents/{id}?format=md` | 1.1 |
| 1.3 | Blöcke: `POST /documents/{id}/blocks` (mit position), `PATCH /blocks/{id}` (base_version → 409), `DELETE`, Neusortieren; jede Änderung → `events.publish` + `enqueue_reembed` + `plain_text` | 1.2 |
| 1.4 | `events.py`: `publish()` über `pg_notify`; LISTEN-Task beim Start der App (asyncpg oder psycopg async) | 0.5 |
| 1.5 | `routers/ws.py`: `/ws?token=`, JWT prüfen, Hub mit Kanälen `doc:`, `user:`, `global`; subscribe/unsubscribe; Presence beim Abonnieren und Trennen; Sperren mit 30-s-Ablauf und Freigabe beim Trennen | 1.1, 1.4 |

### P2: Frontend Shell
| ID | Task | Abhängig von |
|---|---|---|
| 2.1 | Routing (`/login`, `/signup`, `/`, `/doc/:id`), API-Client mit Bearer-JWT, TanStack Query, Name + Rolle im Header | 0.8 |
| 2.2 | Login- und Sign-up-Seiten (Sign-up mit Rollen-Dropdown) | 2.1 (gegen Stub, später 1.1) |
| 2.3 | Home: Dokumentliste gruppiert nach `kind` (Übersichten, Formulare, Anträge), „Neues Dokument“, Suchfeld (`/search`), Glocke (`/notifications` + Live-Events) | 2.1 |
| 2.4 | Dokument-Screen im HackMD-Stil: Blöcke untereinander, Klick auf Textblock → Markdown-Textarea, sonst gerendert (`react-markdown`); „+ Block“-Menü; Block-Registry `type → Komponente`; Kennzeichnung „via Agent“ / „via Workflow“ aus `updated_via` | 2.1 |
| 2.5 | `api/ws.ts`: Verbindung mit Token, Abonnieren beim Öffnen eines Dokuments, Events in den Query-Cache schreiben, Reconnect mit Catch-up; Avatare der anwesenden Nutzer, gesperrte Blöcke grau mit „X bearbeitet“, Sperre beim Fokus, Hinweis bei 409 | 2.4 (gegen Fake-Events, später 1.5) |

### P3: Blöcke + Prozess-Anlage
| ID | Task | Abhängig von |
|---|---|---|
| 3.1 | `TableBlock`: editierbare Zellen, Zeile/Spalte hinzufügen, speichert per `PATCH`; neue Zeilen kurz hervorheben | 2.4 (Registry-Schnittstelle aus 0.4) |
| 3.2 | `FormBlock`: Felder ausfüllen, Pflichtfelder prüfen, „Einreichen“ → `POST /documents/{id}/forms/{block_id}/submit` | 0.4 |
| 3.3 | `SignatureBlock`: `react-signature-canvas`, nur aktiv, wenn die Rolle aus dem JWT der `signer_role` entspricht (sonst „Wartet auf Unterschrift: Chef“); „Unterzeichnen“ → `POST …/signatures/{block_id}/sign`; zeigt danach Bild, Name, Zeit und Hash | 0.4 |
| 3.4 | `services/parsing.py`: `parse_overview_xlsx()` → table-Block; `parse_form_docx()` → Text-Blöcke + form-Block | 0.9 |
| 3.5 | `POST /processes` (Ablauf siehe oben), in einer Transaktion, Antwort mit Warnungen | 3.4, 1.2, 0.5 |
| 3.6 | Endpunkt `submit`: speichert Werte, ruft `engine.start_runs_for_form`. Endpunkt `sign`: prüft die Rolle (403), speichert die Unterschrift und den Hash des Antragsinhalts, ruft `engine.resume_after_signature` | 0.5, 1.3 |

### P4: Workflow
| ID | Task | Abhängig von |
|---|---|---|
| 4.1 | `validate_graph()` mit agentenfreundlichen Fehlermeldungen; `engine.create_template()`; `GET /templates`, `GET /templates/{id}`, `POST /templates/validate` | 0.3 |
| 4.2 | `engine.attach()` (Instanz + workflow-Block), `GET /runs/{id}`, `GET /documents/{id}/runs` | 4.1 |
| 4.3 | `worker.py` + `engine.py`: Run-Loop, 6 Node-Handler, Sub-Workflow mit `parent_run_id`, `run_steps` schreiben, `run.updated` veröffentlichen | 0.5 |
| 4.4 | `start_runs_for_form` und `resume_after_signature` implementieren | 4.3 |
| 4.5 | Benachrichtigungen: `GET /notifications`, `POST /notifications/{id}/read`; Node `notify` adressiert Rollen und veröffentlicht an `user:<id>` | 4.3, 1.4 |
| 4.6 | `WorkflowBlock` (React Flow, nur Anzeige): Graph automatisch gelayoutet (Dagre oder einfache Spalten), Node-Farbe live aus `run.updated`, Liste der letzten Runs, Klick auf Sub-Workflow zeigt den Kind-Graph, Link zum Formular-Dokument aus den Bindings | 4.2 |

### P5: Suche + MCP + Demo
| ID | Task | Abhängig von |
|---|---|---|
| 5.1 | `services/embeddings.py` mit fastembed; Worker verarbeitet `jobs` vom Typ `reembed_document` | 0.3, 0.5 |
| 5.2 | `GET /search?q=` (Vektor + Volltext-Fallback, Top 10 Dokumente mit Snippet) | 5.1 |
| 5.3 | `mcp/server.py` (FastMCP, `API_URL`/`API_TOKEN` aus der Umgebung). Tools: **`create_process(overview_xlsx_path, form_docx_path, description, workflow?)`** (liest die lokalen Dateien, schickt sie an `POST /processes`; Tool-Beschreibung mit Node-Typen + vollständigem Beispielgraphen), `validate_workflow`, `search_documents`, `list_documents`, `get_document` (Markdown mit Block-IDs), `update_block`, `fill_and_submit_form`, `get_run`. Jeder Request sendet `X-Client: mcp`, damit das Backend `updated_via='agent'` setzt | 0.4 |
| 5.4 | Demo-Dateien `Bestelluebersicht.xlsx` (2–3 Beispielanträge) und `Bestellformular.docx` erstellen, genau nach dem Format aus 0.9 | 0.9 |
| 5.5 | `demo/seed.py`: Nutzer anna/ben/chef (Passwort `demo`, passende Rollen), Standard-Templates „Unterschrift einholen“ + „Bestellfreigabe“, Demo-JWTs ausgeben; zwei MCP-Konfigurationen (`demo/anna/.mcp.json`, `demo/ben/.mcp.json`) | 1.1, 4.1 |

---

## Phase 2: Integration (4:00–4:45, **alle zusammen, sequenziell**)

| ID | Task | Owner |
|---|---|---|
| 2.I1 | Alle Stubs durch echte Implementierungen ersetzt, `main` gemergt, `docker compose down -v && up && python demo/seed.py` | P1 leitet |
| 2.I2 | Story **ohne Agent** durchspielen: `POST /processes` per `curl` mit beiden Dateien → zwei Dokumente da → als Ben Formular im Browser einreichen → Chef-Browser bekommt die Benachrichtigung live → unterschreiben → neue Zeile erscheint live in Annas Browser | alle, P5 protokolliert Bugs |
| 2.I3 | Bugliste priorisieren und verteilen (nur Blocker für die Story) | alle |

---

## Phase 3: Agent-Flows und Feinschliff (4:45–6:30, **parallel**)

| ID | Task | Owner |
|---|---|---|
| 3.F1 | Annas Agent-Flow: Dateien + Beschreibung → Agent baut den Graphen → `create_process`. Bei 422 korrigiert der Agent selbst. Prompt so lange proben, bis er stabil ist | P5 + P4 |
| 3.F2 | Bens Agent-Flow: `search_documents("Bestellformular")` → `get_document` → `fill_and_submit_form` | P5 + P3 |
| 3.F3 | Kennzeichnung „via Agent“ / „via Workflow“ an Blöcken, Anträgen und Tabellenzeilen | P1 + P2 |
| 3.F4 | Live-Effekte: Toast bei neuer Benachrichtigung, Zähler an der Glocke, Workflow-Nodes färben sich, neue Dokumente erscheinen auf dem Home-Screen | P2 + P4 |
| 3.F5 | Fehler-Blocker aus 2.I3 | jeweilige Owner |
| 3.F6 | **Stretch** (nur wenn alles läuft): Formeln in der Tabelle (HyperFormula im Frontend); Workflow-Template im React-Flow-Canvas editieren; manueller Upload auf dem Home-Screen als Alternative zum Agent | P3 / P4 / P2 |

---

## Phase 4: Freeze und Proben (6:30–8:00, **sequenziell**)

| ID | Task | Owner |
|---|---|---|
| 4.Z1 | Feature-Freeze, Tag `demo-v1` | P1 |
| 4.Z2 | Komplette Demo dreimal von frischer DB durchspielen (`down -v`, `up`, `seed`) | alle |
| 4.Z3 | Backup-Video der kompletten Demo aufnehmen | P5 |
| 4.Z4 | Demo-Rechner vorbereiten: 3 Browserprofile (Anna, Ben, Chef) nebeneinander, damit die Live-Updates sichtbar sind; 2 Terminals mit Claude Code (Anna-MCP, Ben-MCP) | P2 + P5 |

**Freitag, 1 h vor der Demo:** frische DB, Seed, neue Demo-JWTs in die MCP-Konfigurationen, kurzer Durchlauf, Video bereithalten.

---

## Was sequenziell bleiben muss

1. **Phase 0 komplett vor allem anderen.** Schema, `schemas.py` mit Events, Docker und interne Stubs sind Voraussetzung für alles.
2. **1.4/1.5 WebSocket-Hub vor dem echten Live-Test.** Bis dahin arbeitet P2 mit Fake-Events, und alle anderen rufen `events.publish` schon auf.
3. **0.9 Dateiformat vor 3.4 Parser und 5.4 Demo-Dateien.** Danach arbeiten P3 und P5 parallel.
4. **4.1 Validierung vor 3.5 `POST /processes`**, weil der Endpunkt den Graphen validiert. Bis dahin akzeptiert der Stub jeden Graphen.
5. **4.3/4.4 Engine vor 3.F1/3.F2.** Die Agent-Flows ergeben nur Sinn, wenn der Workflow läuft.
6. **Phase 2 Integration vor Phase 3.** Erst durchspielen, dann den Agent einbinden.

## Claude Code mit dem Pro-Plan effizient nutzen

- `CLAUDE.md` + `schemas.py` sind der Kontext. Prompts nennen die Task-ID und die Dateien, zum Beispiel „Implementiere Task 1.5 in `api/app/routers/ws.py` laut `schemas.py`“.
- Nach jedem Task `/clear`. Keine Logs, `node_modules` oder `.venv` lesen lassen.
- Für Routine-Tasks das Standardmodell nutzen. Teure Modelle nur für den WebSocket-Hub (1.4/1.5), die Engine (4.3) und den Parser (3.4).
- P5 hält Kontingent für Phase 3 und den Freitag zurück, weil P5 die Agent-Demo selbst mit Claude Code fährt.
- Wer am Limit ist, übernimmt manuelle Tests, die Demo-Dateien oder Reviews.

## Verifikation (Definition of Done der Demo)

Von frischer DB (`docker compose down -v && docker compose up -d && python demo/seed.py`):

1. Sign-up mit Rollenwahl funktioniert. Login als `anna`, `ben` und `chef` liefert ein JWT mit der richtigen Rolle.
2. Ben versucht, einen Antrag zu unterschreiben, und bekommt **403**. Ben versucht `POST /processes` und bekommt **403**.
3. Annas Agent ruft `create_process` mit beiden Dateien und der Beschreibung auf. Es entstehen „Bestellanträge – Übersicht“ (Text + Tabelle aus Excel + Workflow-Block mit Graph inklusive Sub-Workflow) und „Bestellformular“ (ausfüllbare Felder). Beide erscheinen ohne Neuladen auf dem Home-Screen.
4. Suche nach „Formular für Bestellungen“ findet „Bestellformular“ (pgvector, nicht nur exakter Treffer).
5. Zwei Browser öffnen dasselbe Dokument. Ein Edit erscheint im anderen sofort per WebSocket. Ein gesperrter Block ist dort schreibgeschützt, und die Sperre verschwindet, wenn der andere Tab geschlossen wird.
6. Bens Agent füllt das Formular aus und reicht es ein. „Antrag #N“ entsteht, gekennzeichnet „via Agent“, und der Run steht auf `waiting`.
7. Im Chef-Browser erscheint die Benachrichtigung live. Der Chef unterschreibt, und der Run geht auf `done`.
8. Annas offener Browser zeigt die neue Tabellenzeile mit Status „freigegeben“ und dem Unterzeichner, ohne Neuladen.
9. WebSocket-Server neu starten: Clients verbinden sich neu und holen den aktuellen Stand nach.
