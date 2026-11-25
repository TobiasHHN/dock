# Hackathon-Plan: Dokument-Plattform – Demo „Bestellfreigabe im Einkauf“

## Kontext

5 Engineers, ca. 1 Arbeitstag, Demo am Freitag (in 48 h). Jeder hat Claude Code (Pro-Plan, 20 $).

Gezeigt wird eine Plattform, auf der Dokumente aus Text, Tabellen, Formularen, Unterschriften und Workflows bestehen. Agents bedienen sie per MCP.

**Demo-Story:**
1. Anna (Einkauf) lädt `Bestelluebersicht.xlsx` und `Bestellformular.docx` hoch. Daraus entstehen zwei Dokumente.
2. Annas Agent erzeugt aus einer Beschreibung den Workflow „Bestellfreigabe“ und hängt ihn an die Übersicht.
3. Bens Agent füllt das Formular aus und reicht es ein. Der Workflow startet.
4. Der Chef wird benachrichtigt und unterschreibt digital.
5. Der Workflow trägt die Bestellung in Annas Tabelle ein.

**Vorgaben:**
- Einfaches Sign-up/Sign-in (bcrypt + zufälliges Token, kein JWT)
- Postgres + pgvector für die Dokumentsuche
- Frontend in React + React Flow
- Backend in Python/FastAPI im Docker-Container
- Semi-Kollaboration per Polling

---

## Architektur auf einen Blick

```
docker-compose
 ├─ db      pgvector/pgvector:pg16        (init.sql beim ersten Start)
 ├─ api     FastAPI (uvicorn)             :8000  REST + OpenAPI
 ├─ worker  selbes Image, python -m app.worker   (Workflow-Engine + Embeddings)
 └─ web     Vite + React + React Flow     :5173
mcp/        Python FastMCP (stdio), läuft lokal bei jedem Agent, ruft die REST-API
```

### Repo-Struktur

```
docker-compose.yml
CLAUDE.md                     ← Stack, Regeln, Verweis auf schemas.py (für Claude Code)
db/init.sql                   ← komplettes Schema (keine Migrationen)
api/
  Dockerfile, pyproject.toml
  app/main.py                 ← FastAPI-App, Router einbinden, CORS
  app/db.py                   ← SQLAlchemy 2 Engine/Session
  app/models.py               ← ORM (inkl. pgvector.sqlalchemy.Vector)
  app/schemas.py              ← Pydantic = API-Vertrag (Single Source of Truth)
  app/auth.py                 ← signup/login, Dependency current_user
  app/routers/{documents,blocks,import_,forms,search,workflows,notifications}.py
  app/services/{parsing,embeddings,engine}.py
  app/worker.py               ← Loop: Runs + Embedding-Jobs
mcp/server.py                 ← FastMCP-Tools → REST
web/src/
  api/types.ts                ← generiert: npx openapi-typescript http://localhost:8000/openapi.json
  pages/{Login,Signup,Home,Document}.tsx
  blocks/{TextBlock,TableBlock,FormBlock,SignatureBlock,WorkflowBlock}.tsx
demo/
  Bestelluebersicht.xlsx, Bestellformular.docx   ← selbst erstellt, passend zum Parser
  seed.py                     ← Users anna/ben/chef + Fallback-Template
  prompts.md                  ← exakte Agent-Prompts für die Demo
```

### Datenmodell (`db/init.sql`)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
users(id, email UNIQUE, name, password_hash, token UNIQUE, created_at)
documents(id, title, owner_id, version INT DEFAULT 0, created_at, updated_at)
blocks(id, document_id, position FLOAT, type TEXT,          -- text|table|form|signature|workflow
       content JSONB, plain_text TEXT, version INT,
       updated_by, updated_at, locked_by, locked_until)
block_embeddings(block_id PK, document_id, embedding VECTOR(384))
presence(document_id, user_id, last_seen, PRIMARY KEY(document_id,user_id))
workflow_templates(id, name, version, graph JSONB, created_by, created_at)
workflow_instances(id, document_id, block_id, template_id, bindings JSONB)
workflow_runs(id, instance_id, template_id, parent_run_id, status,   -- ready|running|waiting|waiting_child|done|failed
              context JSONB, current_node, created_at, updated_at)
