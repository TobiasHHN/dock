"""2.I2: Demo-Story ohne Agent per REST + WebSocket-Beobachter.

Voraussetzung: frische DB, `python demo/seed.py`, `python demo/fallback.py`. Aufruf: `python demo/e2e_story.py`.
Spielt zwei Runs durch (Ablehnung, Genehmigung + Bestellung) und listet OK/BUGS. IDs stammen aus `fallback_batch.json`."""
import asyncio, json, sys, uuid
import httpx, websockets

BASE = "http://localhost:8000/api"
T = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "demo/.tokens.json"))
F1, F2, F3 = "blk_01M8BNNHZQ5EVC85FBJKV35YPQ", "blk_s2_form", "blk_s3_form"
ORDERS = "tbl_01M8BNNHWR0WSE3N076QJRXNNV"
bugs, ok = [], []


def cli(who, agent=False):
    tok = T[who]["agent_token" if agent else "user_token"]
    return httpx.Client(base_url=BASE, headers={"Authorization": "Bearer " + tok}, timeout=30)


def ops(c, *o):
    r = c.post("/ops", json={"batch_id": "b_" + uuid.uuid4().hex, "ops": list(o)})
    return r.status_code, r.json()


def check(cond, msg, extra=None):
    (ok if cond else bugs).append(msg + ("" if cond or extra is None else f" -> {json.dumps(extra, ensure_ascii=False)[:400]}"))


class Watch:
    def __init__(self, who, channels):
        self.who, self.channels, self.msgs = who, channels, []

    async def run(self):
        url = "ws://localhost:8000/ws?token=" + T[self.who]["user_token"]
        async with websockets.connect(url) as ws:
            for ch in self.channels:
                await ws.send(json.dumps({"type": "subscribe", "channel": ch}))
            async for m in ws:
                self.msgs.append(json.loads(m))

    def seen(self, pred):
        return any(pred(m) for m in self.msgs)


