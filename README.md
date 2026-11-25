# dock

Dokument-Plattform (Demo „Bestellfreigabe im Einkauf“). Aufgaben: `hackathon-plan.md`, Logik: `anwendungslogik.md`, Technik: `technische-umsetzung.md`, Regeln für Agents: `AGENTS.md` / `CLAUDE.md`.

```
docker compose up -d --build
```

- Frontend: http://localhost:5173
- API-Doku: http://localhost:8000/docs
- Datenbank (Host-Port): `localhost:5433`, Nutzer/Passwort/DB `dock`

Die Anmeldung läuft über `POST /api/auth/signup` und `/api/auth/login` (Bearer-Token, Task 1.1). Befehle für Tests und Typen: `AGENTS.md` Abschnitt 6.
