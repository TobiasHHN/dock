# AGENTS.md – Regeln für alle Agents

Gilt für jeden Agent (Orchestrator und Sub-Agents), egal welches Tool ihn startet. Die Single Source of Truth für Aufgaben ist `hackathon-plan.md`.

## 1. Modellwahl

Gilt für **ChatGPT Codex** (OpenAI) und **Antigravity** (Google). Modellnamen ändern sich ständig, deshalb wird nach Stufen gewählt. Es gilt jeweils das, was im Tool aktuell im Modell-Picker angeboten wird.

| Stufe | Einsatz | Codex (OpenAI) | Antigravity (Google) |
|---|---|---|---|
| **S1 – Orchestrator** | Planung, Aufteilung, Dependency-Check, Review, Merge | stärkstes GPT-/Codex-Modell, hohes Reasoning | stärkstes Gemini-Pro-Modell (Deep Think/High, falls verfügbar) |
| **S2 – Anspruchsvoll** | Ausführung von Operationen 1.2, Echtzeit-Hub 1.5, Sync-Store 2.3, Import 3.7, Engine 4.2/4.3, Architekturentscheidungen | nächst kleineres GPT-/Codex-Modell, mittleres bis hohes Reasoning | nächst kleineres Gemini-Pro-Modell bzw. Pro mit mittlerem Thinking |
| **S3 – Standard** | Endpunkte, Komponenten, Tests | Standard-Codex-Modell, mittleres Reasoning | Gemini Pro/Flash, Standard-Thinking |
| **S4 – Trivial** | Boilerplate, Umbenennungen, Doku, Formatierung, Code-Suche | kleinstes „mini“-Modell, niedriges Reasoning | Gemini Flash / Flash-Lite |

Regeln:
- Der Orchestrator läuft immer auf S1. Sub-Agents laufen mindestens eine Stufe darunter, nie auf S1.
- Im Zweifel eine Stufe kleiner wählen. Scheitert der Task, eine Stufe hochgehen, nicht gleich auf S1.
- Der Orchestrator implementiert nicht selbst, sondern delegiert (Codex: Sub-Agents/Cloud-Tasks, Antigravity: Agent Manager), prüft Ergebnisse und mergt.
- Steht eine Stufe im Tool nicht zur Verfügung, die nächstgelegene kleinere nehmen und das im Bericht erwähnen.

## 2. Vor jedem Task: Dependencies prüfen

1. Task in `hackathon-plan.md` suchen und die Spalte **„Abhängig von“** lesen. Das gilt auch für Phasen-Abhängigkeiten aus „Was sequenziell bleiben muss“.
2. Jede genannte Abhängigkeit muss im Plan als abgeschlossen markiert sein (siehe Abschnitt 4).
3. Ist **auch nur eine** Abhängigkeit nicht abgeschlossen: **nicht weitermachen.** Stattdessen:
   - nichts implementieren, auch nicht „schon mal vorbereitend“,
   - dem Orchestrator bzw. Nutzer melden, welche Task-ID blockiert ist und wovon,
   - einen anderen, freien Task vorschlagen.
4. Stubs aus Phase 0 gelten nicht als erfüllte Abhängigkeit, wenn der Task die echte Implementierung braucht.

## 3. Git: alles auf Branches

- Nie direkt auf `main` committen oder pushen.
- Ein Branch pro Task: `task/<id>-<kurzname>`, z. B. `task/1.5-ws-hub`. Parallele Agents arbeiten in getrennten Branches (bei Bedarf in einem eigenen Worktree).
- Kleine, fokussierte Commits. Commit-Message beginnt mit der Task-ID: `1.5: WebSocket-Hub mit Presence und Sperren`.
- Branch erst nach erfülltem „Done wenn“-Kriterium abschließen. Merge nach `main` über den Orchestrator (bzw. PR) nach Review.
- Der Plan-Update (Abschnitt 4) gehört in denselben Branch wie der Task.
- Keine Force-Pushes, kein Umschreiben fremder Branches.

