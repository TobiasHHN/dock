# CLAUDE.md

Projekt: Dokument-Plattform, Demo „Bestellfreigabe im Einkauf“. Features und Aufgaben in `hackathon-plan.md`, Logik in `anwendungslogik.md`, Technik in `technische-umsetzung.md`.

**Verbindlich: Dependency-Check, Branches und Plan-Update laut `@AGENTS.md`** (Modellwahl dort gilt für Codex/Antigravity, hier die Claude-Variante). Kurzfassung:

## Vor jeder Änderung: Fachdokumente lesen

Bevor ein Agent Code oder Doku ändert, muss er die Logik und das Gesamtbild kennen:

- `anwendungslogik.md`: Fachlogik (Objekte, Regeln, Operationen, Echtzeit-Abgleich). Lesen, sobald Verhalten, Datenmodell oder Workflows verstanden werden müssen.
- `technische-umsetzung.md`: Umsetzung auf den Stack (API, DB, WebSocket, Frontend). Lesen vor jeder Implementierung. Die Abschnittsnummern verweisen auf `anwendungslogik.md`.
- **Rangfolge bei Widersprüchen:** `anwendungslogik.md` und `technische-umsetzung.md` gelten vor dieser Datei und vor dem Plan. Was dort steht (Stack, Struktur, Bibliotheken, Schema, Prozesse), steht hier bewusst nicht noch einmal.
- Der Plan `hackathon-plan.md` enthält keine Logik, nur Features und Aufgaben mit Verweisen auf diese beiden Dokumente. Widerspricht der Plan ihnen, gelten sie.
- Nur die für den Task relevanten Abschnitte lesen, aber die „Kernentscheidungen“ (Abschnitt 0) immer.

## Workflow-Regeln

- **Modelle (Claude Code):** Orchestrator = Opus 5.5. Sub-Agents = Sonnet 5.5 für anspruchsvolle und Standard-Implementierung, Haiku 5.5 für triviale Tasks. Nie Opus für Sub-Agents. (`AGENTS.md` ist für Codex/Antigravity und nennt die Modelle nur als Stufen.)
- **Branches:** Alles auf Branches (`task/<id>-<kurzname>`), nie direkt auf `main`. Commit-Messages beginnen mit der Task-ID.
- **Plan pflegen:** Ist ein Task fertig, in `hackathon-plan.md` ein ✅ hinter die Task-ID setzen (im selben Branch). Teilweise Erledigtes = 🚧 und zählt nicht als fertig.
- **Dependencies:** Vor jedem Task die Spalte „Abhängig von“ prüfen. Ist eine Abhängigkeit nicht mit ✅ markiert, **nicht weitermachen**, stattdessen Blocker melden und einen freien Task vorschlagen.

## Stack und Struktur

Stack, Bibliotheken, Ordnerstruktur, Schema und Betrieb stehen in `technische-umsetzung.md` (Abschnitte 1, 2, 4, 5). Hier nur, was dort nicht steht:

- Demo-Rollen: `einkauf`, `mitarbeiter`, `chef`. Demo-Nutzer: Anna (`einkauf`), Ben (`mitarbeiter`), Chef (`chef`), siehe `demo/prompts.md`.
- Bis Task 1.1 fertig ist, wählt der Header `X-Demo-User: anna|ben|chef` den Nutzer (`backend/app/auth.py`, Default Anna).
- Alle REST-Endpunkte sind Stubs mit Beispieldaten (`backend/app/api/routers.py`, `stub_data.py`), bis der jeweilige Task sie ersetzt. Die Stub-Schnittstellen in `domain/`, `ops/`, `realtime/`, `imports/`, `search/` und `mcp/` haben leere Rümpfe mit Task-Verweis im Docstring.
- Gemeinsame Testfälle für Backend und Frontend liegen in `spec/fixtures/` (Format: `spec/fixtures/README.md`). Neue Fälle immer dort ergänzen.
- `db/init.sql` ist die Quelle der Wahrheit für das Schema. `db/models.py` und `db/migrations/` aus `technische-umsetzung.md` 2.2 gibt es bewusst noch nicht (entstehen mit Task 1.2, falls nötig; Schemaänderung = `init.sql` + `docker compose down -v`).
- `mcp` ist auf `<2` gepinnt, weil `technische-umsetzung.md` die `FastMCP`-API voraussetzt. Embedding-Dimension 384 (`db/init.sql`, `backend/app/config.py`).

## Konventionen

- Der API-Vertrag (Pydantic-Schemas für Ops, Blöcke, WebSocket-Nachrichten, siehe `technische-umsetzung.md` 2.2/2.3) ist verbindlich. Änderungen nur nach Absprache.
- Keine neuen Dependencies ohne Absprache.
- Keine Logs, `node_modules` oder `.venv` einlesen.
- Nach jedem Task `/clear`; Prompts nennen Task-ID und Dateien.

## Befehle

```
docker compose up -d --build        # db (:5433 auf dem Host), backend (:8000, /docs), worker, frontend (:5173)
docker compose down -v && docker compose up -d   # frische Datenbank (Schema aus db/init.sql)
python demo/seed.py                 # Demo-Nutzer und Templates, entsteht mit Task 5.5

# Backend-Tests (lokale venv: python3 -m venv backend/.venv && backend/.venv/bin/pip install -e "backend[dev]")
backend/.venv/bin/pytest backend

# Frontend (einmalig: cd frontend && npm install)
cd frontend && npm test             # vitest, lädt spec/fixtures
cd frontend && npx tsc --noEmit     # Typecheck
cd frontend && npm run gen:types    # TS-Typen aus http://localhost:8000/openapi.json nach src/api/types.ts
```

Nach jeder Änderung an `backend/app/schemas/` oder an Endpunkten: `npm run gen:types` ausführen und `src/api/types.ts` mit committen.
