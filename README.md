# dock

Dokument-Plattform (Demo „Bestellfreigabe im Einkauf“). Aufgaben: `hackathon-plan.md`, Logik: `anwendungslogik.md`, Technik: `technische-umsetzung.md`, Regeln für Agents: `AGENTS.md` / `CLAUDE.md`.

```
docker compose up -d --build
```

- Frontend: http://localhost:5173
- API-Doku: http://localhost:8000/docs
- Datenbank (Host-Port): `localhost:5433`, Nutzer/Passwort/DB `dock`

Ohne Login wählt der Header `X-Demo-User: anna|ben|chef` den Nutzer (bis Task 1.1). Befehle für Tests und Typen: `AGENTS.md` Abschnitt 6.
