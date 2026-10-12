"""« Carte bannie ? » - which cards are banned in Modern, Legacy and Duel Commander, from Scryfall.

Called by fetch_prices.py with the Scryfall "Oracle Cards" it has already downloaded, so the answers
follow every banlist update the next morning. Writes docs/data/bannies.json:
  {"generated": date, "banned": [[name, id, mask], ...], "decoys": {kind: [[name, id, 0, why], ...]}}
mask: 1 = banned in Modern, 2 = in Legacy, 4 = in Duel Commander. The answer always comes from the
current Scryfall legalities; the decoy categories and their "why" only choose which legal cards to ask.

Only cards shown with a modern frame (2003 or 2015 frame, after Mirrodin) and legal or banned in all
three formats (never "not legal": that is not a ban, and would only confuse the question).

Decoys (legal in all three formats), four kinds:
  ailleurs : banned (or restricted) in another format - Commander, Pioneer, Standard, Pauper, Vintage...
  debannie : banned in Modern, Legacy or Duel Commander before, legal now. Built up day after day in
             docs/data/bannies-history.json (every card ever seen banned), started with famous unbans.
  cousine  : shares a mechanic with a banned card (delve, cascade, companion, "without paying its
             mana cost"...), the closest ones first.
  suspecte : the most played, expensive, cheap, tutor-like... cards (fallback score).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

FORMATS = (("modern", 1, "Modern"), ("legacy", 2, "Legacy"), ("duel", 4, "Duel Commander"))
# formats whose bans make a card "look banned" (paper formats; Arena-only bans are about the client)
OTHER = {"commander": "Commander", "pioneer": "Pioneer", "standard": "Standard", "pauper": "Pauper",
         "vintage": "Vintage", "oathbreaker": "Oathbreaker", "premodern": "Premodern",
         "paupercommander": "Pauper Commander", "predh": "PreDH"}
# Famous unbans the history starts with (bit = format). Only used to pick decoys; the answer is the
# current legality, and a card banned again is simply not a decoy any more.
UNBANNED_SEED = {
    "Jace, the Mind Sculptor": 1, "Bloodbraid Elf": 1, "Ancestral Vision": 1, "Sword of the Meek": 1,
    "Wild Nacatl": 1, "Bitterblossom": 1, "Thopter Foundry": 1,
}
MODERN_FRAMES = {"2003", "2015"}
CAP = 150
EVERGREEN = {"flying", "first strike", "double strike", "deathtouch", "haste", "hexproof", "indestructible", "lifelink",
             "menace", "reach", "trample", "vigilance", "defender", "flash", "ward", "enchant", "equip", "scry",
             "mill", "fight", "transform", "protection", "landfall", "kicker", "cycling"}
PHRASES = {
    "gratuit": r"without paying its mana cost|rather than pay this spell's mana cost",
    "tour supplémentaire": r"extra turn",
    "tuteur": r"search your library for a card",
    "mana rapide": r"add \{[wubrgc]\}\{[wubrgc]\}|add three mana|add x mana",
    "pioche": r"draw (two|three|four|seven) cards",
    "Trésor": r"treasure token",
    "copie": r"copy target|copy that spell",
    "dégagement": r"untap all|untap target",
    "contrôle adverse": r"can't cast|can't play|your opponents can't",
}
SUSPICIOUS = re.compile("|".join(PHRASES.values()) + r"|cascade|storm|delve|affinity|convoke|destroy all|exile all", re.I)


def text_of(c: dict) -> str:
    return (c.get("oracle_text") or "") + " " + " ".join(f.get("oracle_text", "") for f in c.get("card_faces") or [])


def eligible(c: dict) -> bool:
    if c.get("digital") or c.get("frame") not in MODERN_FRAMES or c.get("set_type") in {"funny", "token", "memorabilia"}:
        return False
    if c.get("layout") not in {"normal", "transform", "modal_dfc", "adventure", "split", "flip", "saga", "class", "prototype"}:
        return False
    if "Basic Land" in (c.get("type_line") or ""):
        return False
    leg = c.get("legalities") or {}
    return all(leg.get(f) in ("legal", "banned") for f, _, _ in FORMATS)


def mask(c: dict) -> int:
    leg = c.get("legalities") or {}
    return sum(bit for f, bit, _ in FORMATS if leg.get(f) == "banned")


def mechanics(c: dict) -> set[str]:
    """The card's notable mechanics: non-evergreen keywords and a few telling phrases."""
    out = {k.lower() for k in c.get("keywords") or [] if k.lower() not in EVERGREEN}
    t = text_of(c)
    out.update(tag for tag, rx in PHRASES.items() if re.search(rx, t, re.I))
    return out


