# MCP-Server mit Claude und ChatGPT nutzen

Der Dock-MCP-Server läuft im Backend unter `http://localhost:8000/mcp` (Streamable HTTP). Er erkennt den Nutzer am
Header `Authorization: Bearer <token>`. Die Tokens erzeugt der Seed:

```
docker compose up -d
backend/.venv/bin/python demo/seed.py      # schreibt demo/.tokens.json und demo/mcp/anna.json, ben.json


Für Agenten das Feld `agent_token` aus `demo/.tokens.json` nehmen (Anna = `einkauf`, Ben = `mitarbeiter`, Chef = `chef`).
Im Verlauf steht dann „von Annas Assistent im Auftrag von Anna Beispiel“. Tokens gelten 7 Tage,
`demo/seed.py --fresh-tokens-only` erneuert sie.

## Claude Code

**Variante A: HTTP (am einfachsten)**

```
claude --mcp-config demo/mcp/anna.json     # als Annas Assistent
claude --mcp-config demo/mcp/ben.json      # als Bens Assistent
```

Oder dauerhaft eintragen:

```
claude mcp add --transport http dock http://localhost:8000/mcp --header "Authorization: Bearer <agent_token>"
```

Mit `/mcp` in Claude Code prüfen, ob `dock` verbunden ist.

Einschränkung: Über HTTP liest der Server Dateien im Backend-Container. `import_xlsx`/`import_docx` mit `file_path`
finden `demo/Bestelluebersicht.xlsx` dort nicht, der Agent muss `content_base64` schicken (das macht er nach dem
Hinweis in der Tool-Beschreibung meist selbst).

**Variante B: stdio (lokale Dateipfade funktionieren)**

Der Server läuft dann als lokaler Prozess und liest Dateien direkt vom Rechner:

```
claude mcp add dock \
  --env DOCK_TOKEN=<agent_token> \
  --env DATABASE_URL=postgresql+asyncpg://dock:dock@localhost:5433/dock \
  --env PYTHONPATH=backend \
  -- backend/.venv/bin/python -m app.mcp.server
```

Im Repo-Root starten. Ein Prompt wie „Hier sind `demo/Bestelluebersicht.xlsx` und `demo/Bestellformular.docx` …“
(siehe `demo/prompts.md`) funktioniert so ohne Umweg.

**Claude Desktop:** Dieselbe stdio-Konfiguration in `claude_desktop_config.json` unter `mcpServers` eintragen
(`command` = absoluter Pfad zu `backend/.venv/bin/python`, `args` = `["-m", "app.mcp.server"]`, `env` wie oben, mit
absolutem `PYTHONPATH`).

## ChatGPT

ChatGPT bindet MCP-Server als **Connector im Entwicklermodus** ein (Einstellungen → Apps & Connectors → Erweitert →
Entwicklermodus, dann einen neuen Connector mit der MCP-URL anlegen). Je nach Tarif und Version heißen die Menüs etwas
anders. Zwei Punkte unterscheiden sich von Claude:

1. **Öffentliche HTTPS-URL nötig.** ChatGPT läuft in der Cloud und erreicht `localhost` nicht. Das Backend per
   Tunnel freigeben.
2. **Kein eigener Header.** Im Connector gibt es nur OAuth oder „keine Authentifizierung“, ein Bearer-Token lässt sich
   nicht eintragen. Der Tunnel muss den Header deshalb selbst setzen, z. B. mit ngrok:

```
ngrok http 8000 --request-header-add "Authorization: Bearer <agent_token>"
```

Als Connector-URL dann `https://<id>.ngrok-free.app/mcp` eintragen, Authentifizierung „keine“.

Achtung: Wer diese URL kennt, handelt als der Nutzer des Tokens. Nur für die Demo nutzen und den Tunnel danach beenden.
Für jede Person (Anna, Ben) braucht es einen eigenen Tunnel mit eigenem Token.

Dateien kann ChatGPT nicht per Pfad übergeben. Die Excel- und Word-Datei in den Chat hochladen und den Agenten bitten,
sie als `content_base64` an `import_xlsx`/`import_docx` zu schicken.

## Bekannte Probleme (Stand 26.11.2026)

1. **Import per `file_path` scheitert über HTTP (Demo-kritisch).** Der Server sucht den Pfad im Backend-Container,
   `import_xlsx(file_path="…/demo/Bestelluebersicht.xlsx")` liefert `NOT_FOUND`, obwohl die Datei auf dem Rechner
   liegt. Schritt 1 aus `demo/prompts.md` bricht damit beim ersten Aufruf ab, bis der Agent auf `content_base64`
   ausweicht (kostet Zeit, wirkt live schlecht). Für die Demo stdio nutzen (Variante B). Dauerhafte Lösung: `demo/`
   in den Backend-Container mounten (Pfad im Container identisch) oder lokale Pfade im MCP-Prozess einlesen und als
   `content_base64` weiterreichen.
2. **Sehr große Tool-Schemas.** `apply_ops`, `edit_document` und `create_document` bringen jeweils den kompletten
   Block- und Op-Baum (alle Blocktypen, alle Ops, verschachtelte `children`) als JSON-Schema mit, je mehrere zehn KB.
   Das kostet bei jedem Laden viel Kontext, macht Agenten langsamer und teurer und lässt weniger Platz für die
   eigentliche Aufgabe. Möglichkeiten: gemeinsame Definitionen nur einmal ausliefern, Ops/Blöcke im Schema als
   `object` mit Verweis auf eine Doku-Ressource beschreiben (Validierung bleibt serverseitig), oder das volle Schema
   nur an `apply_ops` hängen und die übrigen Tools schlank halten.

## Fehlersuche

- **401:** Token abgelaufen oder Backend mit anderem `JWT_SECRET` gestartet. `demo/seed.py --fresh-tokens-only`
  ausführen bzw. `docker compose up -d`.
- **Tools fehlen:** In Claude `/mcp` aufrufen, in ChatGPT den Connector neu laden (Aktualisieren).
- **Agent hakt in der Demo:** Fallback ohne Agent mit `backend/.venv/bin/python demo/fallback.py`.