async def main():
    ben, chef, anna, chef_agent = cli("ben"), cli("chef"), cli("anna"), cli("chef", agent=True)
    w_chef = Watch("chef", [f"user:{T['chef']['user_id']}"])
    w_anna = Watch("anna", [f"table:{ORDERS}", f"user:{T['anna']['user_id']}"])
    tasks = [asyncio.create_task(w.run()) for w in (w_chef, w_anna)]
    await asyncio.sleep(1)

    # Rechte: Ben darf kein Schema ändern / nicht veröffentlichen
    s, b = ops(ben, {"op": "column.add", "table": ORDERS, "column": {"id": "col_xben1", "key": "x_ben", "name": "X", "type": {"kind": "text"}}})
    check(s == 403, f"Ben column.add -> 403 (got {s})", b)
    s, b = ops(ben, {"op": "workflow.publish", "workflow": "wf_best"})
    check(s == 403, f"Ben workflow.publish -> 403 (got {s})", b)

    async def one_run(reject: bool):
        run = "run_" + uuid.uuid4().hex[:20]
        s, b = ops(ben, {"op": "run.start", "id": run, "workflow": "bestellprozess"})
        check(s == 200, f"Ben run.start ({s})", b)
        w_ben = Watch("ben", [f"run:{run}"]); tb = asyncio.create_task(w_ben.run()); tasks.append(tb)
        s, b = ops(ben, {"op": "form.submit", "submission_id": "sub_" + uuid.uuid4().hex, "form_block": F1, "button": "submit",
                         "run": run, "values": {"name": "Ben Mitarbeiter", "kostenstelle": "4711", "bemerkung": "",
                                                "artikel": [{"artikelname": "Dell-Monitor U2724D", "artikelnummer": "DELL-U2724D", "preis": 289.9, "anzahl": 2}]}})
        check(s == 200 and b["results"]["0"]["run"]["current_step"] == "genehmigung", f"Ben erfassen -> genehmigung ({s})", b)
        await asyncio.sleep(1.5)
        check(w_chef.seen(lambda m: m.get("type") == "ops" and run in json.dumps(m)), "Chef bekommt Aufgabe live (user-Kanal)")
        check(w_anna.seen(lambda m: m.get("type") == "ops" and m["channel"] == f"table:{ORDERS}" and run in json.dumps(m)),
              "Annas Tabelle sieht neue Bestellung live")
        my = ben.get("/runs", params={"mine": "true"}).json()
        check(any(r.get("id") == run for r in (my if isinstance(my, list) else [])), "Ben sieht Run in Meine Anträge", my)
        tl = chef.get("/tasks").json()
        check(any(t.get("run") == run or t.get("run_id") == run or run in json.dumps(t) for t in tl), "Chef sieht Aufgabe in /tasks", tl)
        # Vier-Augen
        s, b = ops(ben, {"op": "form.submit", "submission_id": "sub_" + uuid.uuid4().hex, "form_block": F2, "button": "approve", "run": run})
        check(s in (403, 409), f"Ben darf nicht genehmigen ({s})", b)
        if reject:
            s, b = ops(chef, {"op": "form.submit", "submission_id": "sub_" + uuid.uuid4().hex, "form_block": F2, "button": "reject", "run": run, "values": {}})
            check(s >= 400, f"Ablehnen ohne Kommentar verweigert ({s})", b)
            s, b = ops(chef, {"op": "form.submit", "submission_id": "sub_" + uuid.uuid4().hex, "form_block": F2, "button": "reject", "run": run, "values": {"kommentar": "Budget erschöpft"}})
            check(s == 200 and b["results"]["0"]["run"]["status"] == "completed", f"Ablehnen mit Kommentar beendet Run ({s})", b)
        else:
            task = next((t for t in chef.get("/tasks").json() if run in json.dumps(t)), None)
            tid = task and task["task"]["id"]
            s, b = ops(chef, {"op": "task.claim", "task": tid})
            check(s == 200, f"Chef übernimmt Aufgabe ({s})", b)
            s, b = ops(chef_agent, {"op": "form.submit", "submission_id": "sub_" + uuid.uuid4().hex, "form_block": F2, "button": "approve", "run": run, "values": {"kommentar": "Passt."}})
            check(s == 200 and b["results"]["0"]["run"]["current_step"] == "bestellung", f"Chef-Agent genehmigt ({s})", b)
            await asyncio.sleep(1.5)
            check(w_anna.seen(lambda m: m.get("type") == "ops" and m["channel"].startswith("user:") and run in json.dumps(m)), "Anna bekommt Einkaufs-Aufgabe live")
            s, b = ops(anna, {"op": "form.submit", "submission_id": "sub_" + uuid.uuid4().hex, "form_block": F3, "button": "ordered", "run": run,
                              "values": {"lieferanten_nr": "PO-2026-0815", "liefertermin": "2026-12-03"}})
            check(s == 200 and b["results"]["0"]["run"]["status"] == "completed", f"Anna bestellt -> abgeschlossen ({s})", b)
        await asyncio.sleep(1.5)
        st = ben.get(f"/runs/{run}").json()
        print("  get_run:", json.dumps({k: st.get(k) for k in ("status", "status_label", "current_step", "result")}, ensure_ascii=False))
        hist = json.dumps(st.get("history") or st.get("events") or [], ensure_ascii=False)
        if not reject:
            check("on_behalf_of" in hist or "im Auftrag" in hist or "agt_chef" in hist, "Verlauf nennt Agent im Auftrag", st.get("history"))
        check(w_ben.seen(lambda m: m.get("type") == "ops"), "Ben sieht Run-Änderungen live (run-Kanal)")
        rows = anna.post(f"/tables/{ORDERS}/rows/query", json={}).json()
        print("  Bestellungen:", [r.get("values", {}).get("col_b_status") for r in rows.get("rows", [])])

    print("Durchlauf 1 (Ablehnung)"); await one_run(reject=True)
    print("Durchlauf 2 (Genehmigung + Bestellung)"); await one_run(reject=False)
    for t in tasks: t.cancel()
    print("\nOK:"); [print("  ✓", m) for m in ok]
    print("BUGS:"); [print("  ✗", m) for m in bugs]
    sys.exit(1 if bugs else 0)


asyncio.run(main())
