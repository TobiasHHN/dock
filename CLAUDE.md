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

- Demo-Rollen: `einkauf`, `mitarbeiter`, `chef`

## Konventionen

- Der API-Vertrag (Pydantic-Schemas für Ops, Blöcke, WebSocket-Nachrichten, siehe `technische-umsetzung.md` 2.2/2.3) ist verbindlich. Änderungen nur nach Absprache.
- Keine neuen Dependencies ohne Absprache.
- Keine Logs, `node_modules` oder `.venv` einlesen.
- Nach jedem Task `/clear`; Prompts nennen Task-ID und Dateien.

## Befehle

```
docker compose up                                   # db, backend (:8000), worker, frontend (:5173)
docker compose down -v && docker compose up -d && python demo/seed.py   # frische Demo-Umgebung
npx openapi-typescript http://localhost:8000/openapi.json -o frontend/src/api/types.ts
```

(Befehle entstehen mit Phase 0; bei Abweichungen diese Datei anpassen. Ordnernamen wie in `technische-umsetzung.md` 2.2 und 5.2.)
