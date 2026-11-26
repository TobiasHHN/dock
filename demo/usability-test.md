# Usability-Test (5 Minuten): Bestellprozess per Agent

Testperson = **Anna (Einkauf)**, arbeitet nur mit ihrem KI-Assistenten. Ben und Chef spielt das Testteam.

## Für das Testteam (nicht vorlesen)

- Vorher: `docker compose down -v && docker compose up -d --build`, dann `python demo/seed.py`. **Nicht** `fallback.py` ausführen.
- Agent der Testperson ist per MCP als Anna verbunden, Chat ist leer.
- Nicht helfen. Notieren: Zeit, Anzahl Prompts, wo die Testperson zögert.

---

## Vorlesetext

> Danke fürs Mitmachen! Wir testen die Software, nicht Sie. Bitte denken Sie laut.
>
> Sie sind **Anna** aus dem **Einkauf**. Bisher laufen Bestellungen über ein Word-Formular und eine Excel-Liste. Beide Dateien liegen im Ordner `demo/`: `Bestellformular.docx` und `Bestelluebersicht.xlsx`. Ab jetzt soll das über unsere Plattform laufen. Sie bedienen sie über Ihren **KI-Assistenten**. Sagen Sie ihm einfach in eigenen Worten, was Sie wollen.

### Aufgabe 1

> Lassen Sie Ihren Assistenten aus den beiden Dateien einen Bestellprozess bauen: Ein Mitarbeiter reicht das Formular ein, der Chef genehmigt, danach bestellen Sie beim Lieferanten.

*Erfolg:* Der Agent meldet einen veröffentlichten Workflow.
*Danach (Testteam):* Ben bestellt 2× Dell-Monitor, Chef genehmigt. Das kann per Browser oder per Agent passieren.

### Aufgabe 2

> Der Chef hat eine Bestellung von Ben genehmigt. Sie haben bestellt, die Bestellnummer ist **LF-2026-0815**, geliefert wird am **3. Dezember**. Erledigen Sie Ihren Teil mit Ihrem Assistenten.

*Erfolg:* Die Aufgabe ist abgeschlossen, der Run steht auf „Bestellt“.

### Zum Schluss

> Was war einfach, was war unklar?
