# MCP-Konfigurationen für die Demo

`python demo/seed.py` (im Repo-Root, z. B. `backend/.venv/bin/python demo/seed.py`) legt Nutzer, Rollen und Agenten an
und erzeugt hier `anna.json` und `ben.json` sowie `demo/.tokens.json`. Alle drei enthalten Tokens und sind per
`.gitignore` ausgeschlossen. Die Tokens gelten 7 Tage; `python demo/seed.py --fresh-tokens-only` erneuert sie.
Das JWT-Secret muss dem des Backends entsprechen (Default in `backend/app/config.py` und `docker-compose.yml` identisch).

Die Tokens sind Agent-Tokens im Auftrag der Person: Annas Assistent handelt mit den Rechten von Anna (`einkauf`),
Bens Assistent mit denen von Ben (`mitarbeiter`). Im Verlauf erscheint „von Annas Assistent im Auftrag von Anna Beispiel“.

## Nutzung

```
claude --mcp-config demo/mcp/anna.json     # Schritt 1 der Demo (Prozess anlegen)
claude --mcp-config demo/mcp/ben.json      # Schritt 2 und 5 (Antrag, Status)
```

Alternativ ohne Datei (Token aus `demo/.tokens.json`, Feld `agent_token`):

```
claude mcp add --transport http dock http://localhost:8000/mcp --header "Authorization: Bearer <agent_token>"
```

Login im Browser: `anna@demo.local`, `ben@demo.local`, `chef@demo.local`, Passwort `demo`.

Antwortet das Backend mit 401, läuft der Container noch mit einem alten `JWT_SECRET`: `docker compose up -d` erzeugt ihn neu
(`docker compose exec backend env | grep JWT` zeigt den Wert).
