# CLAUDE.md

Projekt: Dokument-Plattform, Demo „Bestellfreigabe im Einkauf“. Details in `hackathon-plan.md` (Aufgaben, Architektur) und `dokument-plattform-architektur.md`.

**Verbindlich: Dependency-Check, Branches und Plan-Update laut `@AGENTS.md`** (Modellwahl dort gilt für Codex/Antigravity, hier die Claude-Variante). Kurzfassung:

## Vor jeder Änderung: Fachdokumente lesen

Bevor ein Agent Code oder Doku ändert, muss er die Logik und das Gesamtbild kennen:

- `anwendungslogik.md`: Fachlogik (Objekte, Regeln, Operationen, Echtzeit-Abgleich). Lesen, sobald Verhalten, Datenmodell oder Workflows verstanden werden müssen.
- `technische-umsetzung.md`: Umsetzung auf den Stack (API, DB, WebSocket, Frontend). Lesen vor jeder Implementierung. Die Abschnittsnummern verweisen auf `anwendungslogik.md`.
- Bei Widersprüchen gelten diese beiden vor `dokument-plattform-architektur.md` (teilweise überholt).
- Nur die für den Task relevanten Abschnitte lesen, aber die „Kernentscheidungen“ (Abschnitt 0) immer.

## Workflow-Regeln

- **Modelle (Claude Code):** Orchestrator = Opus 5.5. Sub-Agents = Sonnet 5.5 für anspruchsvolle und Standard-Implementierung, Haiku 5.5 für triviale Tasks. Nie Opus für Sub-Agents. (`AGENTS.md` ist für Codex/Antigravity und nennt die Modelle nur als Stufen.)
- **Branches:** Alles auf Branches (`task/<id>-<kurzname>`), nie direkt auf `main`. Commit-Messages beginnen mit der Task-ID.
- **Plan pflegen:** Ist ein Task fertig, in `hackathon-plan.md` ein ✅ hinter die Task-ID setzen (im selben Branch). Teilweise Erledigtes = 🚧 und zählt nicht als fertig.
- **Dependencies:** Vor jedem Task die Spalte „Abhängig von“ prüfen. Ist eine Abhängigkeit nicht mit ✅ markiert, **nicht weitermachen**, stattdessen Blocker melden und einen freien Task vorschlagen.

## Stack

- Backend: Python/FastAPI in Docker, `uvicorn --workers 1`, SQLAlchemy 2, PyJWT
- DB: Postgres + pgvector (`db/init.sql`, keine Migrationen); Events über `pg_notify` / `LISTEN`
- Frontend: React + Vite + React Flow, TanStack Query
- MCP: Python FastMCP (stdio) in `mcp/server.py`, ruft die REST-API
- Rollen: `einkauf`, `mitarbeiter`, `chef` (JWT)

## Konventionen

- `api/app/schemas.py` ist der API-Vertrag (inkl. WebSocket-Events). Änderungen nur nach Absprache.
- Keine neuen Dependencies ohne Absprache.
- Schreiben per REST, Verteilen per WebSocket.
- Keine Logs, `node_modules` oder `.venv` einlesen.
- Nach jedem Task `/clear`; Prompts nennen Task-ID und Dateien.

## Befehle

```
docker compose up                                   # db, api (:8000), worker, web (:5173)
docker compose down -v && docker compose up -d && python demo/seed.py   # frische Demo-Umgebung
npx openapi-typescript http://localhost:8000/openapi.json -o web/src/api/types.ts
```

(Struktur und Befehle entstehen mit Phase 0; bei Abweichungen diese Datei anpassen.)