def suspicion(c: dict) -> float:
    rank = c.get("edhrec_rank") or 0
    eur = float((c.get("prices") or {}).get("eur") or 0)
    score = max(0.0, 3.0 - rank / 1000) if rank else 0.0
    score += min(3.0, eur / 5) + 1.5 * len(SUSPICIOUS.findall(text_of(c)))
    if (c.get("cmc") or 0) <= 2 and "Land" not in (c.get("type_line") or ""):
        score += 1.0
    if c.get("rarity") in ("mythic", "rare"):
        score += 0.5
    return score


def fmt_names(bits: int) -> str:
    return ", ".join(n for _, b, n in FORMATS if bits & b)


def build(cards: list[dict], out: Path, history_path: Path | None = None) -> None:
    history_path = history_path or out.with_name("bannies-history.json")
    try:
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {}
    except ValueError:
        history = {}
    for name, bits in UNBANNED_SEED.items():
        history[name] = history.get(name, 0) | bits

    pool = [c for c in cards if eligible(c)]
    for c in cards:                                   # every card seen banned, on any frame
        m = mask(c)
        if m:
            history[c["name"]] = history.get(c["name"], 0) | m
    banned_cards = [c for c in pool if mask(c)]
    banned = [[c["name"], c["id"], mask(c)] for c in banned_cards]
    legal = [c for c in pool if not mask(c)]
    used: set[str] = set()

    def take(rows):                                   # a card is a decoy of one kind only
        res = []
        for r in rows:
            if r[0] not in used and len(res) < CAP:
                used.add(r[0]); res.append(r)
        return res

    # 1. ex-banned in one of the three formats
    deb = take([[c["name"], c["id"], 0, "Ancienne carte bannie en " + fmt_names(history[c["name"]])]
                for c in sorted(legal, key=suspicion, reverse=True) if history.get(c["name"])])
    # 2. banned or restricted in another format
    def elsewhere(c):
        leg = c.get("legalities") or {}
        bad = [n for f, n in OTHER.items() if leg.get(f) == "banned"]
        if leg.get("vintage") == "restricted":
            bad.append("Vintage (restreinte)")
        return bad
    ail = take([[c["name"], c["id"], 0, ("Bannie ailleurs : " if any("restreinte" not in x for x in elsewhere(c)) else "Restreinte ailleurs : ") + ", ".join(elsewhere(c))]
                for c in sorted(legal, key=suspicion, reverse=True) if elsewhere(c)])
    # 3. shares a mechanic with a banned card
    by_mech: dict[str, str] = {}
    for c in sorted(banned_cards, key=lambda c: c.get("edhrec_rank") or 99999):
        for m in mechanics(c):
            by_mech.setdefault(m, c["name"])
    cousins = []
    for c in legal:
        shared = [m for m in mechanics(c) if m in by_mech]
        if shared:
            m = max(shared, key=lambda m: len(m))
            cousins.append((len(shared) * 2 + suspicion(c), [c["name"], c["id"], 0, f"Même mécanique ({m}) que {by_mech[m]}, bannie"]))
    cou = take([r for _, r in sorted(cousins, key=lambda x: -x[0])])
    # 4. fallback: the most "suspicious" legal cards
    sus = take([[c["name"], c["id"], 0, ""] for c in sorted(legal, key=suspicion, reverse=True)])

    out.write_text(json.dumps({"generated": dt.date.today().isoformat(), "banned": sorted(banned),
                               "decoys": {"debannie": deb, "ailleurs": ail, "cousine": cou, "suspecte": sus}},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    history_path.write_text(json.dumps(dict(sorted(history.items())), ensure_ascii=False, indent=0), encoding="utf-8")
    by = {bit: sum(1 for b in banned if b[2] & bit) for _, bit, _ in FORMATS}
    print(f"Carte bannie : {len(banned)} cartes bannies (Modern {by[1]}, Legacy {by[2]}, Duel Commander {by[4]}) ; "
          f"leurres : {len(deb)} débannies, {len(ail)} bannies ailleurs, {len(cou)} cousines, {len(sus)} suspectes -> {out}")
