"""Cards of the day for « Carte mystère » (a card to guess letter by letter, like Spellify).

Called by fetch_prices.py with the Scryfall "Oracle Cards" it has already downloaded. Writes
docs/data/mystere.json: a schedule {date: card} from yesterday to DAYS_AHEAD days ahead (Paris dates).
Dates already scheduled keep their card when the file is regenerated, so everyone gets the same card
all day long; the names already used are kept too, so a card does not come back.

Each card is lightly sealed (XOR with SHA-256 of its date, base64) so that the answers are not
readable at a glance in the file; the game unseals the card of the day.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import random
import re
from pathlib import Path
from zoneinfo import ZoneInfo

DAYS_AHEAD = 21
MAX_RANK = 1500                         # well-known cards only: the 1 500 most played in Commander
ALLOWED_SYMBOLS = re.compile(r"^\{([WUBRGCXT]|\d)\}$")
SYMBOL = re.compile(r"\{[^}]+\}")


def paris_today() -> dt.date:
    """Today's date in Paris (the game switches cards at Paris midnight)."""
    try:
        return dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:                       # no time zone data (tzdata not installed): CET/CEST guess
        now = dt.datetime.now(dt.timezone.utc)
        summer = 3 < now.month < 10 or (now.month == 3 and now.day >= 25) or (now.month == 10 and now.day < 25)
        return (now + dt.timedelta(hours=2 if summer else 1)).date()


def candidate(c: dict) -> bool:
    """A single-faced, ranked card whose symbols are all guessable keys (WUBRG, C, X, T, numbers)."""
    if c.get("layout") != "normal" or c.get("digital") or not c.get("oracle_text"):
        return False
    if not (0 < (c.get("edhrec_rank") or 0) <= MAX_RANK):
        return False
    if any(w in (c.get("type_line") or "") for w in ("Basic Land", "Planeswalker", "Battle")) \
            or c.get("set_type") in {"token", "funny", "memorabilia"}:
        return False
    text = (c.get("mana_cost") or "") + (c.get("oracle_text") or "")
    if not all(ALLOWED_SYMBOLS.match(s) for s in SYMBOL.findall(text)):
        return False
    if not re.fullmatch(r"[A-Za-z0-9 ,'\-]+", c["name"]):          # plain names only (no accents, no //)
        return False
    return 20 <= len(c["oracle_text"]) <= 320


def payload(c: dict) -> dict:
    return {"n": c["name"], "m": c.get("mana_cost") or "", "t": c.get("type_line") or "",
            "o": c.get("oracle_text") or "", "p": c.get("power"), "h": c.get("toughness"),
            "l": c.get("loyalty"), "id": c["id"], "s": c.get("set", ""), "cn": c.get("collector_number", ""),
            # for the Magic Set Editor render (pipeline/render_mystere.py)
            "r": c.get("rarity") or "common", "a": c.get("artist") or "", "d": c.get("released_at") or "",
            "ft": c.get("flavor_text") or ""}


def seal(card: dict, date: str) -> str:
    raw = json.dumps(card, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    key = hashlib.sha256(date.encode()).digest()
    return base64.b64encode(bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))).decode()


def unseal(blob: str, date: str) -> dict:
    raw = base64.b64decode(blob)
    key = hashlib.sha256(date.encode()).digest()
    return json.loads(bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)).decode("utf-8"))


def build(cards: list[dict], path: Path, today: dt.date | None = None) -> None:
    today = today or paris_today()
    old = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    used = list(old.get("used", []))
    days = {d: v for d, v in (old.get("days") or {}).items() if d >= (today - dt.timedelta(days=1)).isoformat()}

    pool = [c for c in cards if candidate(c)]
    by_name = {c["name"]: c for c in pool}
    fresh = [n for n in sorted(by_name) if n not in set(used)]
    if len(fresh) < DAYS_AHEAD + 2:                 # every card has been used: start a new round
        used, fresh = [], sorted(by_name)
    rng = random.Random(f"{today.isoformat()}-{len(used)}")
    rng.shuffle(fresh)

    added = 0
    for i in range(-1, DAYS_AHEAD + 1):
        d = (today + dt.timedelta(days=i)).isoformat()
        if d in days or not fresh:
            continue
        name = fresh.pop()
        days[d] = seal(payload(by_name[name]), d)
        used.append(name)
        added += 1
    out = {"generated": today.isoformat(), "days": dict(sorted(days.items())), "used": used[-3000:]}
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Carte mystère : {len(pool)} cartes possibles, {added} jour(s) ajouté(s), {len(days)} programmé(s) -> {path}")
