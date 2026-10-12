"""« Carte bannie ? » - which cards are banned in Modern, Legacy and Duel Commander, from Scryfall.

Called by fetch_prices.py with the Scryfall "Oracle Cards" it has already downloaded, so the answers
follow every banlist update the next morning. Writes docs/data/bannies.json:
  {"generated": date, "banned": [[name, id, mask], ...], "decoys": [[name, id, 0], ...]}
mask: 1 = banned in Modern, 2 = in Legacy, 4 = in Duel Commander.

Only cards shown with a modern frame (2003 or 2015 frame, after Mirrodin) and legal or banned in all
three formats (never "not legal": that is not a ban, and would only confuse the question).

The decoys make the quiz hard: cards legal everywhere that look like they could be banned, i.e. the
most played and most expensive cards of those formats, cheap fast mana, tutors, free spells, extra
turns... ranked by a "suspicion" score; the top ones are kept.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

FORMATS = (("modern", 1), ("legacy", 2), ("duel", 4))
MODERN_FRAMES = {"2003", "2015"}
DECOYS = 300
SUSPICIOUS = re.compile(
    r"without paying its mana cost|extra turn|search your library for a card|add \{[wubrgc]\}\{[wubrgc]\}|"
    r"rather than pay this spell's mana cost|untap all|each opponent|can't cast|draw (two|three|seven) cards|"
    r"cascade|storm|delve|affinity|convoke|copy target|return target|destroy all|exile all|infinite", re.I)


def eligible(c: dict) -> bool:
    if c.get("digital") or c.get("frame") not in MODERN_FRAMES or c.get("set_type") in {"funny", "token", "memorabilia"}:
        return False
    if c.get("layout") not in {"normal", "transform", "modal_dfc", "adventure", "split", "flip", "saga", "class", "prototype"}:
        return False
    if "Basic Land" in (c.get("type_line") or ""):
        return False
    leg = c.get("legalities") or {}
    return all(leg.get(f) in ("legal", "banned") for f, _ in FORMATS)


def mask(c: dict) -> int:
    leg = c["legalities"]
    return sum(bit for f, bit in FORMATS if leg.get(f) == "banned")


def suspicion(c: dict) -> float:
    """How much a legal card looks like a banned one."""
    rank = c.get("edhrec_rank") or 0
    eur = float((c.get("prices") or {}).get("eur") or 0)
    text = (c.get("oracle_text") or "") + " ".join(f.get("oracle_text", "") for f in c.get("card_faces") or [])
    score = 0.0
    if rank:
        score += max(0.0, 3.0 - rank / 1000)          # top 3 000 of Commander
    score += min(3.0, eur / 5)                        # up to 15 €
    score += 1.5 * len(SUSPICIOUS.findall(text))
    if (c.get("cmc") or 0) <= 2 and "Land" not in (c.get("type_line") or ""):
        score += 1.0                                  # cheap and efficient
    if c.get("rarity") in ("mythic", "rare"):
        score += 0.5
    return score


def build(cards: list[dict], out: Path) -> None:
    pool = [c for c in cards if eligible(c)]
    banned = [[c["name"], c["id"], mask(c)] for c in pool if mask(c)]
    legal = sorted((c for c in pool if not mask(c)), key=suspicion, reverse=True)[:DECOYS]
    decoys = [[c["name"], c["id"], 0] for c in legal]
    out.write_text(json.dumps({"generated": dt.date.today().isoformat(), "banned": sorted(banned),
                               "decoys": decoys}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    by = {bit: sum(1 for b in banned if b[2] & bit) for _, bit in FORMATS}
    print(f"Carte bannie : {len(banned)} cartes bannies (Modern {by[1]}, Legacy {by[2]}, Duel Commander {by[4]}), "
          f"{len(decoys)} leurres -> {out}")
