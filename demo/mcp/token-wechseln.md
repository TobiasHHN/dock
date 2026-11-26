# MCP-Token wechseln: Agent im Namen eines anderen Nutzers

Der MCP-Server (`http://localhost:8000/mcp`) kennt keine eigene Nutzerverwaltung. Die Identität des Agenten ergibt sich allein aus dem Bearer-Token im `Authorization`-Header. Wer das Token tauscht, tauscht den Nutzer: Der Agent handelt dann mit den Rechten und Rollen dieses Nutzers, und im Verlauf steht „von <Name>s Assistent im Auftrag von <Name>“.

| Nutzer | Rolle | Agent | Eintrag in `demo/.tokens.json` |
|---|---|---|---|
| Anna (`anna@demo.local`) | `einkauf` | `agt_anna_assistent` | `anna` |
| Ben (`ben@demo.local`) | `mitarbeiter` | `agt_ben_assistent` | `ben` |
| Chef (`chef@demo.local`) | `chef` | `agt_chef_assistent` | `chef` |

Verwende immer den **`agent_token`**, nicht den `user_token`. Der `user_token` ist das Login-Token des Menschen und erscheint im Verlauf nicht als Agent.

## Voraussetzungen

- Backend läuft (`docker compose up -d`), Demo-Daten sind angelegt (`backend/.venv/bin/python demo/seed.py`).
- Tokens sind 7 Tage gültig. Abgelaufen oder 401? Erneuern mit:
  ```
  backend/.venv/bin/python demo/seed.py --fresh-tokens-only
  ```
  Das schreibt `demo/.tokens.json`, `demo/mcp/anna.json` und `demo/mcp/ben.json` neu. Diese Dateien enthalten Tokens und sind per `.gitignore` ausgeschlossen. Nie committen.

## Variante A: Mit der Config-Datei starten (einfachster Weg)

Pro Nutzer eine Datei, die Sitzung startet mit genau diesem Nutzer:

```
claude --mcp-config demo/mcp/anna.json    # Agent handelt als Anna
claude --mcp-config demo/mcp/ben.json     # Agent handelt als Ben
```

Wechsel = Sitzung beenden und mit der anderen Datei neu starten. Der Token wird beim Start gelesen und gilt für die ganze Sitzung.

Für den Chef gibt es keine fertige Datei. Kopiere `anna.json` nach `demo/mcp/chef.json` und setze `agent_token` von `chef` aus `demo/.tokens.json` als `Authorization: Bearer <agent_token>` ein:

```json
{
  "mcpServers": {
    "dock": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer <agent_token von chef>" }
    }
  }
}
```

## Variante B: Registrierten MCP-Server umstellen

Ist der Server fest in Claude Code registriert (z. B. als `dock-anna`), ersetze die Registrierung durch eine mit dem anderen Token:

```
TOKEN=$(python3 -c "import json;print(json.load(open('demo/.tokens.json'))['ben']['agent_token'])")

claude mcp remove dock-anna
claude mcp add --transport http dock-ben http://localhost:8000/mcp \
  --header "Authorization: Bearer $TOKEN"
```

Danach Claude Code neu starten (oder `/mcp` → neu verbinden), damit die neuen Header gelten. Tool-Namen tragen den Servernamen als Präfix (`mcp__dock-anna__…` wird zu `mcp__dock-ben__…`). Frühere Prompts und Berechtigungsregeln, die den alten Namen nennen, müssen angepasst werden. Wer die alte Namensform behalten will, registriert den Server unter demselben Namen neu.

Zwei Nutzer parallel: beide Server unter verschiedenen Namen registrieren (`dock-anna`, `dock-ben`). Der Agent wählt dann über das Tool-Präfix, in wessen Namen er handelt. Das ist praktisch für die Demo-Schritte 1 und 2 in einer Sitzung, birgt aber Verwechslungsgefahr. Im Prompt ausdrücklich nennen, welchen Server er nutzen soll.

## Variante C: Stdio-Betrieb mit Umgebungsvariable

Läuft der MCP-Server lokal per stdio (`python -m app.mcp.server`), kommt die Identität aus `DOCK_TOKEN`:

```
DOCK_TOKEN=<agent_token> backend/.venv/bin/python -m app.mcp.server
```

Bei HTTP hat ein mitgesendeter `Authorization`-Header Vorrang vor `DOCK_TOKEN`. Siehe `_identity_headers` in `backend/app/mcp/server.py`.

## Prüfen, wer der Agent gerade ist

- Aufruf von `list_users` oder `list_tasks` und Blick auf den Verlauf in der Oberfläche: Einträge erscheinen als „Annas Assistent im Auftrag von Anna Beispiel“ usw.
- Rollenabhängige Tools zeigen den Wechsel sofort. Beispiel: Als Ben (`mitarbeiter`) schlägt `publish_workflow` mit `FORBIDDEN` fehl, als Anna (`einkauf`) nicht. Genehmigen kann nur `chef`, und nicht der Antragsteller.

## Fehlerbilder

| Meldung | Ursache | Abhilfe |
|---|---|---|
| `UNAUTHORIZED` / 401 | Token abgelaufen oder `JWT_SECRET` des Containers weicht ab | `seed.py --fresh-tokens-only`; `docker compose up -d`; Wert prüfen mit `docker compose exec backend env \| grep JWT` |
| `FORBIDDEN` / 403 | Die Rolle des gewählten Nutzers darf die Aktion nicht | Richtigen Nutzer wählen, nicht die Rechte umgehen |
| Agent handelt weiter als der alte Nutzer | Sitzung nicht neu gestartet oder alter Server noch registriert | Claude Code neu starten; `claude mcp list` prüfen |
| Verlauf zeigt keinen Agenten, nur den Menschen | `user_token` statt `agent_token` verwendet | `agent_token` einsetzen |

## Sicherheit

Ein Agent-Token ist ein Passwort für alles, was der Nutzer darf. Nicht in Chat, Tickets oder Git teilen. Für die Demo gilt das Default-`JWT_SECRET` aus `backend/app/config.py`. Außerhalb der Demo ein eigenes setzen, und Tokens mit kurzer Laufzeit ausstellen.