## 4. Plan aktualisieren

Sobald ein Task abgeschlossen ist, aktualisiert der ausführende Agent `hackathon-plan.md` im selben Branch:

- Ein Task gilt als abgeschlossen, wenn sein „Done wenn“-Kriterium (bzw. der Zweck der Zeile) erfüllt und verifiziert ist (Code läuft, Tests/`docker compose up` grün).
- Markierung: **✅ hinter der Task-ID** in der ersten Spalte, z. B. `| 1.1 ✅ |`. Offene Tasks bleiben unmarkiert. Teilweise erledigte Tasks bekommen **🚧** und gelten für Dependencies **nicht** als abgeschlossen.
- Nur die Markierung ändern, plus bei Bedarf eine kurze Notiz (Branch-Name, Abweichungen) in der Zeile oder darunter. Keine Tasks umformulieren oder löschen.
- Wird der Plan inhaltlich ungenau, den Orchestrator informieren statt still umzuschreiben.

## 5. Arbeitsweise

- **Vor jeder Änderung die Fachdokumente lesen:** `anwendungslogik.md` (Fachlogik: Objekte, Regeln, Operationen, Echtzeit-Abgleich) und `technische-umsetzung.md` (Umsetzung auf den Stack, Abschnittsnummern verweisen auf die Logik). Immer Abschnitt 0 „Kernentscheidungen“, sonst die für den Task relevanten Abschnitte. Der Plan enthält keine Logik, nur Features und Aufgaben mit Verweisen. Widerspricht der Plan den beiden Dokumenten, gelten sie.
- Prompt/Auftrag nennt die Task-ID und die betroffenen Dateien. Nur diese Dateien anfassen.
- Der API-Vertrag (Schemas laut `technische-umsetzung.md` 2.2/2.3) ist verbindlich. Änderungen daran nur nach Absprache mit dem Orchestrator.
- `anwendungslogik.md` und `technische-umsetzung.md` haben Vorrang vor `CLAUDE.md` und dem Plan.
- Keine neuen Dependencies ohne Absprache.
- Keine Logs, `node_modules` oder `.venv` einlesen.
- Am Ende kurz berichten: Task-ID, Branch, was erledigt ist, was offen ist, ob der Plan aktualisiert wurde.

## 6. Stack, Befehle und Besonderheiten

Stack und Struktur stehen in `technische-umsetzung.md`. Zusätzlich gilt:

- Demo-Rollen: `einkauf`, `mitarbeiter`, `chef`. Demo-Nutzer: Anna (`einkauf`), Ben (`mitarbeiter`), Chef (`chef`), siehe `demo/prompts.md`.
- Bis Task 1.1 fertig ist, wählt der Header `X-Demo-User: anna|ben|chef` den Nutzer (`backend/app/auth.py`, Default Anna).
- Alle REST-Endpunkte sind Stubs mit Beispieldaten (`backend/app/api/routers.py`, `stub_data.py`), bis der jeweilige Task sie ersetzt. Die Stub-Schnittstellen in `domain/`, `ops/`, `realtime/`, `imports/`, `search/` und `mcp/` haben leere Rümpfe mit Task-Verweis im Docstring.
- Gemeinsame Testfälle für Backend und Frontend liegen in `spec/fixtures/` (Format: `spec/fixtures/README.md`). Neue Fälle immer dort ergänzen.
- `db/init.sql` ist die Quelle der Wahrheit für das Schema. `db/models.py` (SQLAlchemy) und `db/migrations/` aus `technische-umsetzung.md` 2.2 gibt es bewusst noch nicht und entstehen mit Task 1.2, falls die Handler sie brauchen (keine Migrationen, Schemaänderung = `init.sql` + `docker compose down -v`).
- `mcp` ist auf `<2` gepinnt, weil `technische-umsetzung.md` die `FastMCP`-API voraussetzt. Embedding-Dimension 384 (`db/init.sql`, `backend/app/config.py`).

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
