# Bugliste (Phase 2 Integration, 2.I2/2.I3)

Hier landen alle Fehler aus der Integration und den Proben. P5 protokolliert, in 2.I3 priorisiert und verteilt das Team.

## So wird ein Bug eingetragen

1. Nächste freie ID nehmen (`B2`, `B3`, …) und **eine Zeile** in der Tabelle ergänzen.
2. Unter „Details“ einen Abschnitt mit derselben ID anlegen, falls die Zeile nicht reicht (Schritte, Fehlermeldung, Vermutung).
3. Wer einen Bug behebt: Status auf `behoben` setzen, Branch/Commit in die Spalte „Fix“ schreiben. Commit-Message mit der Task-ID **und** der Bug-ID, z. B. `3.F5: B4 Toast fehlt bei neuer Aufgabe`.
4. Nicht reproduzierbar oder kein Fehler: Status `verworfen` mit kurzem Grund.

**Priorität**

- `Blocker`: bricht die Demo-Story (Schritte 1–5 in `hackathon-plan.md`) oder die Definition of Done. Wird in 3.F5 behoben.
- `Hoch`: sichtbar in der Demo, aber umgehbar.
- `Niedrig`: Schönheitsfehler, nur wenn Zeit bleibt.

**Status:** `offen` · `in Arbeit` · `behoben` · `verworfen`

**Bereich:** Backend, Frontend, Echtzeit, Workflow, Formulare, Tabellen, Import, Suche, MCP/Agent, Demo-Daten

## Übersicht

| ID | Titel | Bereich | Priorität | Gefunden in | Owner | Status | Fix |
|---|---|---|---|---|---|---|---|
| B1 | Snapshot von `user:` und `run:` scheitert, sobald Benachrichtigungen oder Run-Events existieren | Echtzeit | Blocker | 2.I2 (E2E-Skript) | P1 | behoben | `task/2.I-integration`, `f1b4077` |

## Details

### B1: Snapshot von `user:` und `run:` scheitert

- **Symptom:** Das Abonnieren von `user:<id>` bzw. `run:<id>` liefert keinen Snapshot, im Backend-Log `JSONDecodeError` in `realtime/snapshots.py`. Folge im Browser: „Meine Aufgaben“, Glocke und Run-Ansicht ohne Live-Daten.
- **Schritte:** frische DB, Seed, Fallback, Run starten und absenden, danach `user:usr_ben` oder `run:<id>` abonnieren.
- **Ursache:** `_JSON_COLUMNS` enthielt `type`. In `run_events`, `notifications` und `blocks` ist `type` Text, kein JSON.
- **Fix:** `type` aus `_JSON_COLUMNS` entfernt, Regressionstest `test_snapshot_row_keeps_text_type_columns` in `backend/tests/test_realtime.py`.

<!-- Vorlage für neue Details:

### B<n>: <Titel>

- **Symptom:**
- **Schritte:**
- **Erwartet:**
- **Ursache (falls bekannt):**
- **Fix:**
-->