run_steps(id, run_id, node_id, status, output JSONB, created_at)
notifications(id, user_id, text, link, read BOOL, created_at)
jobs(id, kind, payload JSONB, status, created_at)                     -- z. B. reembed_document
```

### Block-Inhalte (`content` JSONB)

| type | content |
|---|---|
| text | `{"md": "## Überschrift\nText …"}` |
| table | `{"columns":["Nr","Artikel",…], "rows":[["11","Laptop",…]]}` |
| form | `{"fields":[{"key":"artikel","label":"Artikel","type":"text"}], "values":{}, "submitted_by":null}` |
| signature | `{"signer_role":"chef", "signed_by":null, "image":null, "signed_at":null, "content_hash":null}` |
| workflow | `{"instance_id":"…", "template_id":"…"}` |

### Semi-Kollaboration (Polling)

- `GET /documents/{id}/changes?since=<version>` alle 2 s. Antwort: neue Dokumentversion, geänderte Blöcke, gelöschte IDs und Presence (wer ist im Dokument, wer sperrt welchen Block). Der Aufruf zählt gleichzeitig als Presence-Heartbeat.
- `POST /blocks/{id}/lock` setzt eine weiche Sperre für 30 s. Der Client erneuert sie, solange editiert wird. Andere sehen „Anna bearbeitet …“, der Block ist für sie schreibgeschützt.
- `PATCH /blocks/{id}` mit `base_version`. Bei Abweichung antwortet der Server mit **409**. Der Client übernimmt dann die Serverversion und zeigt einen Hinweis.
- Jede Blockänderung erhöht `blocks.version` und `documents.version` und legt einen `reembed_document`-Job an.

### Auth

- `POST /auth/signup` und `POST /auth/login`: Das Passwort wird mit bcrypt gehasht (eine Zeile mit dem Paket `bcrypt`). Das Token ist `secrets.token_urlsafe()` und steht in `users.token`.
- Requests senden `Authorization: Bearer <token>`. Die Dependency `current_user` prüft es.
- Das Frontend speichert das Token in `localStorage`. Der MCP-Server bekommt das Token über die Umgebungsvariable `API_TOKEN`. So handelt Bens Agent als Ben.

### Suche (pgvector)

- Embeddings mit `fastembed` (ONNX, leicht, ohne API-Key) und dem Modell `paraphrase-multilingual-MiniLM-L12-v2` (384 Dimensionen, kann Deutsch). Das Modell wird beim Docker-Build vorab geladen.
- Der Worker bettet `plain_text` jedes Blocks ein.
- `GET /search?q=` sortiert nach Kosinus-Distanz und gruppiert pro Dokument. Als Fallback dient die Postgres-Volltextsuche über `plain_text`.

### Workflow-Engine (Worker)

- Endlosschleife, alle 1 s: `SELECT … FROM workflow_runs WHERE status='ready' FOR UPDATE SKIP LOCKED`. Der Worker führt Nodes aus, bis der Run fertig ist oder warten muss.
- Graph-Format: `{"nodes":[{"id","type","config"}], "edges":[{"from","to"}]}`. Die Abarbeitung ist linear entlang der Edges.
- 6 Node-Typen:
  - `trigger.form_submitted`
  - `doc.create_from_form`: erzeugt „Bestellung #N“ mit Formularwerten und Unterschriftsblock
  - `subworkflow` (`config.template_id`): legt einen Kind-Run an, der Eltern-Run geht auf `waiting_child`. Ist das Kind fertig, wird der Eltern-Run wieder `ready`.
  - `notify` (`config.user`, `config.text`)
  - `wait.signature`: Status `waiting`. `POST …/sign` setzt den Run wieder auf `ready`.
  - `table.append_row` (`config.document_id`, `block_id`, `mapping`)
- `validate_graph(graph)` prüft: genau ein Trigger, keine unbekannten Typen, alle Edges zeigen auf existierende Nodes, keine Zyklen bei Sub-Workflows.

---

## Rollen

| Kürzel | Rolle | Schwerpunkt |
|---|---|---|
| **P1** | Backend Core | Docker, DB, Auth, Dokument-/Block-API, Polling/Kollaboration |
| **P2** | Frontend Shell | Login/Sign-up, Home-Screen, Dokument-Screen, Polling-UI |
| **P3** | Blöcke + Import | Tabellen-, Formular- und Unterschriftsblock (Frontend), xlsx/docx-Parsing und Endpunkte für Einreichen/Unterschreiben (Backend) |
| **P4** | Workflow | Engine/Worker, Template-API, Workflow-Block mit React Flow, Benachrichtigungen |
| **P5** | Suche + MCP + Demo | pgvector-Suche, MCP-Server, Demo-Dateien, Seed, Prompts, Proben |

---

## Phase 0: Fundament (0:00–1:00, **alle zusammen, sequenziell**)

Hier lässt sich nicht parallelisieren. Ohne den gemeinsamen Vertrag arbeiten alle aneinander vorbei.

| ID | Task | Owner | Done wenn |
|---|---|---|---|
| 0.1 | Demo-Story und Prompts final abnicken (15 min) | alle | `demo/prompts.md` steht als Entwurf |
| 0.2 | Repo + `docker-compose.yml` (db, api, worker, web), Hello-World-FastAPI, Vite-App | P1 (+P2 für `web/`) | `docker compose up` → `localhost:5173` und `localhost:8000/docs` erreichbar |
| 0.3 | `db/init.sql` komplett (Schema oben) | P1 + P4 | Tabellen existieren nach `docker compose up` |
| 0.4 | `app/schemas.py`: alle Pydantic-Modelle + **Stub-Router**, die Fixtures zurückgeben | P3 + P5 (mit allen abgestimmt) | `/docs` zeigt alle Endpunkte, Frontend kann gegen Stubs bauen |
| 0.5 | Interne Schnittstellen als Funktions-Stubs festlegen: `engine.start_runs_for_form(doc_id, block_id, values, user)`, `engine.resume_after_signature(run_id)`, `embeddings.enqueue_reembed(doc_id)` | P4 + P5 | Signaturen in `app/services/*.py`, Body `pass` |
| 0.6 | `CLAUDE.md`: Stack, Ordner, „schemas.py ist der Vertrag“, „keine neuen Dependencies ohne Absprache“, Startbefehle | P2 | im Repo |
| 0.7 | `api/types.ts` generieren (`openapi-typescript`) | P2 | TS-Typen im Frontend nutzbar |

**Exit-Kriterium:** Alle können `git pull && docker compose up` ausführen und gegen die Stubs entwickeln.

---

## Phase 1: Paralleles Bauen (1:00–4:00, **voll parallel**)

### P1: Backend Core
| ID | Task | Abhängig von |
|---|---|---|
| 1.1 | `auth.py`: signup, login, `current_user` (bcrypt + Token) | 0.3 |
| 1.2 | Dokumente: `GET /documents`, `POST /documents`, `GET /documents/{id}` (mit Blöcken), `DELETE`, `GET /documents/{id}?format=md` | 1.1 |
| 1.3 | Blöcke: `POST /documents/{id}/blocks` (mit position), `PATCH /blocks/{id}` (base_version → 409), `DELETE`, Neusortieren | 1.2 |
| 1.4 | Polling: `GET /documents/{id}/changes?since=` inkl. Presence-Upsert; `POST/DELETE /blocks/{id}/lock` | 1.3 |
| 1.5 | Bei jeder Blockänderung `enqueue_reembed` aufrufen und `plain_text` füllen | 1.3, 0.5 |

### P2: Frontend Shell
| ID | Task | Abhängig von |
|---|---|---|
| 2.1 | Routing (`/login`, `/signup`, `/`, `/doc/:id`), API-Client mit Bearer-Token, TanStack Query | 0.7 |
| 2.2 | Login- und Sign-up-Seiten | 2.1 (gegen Stub, später 1.1) |
| 2.3 | Home: Dokumentliste, „Neues Dokument“, Upload-Dropzone (`POST /import`), Suchfeld (`/search`), Glocke (`/notifications`) | 2.1 |
| 2.4 | Dokument-Screen im HackMD-Stil: Blöcke untereinander, Klick auf Textblock → Markdown-Textarea, sonst gerendert (`react-markdown`); „+ Block“-Menü (Text/Tabelle/Formular/Unterschrift/Workflow); Block-Registry `type → Komponente` | 2.1 |
| 2.5 | Polling (`refetchInterval: 2000` auf `/changes`), Avatare der anwesenden Nutzer, gesperrte Blöcke grau mit „X bearbeitet“, Lock beim Fokus, Hinweis bei 409 | 2.4 (gegen Stub, später 1.4) |

### P3: Blöcke + Import
| ID | Task | Abhängig von |
|---|---|---|
| 3.1 | `TableBlock`: editierbare Zellen, Zeile/Spalte hinzufügen, speichert per `PATCH` | 2.4 (Registry-Schnittstelle aus 0.4) |
| 3.2 | `FormBlock`: Felder ausfüllen, „Einreichen“ → `POST /documents/{id}/forms/{block_id}/submit` | 0.4 |
| 3.3 | `SignatureBlock`: `react-signature-canvas`, nur für `signer_role` aktiv, „Unterzeichnen“ → `POST …/signatures/{block_id}/sign`; zeigt danach Bild, Name, Zeit und Hash | 0.4 |
| 3.4 | `services/parsing.py`: xlsx mit `openpyxl` (erstes Sheet → table-Block); docx mit `python-docx` (Absätze → Textblöcke, Zeilen `Label: ____` bzw. Tabellenzeilen → form-Block) | 0.4 |
| 3.5 | `POST /import` (multipart) → erzeugt ein Dokument aus den Blöcken | 3.4, 1.2 |
| 3.6 | Endpunkt `submit`: speichert Werte, ruft `engine.start_runs_for_form`; Endpunkt `sign`: speichert die Unterschrift, ruft `engine.resume_after_signature` | 0.5, 1.3 |

### P4: Workflow
| ID | Task | Abhängig von |
|---|---|---|
| 4.1 | Template-API: `GET/POST /templates`, `POST /templates/validate` (`validate_graph`) | 0.3 |
| 4.2 | `POST /workflow-instances` (Template an Dokument + Formular binden, legt workflow-Block an), `GET /runs/{id}`, `GET /documents/{id}/runs` | 4.1 |
| 4.3 | `worker.py` + `engine.py`: Run-Loop, 6 Node-Handler, Sub-Workflow mit `parent_run_id`, `run_steps` schreiben | 0.5 |
| 4.4 | `start_runs_for_form` und `resume_after_signature` implementieren | 4.3 |
| 4.5 | Benachrichtigungen: `GET /notifications`, `POST /notifications/{id}/read`; Node `notify` schreibt sie | 4.3 |
| 4.6 | `WorkflowBlock` (React Flow, nur Anzeige): Graph automatisch gelayoutet (Dagre oder einfache Spalten), Node-Farbe nach Run-Status, Liste der letzten Runs, Klick auf Sub-Workflow zeigt den Kind-Graph | 4.2 |

### P5: Suche + MCP + Demo
| ID | Task | Abhängig von |
|---|---|---|
| 5.1 | `services/embeddings.py` mit fastembed; Worker verarbeitet `jobs` vom Typ `reembed_document` | 0.3, 0.5 |
| 5.2 | `GET /search?q=` (Vektor + Volltext-Fallback, Top 10 Dokumente mit Snippet) | 5.1 |
| 5.3 | `mcp/server.py` (FastMCP, `API_URL`/`API_TOKEN` aus der Umgebung): `search_documents`, `list_documents`, `get_document` (Markdown mit Block-IDs), `import_file(path)`, `create_document`, `update_block`, `create_workflow_template` (Tool-Beschreibung mit Node-Typen + vollständigem Beispielgraphen), `validate_workflow`, `attach_workflow`, `fill_and_submit_form`, `get_run` | 0.4 |
| 5.4 | Demo-Dateien `Bestelluebersicht.xlsx` und `Bestellformular.docx` erstellen, genau passend zum Parser aus 3.4 | 3.4 (Format absprechen) |
| 5.5 | `demo/seed.py`: Nutzer anna/ben/chef (Passwort `demo`), Fallback-Template „Unterschrift einholen“ + „Bestellfreigabe“; MCP-Konfigurationen für Anna und Ben (`.mcp.json` in zwei Ordnern) | 1.1, 4.1 |

---

## Phase 2: Integration (4:00–4:45, **alle zusammen, sequenziell**)

| ID | Task | Owner |
|---|---|---|
| 2.I1 | Alle Stubs durch echte Implementierungen ersetzt, `main` gemergt, `docker compose down -v && up && python demo/seed.py` | P1 leitet |
| 2.I2 | Story **ohne Agent** durchklicken: Upload → Workflow manuell per API/Seed anhängen → als Ben Formular einreichen → als Chef unterschreiben → Zeile in der Tabelle erscheint | alle, P5 protokolliert Bugs |
| 2.I3 | Bugliste priorisieren und verteilen (nur Blocker für die Story) | alle |

---

## Phase 3: Agent-Flows und Feinschliff (4:45–6:30, **parallel**)

| ID | Task | Owner |
|---|---|---|
| 3.F1 | Annas Agent-Flow: `import_file` ×2 → `create_workflow_template` aus der Beschreibung → `attach_workflow`. Prompt so lange proben, bis er stabil ist | P5 + P4 |
| 3.F2 | Bens Agent-Flow: `search_documents("Bestellformular")` → `get_document` → `fill_and_submit_form` | P5 + P3 |
| 3.F3 | „via Agent“-Kennzeichnung (MCP sendet `X-Client: mcp`, wird in `updated_by`/`submitted_by` angezeigt) | P1 + P2 |
| 3.F4 | Live-Effekte: neue Tabellenzeile kurz hervorheben, Glocke mit Zähler, Workflow-Nodes färben sich live | P2 + P4 |
| 3.F5 | Fehler-Blocker aus 2.I3 | jeweilige Owner |
| 3.F6 | **Stretch** (nur wenn alles läuft): Formeln in der Tabelle (HyperFormula im Frontend); Workflow-Template im React-Flow-Canvas editieren | P3 / P4 |

---

## Phase 4: Freeze und Proben (6:30–8:00, **sequenziell**)

| ID | Task | Owner |
|---|---|---|
| 4.Z1 | Feature-Freeze, Tag `demo-v1` | P1 |
| 4.Z2 | Komplette Demo dreimal von frischer DB durchspielen (`down -v`, `up`, `seed`) | alle |
| 4.Z3 | Backup-Video der kompletten Demo aufnehmen | P5 |
| 4.Z4 | Demo-Rechner vorbereiten: 3 Browserprofile (Anna, Ben, Chef), 2 Terminals mit Claude Code (Anna-MCP, Ben-MCP) | P2 + P5 |

**Freitag, 1 h vor der Demo:** frische DB, Seed, kurzer Durchlauf, Video bereithalten.

---

## Was sequenziell bleiben muss

1. **Phase 0 komplett vor allem anderen.** Schema, `schemas.py`, Docker und interne Stubs sind Voraussetzung für alles.
2. **1.1 Auth vor dem echten Durchstich**, weil jeder Endpunkt `current_user` braucht. Bis dahin liefert der Stub immer Nutzer `anna`.
3. **3.4 Parser vor 5.4 Demo-Dateien.** Das Dateiformat sprechen P3 und P5 in Phase 0 ab.
4. **4.3/4.4 Engine vor 3.F1/3.F2.** Die Agent-Flows ergeben nur Sinn, wenn der Workflow läuft.
5. **Phase 2 Integration vor Phase 3.** Erst durchklicken, dann den Agent einbinden.

## Claude Code mit dem Pro-Plan effizient nutzen

- `CLAUDE.md` + `schemas.py` sind der Kontext. Prompts nennen die Task-ID und die Dateien, zum Beispiel „Implementiere Task 4.3 in `api/app/services/engine.py` laut `schemas.py`“.
- Nach jedem Task `/clear`. Keine Logs, `node_modules` oder `.venv` lesen lassen.
- Für Routine-Tasks das Standardmodell nutzen. Teure Modelle nur für Engine (4.3) und Parser (3.4).
- P5 hält Kontingent für Phase 3 und den Freitag zurück, weil P5 die Agent-Demo selbst mit Claude Code fährt.
- Wer am Limit ist, übernimmt manuelle Tests, die Demo-Dateien oder Reviews.

## Verifikation (Definition of Done der Demo)

Von frischer DB (`docker compose down -v && docker compose up -d && python demo/seed.py`):

1. Sign-up eines neuen Nutzers funktioniert. Login als `anna` funktioniert.
2. Anna lädt beide Dateien hoch. Die Übersicht zeigt eine Tabelle, das Formular zeigt ausfüllbare Felder.
3. Suche nach „Formular für Bestellungen“ findet „Bestellformular“ (pgvector, nicht nur exakter Treffer).
4. Zwei Browser öffnen dasselbe Dokument. Ein Edit erscheint im anderen innerhalb von etwa 2 s, ein gesperrter Block ist dort schreibgeschützt.
5. Annas Agent legt den Workflow per Prompt aus `demo/prompts.md` an. Der Workflow-Block zeigt den Graphen inklusive Sub-Workflow.
6. Bens Agent füllt das Formular aus und reicht es ein. „Bestellung #N“ entsteht, und der Run steht auf `waiting`.
7. Der Chef sieht die Benachrichtigung, unterschreibt, und der Run geht auf `done`.
8. Annas Tabelle enthält die neue Zeile mit Status „freigegeben“ und dem Unterzeichner.
