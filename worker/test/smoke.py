"""Smoke test of the game server, against `wrangler dev` (local D1) or a deployed Worker.

Usage: python worker/test/smoke.py http://127.0.0.1:8787 <admin token>
Checks: deck upload (and refusal without the token), a full game, the server-side score,
a forged submit, a double submit, a late hardcore answer, the leaderboard order.
"""
import json
import sys
import time
import urllib.error
import urllib.request

API, ADMIN = sys.argv[1].rstrip("/"), sys.argv[2]
failures = []


def call(path, data=None, token=None):
    req = urllib.request.Request(API + path, method="POST" if data is not None else "GET",
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json", "Origin": "http://localhost:8000",
                                          **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


key = {f"card{i:02d}.webp": {"real": i % 2 == 0, "set": "Test Set", "artist": "A. Artist"} for i in range(40)}
check("deck upload refused without token", call("/admin/deck", {"mode": "normal", "key": key})[0] == 401)
for mode in ("normal", "hardcore"):
    s, r = call("/admin/deck", {"mode": mode, "key": key}, ADMIN)
    check(f"deck upload {mode}", s == 200 and r.get("cards") == 40, r)
check("deck read refused without token", call("/admin/deck?mode=normal")[0] == 401)
s, r = call("/admin/deck?mode=normal", None, ADMIN)
check("deck read with token", s == 200 and r.get("key") == key, str(r)[:200])


def play(mode, right, pause=0.0):
    s, g = call("/start", {"mode": mode})
    check(f"start {mode}", s == 200 and len(g.get("cards", [])) == 20, g)
    for i, img in enumerate(g["cards"]):
        truth = "real" if key[img]["real"] else "ai"
        answer = truth if i < right else ("ai" if truth == "real" else "real")
        time.sleep(pause)
        s, r = call("/answer", {"game": g["game"], "index": i, "answer": answer})
        check(f"answer {i}", s == 200 and r["truth"] == truth and r["correct"] == (i < right), r)
        if i == 0:
            s2, r2 = call("/answer", {"game": g["game"], "index": 0, "answer": truth})
            check("replaying an answered card is refused", s2 == 409, r2)
        time.sleep(1.2)                                   # the page's verdict
    return g


s, r = call("/start", {"mode": "normal"})
s2, r2 = call("/submit", {"game": r["game"], "name": "Cheater"})
check("submit of an unfinished game refused", s2 == 409, r2)

g = play("normal", 8)
s, r = call("/result", {"game": g["game"]})
check("server-side score", s == 200 and r["score"] == 8 and r["qualifies"], r)
s, r = call("/submit", {"game": g["game"], "name": "Morgane"})
check("submit", s == 200 and r["entered"] and r["rank"] == 1, r)
s, r = call("/submit", {"game": g["game"], "name": "Morgane"})
check("double submit refused", s == 409, r)

g = play("normal", 20)
s, r = call("/submit", {"game": g["game"], "name": "<script>"})
check("bad name refused", s == 400, r)
s, r = call("/submit", {"game": g["game"], "name": "Élise"})
check("better score ranks first", s == 200 and r["rank"] == 1 and r["leaderboard"]["normal"][1]["name"] == "Morgane", r)

# hardcore: an answer after card 1's 10 s + grace counts as wrong even if right
s, g = call("/start", {"mode": "hardcore"})
check("hardcore limits", g.get("limits", [None])[0] == 8000 and g["limits"][-1] == 4000, g.get("limits"))
time.sleep(11)
img = g["cards"][0]
s, r = call("/answer", {"game": g["game"], "index": 0, "answer": "real" if key[img]["real"] else "ai"})
check("late hardcore answer counts as wrong", s == 200 and r["correct"] is False and r["timeout"] is True, r)

s, r = call("/leaderboard")
check("leaderboard", s == 200 and [x["name"] for x in r["normal"]][:2] == ["Élise", "Morgane"], r)
print("\n" + ("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
