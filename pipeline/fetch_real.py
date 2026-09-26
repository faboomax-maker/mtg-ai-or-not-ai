"""Step 1 - Fetch real cards (text + art crop only) from the free Scryfall API.

Usage:
    python pipeline/fetch_real.py --count 60
    python pipeline/fetch_real.py --count 60 --query "set:dsk -type:basic"

Output: pipeline/work/real.json + pipeline/work/img/real_<id>.jpg
"""
from __future__ import annotations

import argparse
import difflib
import json
import lzma
import random
import re
import sys
import time

from common import WORK, WORK_IMG, WORK_SETS, ensure_dirs, env, fetch_bytes, load_json, normalize_image, save_json, session

API = "https://api.scryfall.com"

# Modern single-faced paper cards, same frame era as what the AI imitates.
DEFAULT_QUERY = (
    "game:paper layout:normal lang:en frame:2015 year>=2016 "
    "(st:expansion or st:core) -is:funny -is:reprint -is:promo -type:basic"
)

# Rares and mythics are the cards players know by heart: a famous real card is spotted at
# once, and so is a fake "mythic" nobody has heard of. Both pools (real cards here, AI card
# profiles in generate_fake.py) are drawn with these weights.
RARITY_WEIGHTS = {"common": 55, "uncommon": 40, "rare": 4, "mythic": 1}


def parse_weights(text: str | None) -> dict[str, float]:
    """'common=55,uncommon=40,rare=4,mythic=1' -> dict (missing rarities keep the default)."""
    weights = dict(RARITY_WEIGHTS)
    for part in (text or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            weights[k.strip().lower()] = float(v)
    return weights


def pick_rarity(weights: dict[str, float]) -> str:
    return random.choices(list(weights), weights=list(weights.values()))[0]


FIELDS = ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
          "power", "toughness", "loyalty", "rarity", "colors", "cmc", "keywords", "produced_mana",
          "set", "set_name", "artist", "collector_number", "released_at", "scryfall_uri")


def ensure_set_icon(s, code: str) -> None:
    """Download the set symbol (SVG, for the HTML fallback) and set info (size, date) once."""
    path, meta = WORK_SETS / f"{code}.svg", WORK_SETS / f"{code}.meta.json"
    if path.exists() and meta.exists():
        return
    r = s.get(f"{API}/sets/{code}", timeout=30)
    time.sleep(0.12)
    r.raise_for_status()
    info = r.json()
    save_json(meta, {k: info.get(k) for k in ("code", "name", "released_at", "card_count", "printed_size")})
    path.write_bytes(fetch_bytes(s, info["icon_svg_uri"]))
    time.sleep(0.12)


MTGJSON = "https://mtgjson.com/api/v5"


def printed_texts(s, code: str) -> dict[str, str]:
    """{scryfall id: rules text as printed} for one set, from MTGJSON (cached).

    Scryfall only has the current Oracle wording ("When this creature enters"); the
    cards themselves say what was printed at the time ("When X enters the battlefield")."""
    path = WORK_SETS / f"{code}.printed.json"
    texts = load_json(path, None)
    if texts is None:
        texts = {}
        try:
            data = json.loads(lzma.decompress(fetch_bytes(s, f"{MTGJSON}/{code.upper()}.json.xz")))
            # Scryfall lacks the printed set size for some sets (WAR: 311 cards, 264 printed)
            meta_path = WORK_SETS / f"{code}.meta.json"
            meta = load_json(meta_path, None)
            if meta is not None and not meta.get("printed_size") and data["data"].get("baseSetSize"):
                save_json(meta_path, {**meta, "printed_size": data["data"]["baseSetSize"]})
            for c in data["data"]["cards"]:
                sid = c.get("identifiers", {}).get("scryfallId")
                if sid and c.get("originalText") and c.get("language", "English") == "English":
                    texts[sid] = c["originalText"]
        except Exception as e:                     # fall back to Oracle text
            print(f"  no printed text for {code}: {e}", file=sys.stderr)
        save_json(path, texts)
    return texts


def same_card_text(printed: str, oracle: str, name: str) -> bool:
    """Printed and Oracle texts differ only by wording updates ('enters the battlefield',
    self-reference by name...). MTGJSON sometimes attaches another card's text (SNC Most
    Wanted got a tri-land's): reject printed texts that don't resemble the Oracle text."""
    norm = lambda t: re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", "", t.replace(name, "this")).lower()
                            .replace("enters the battlefield", "enters")).strip()
    return difflib.SequenceMatcher(None, norm(printed), norm(oracle)).ratio() >= 0.6


def with_printed_text(s, card: dict) -> dict:
    """Card entry with the printed rules text (Oracle text kept in oracle_text_current)."""
    printed = printed_texts(s, card["set"]).get(card["id"])
    if printed and card.get("oracle_text") and not same_card_text(printed, card["oracle_text"], card["name"]):
        printed = None                                    # wrong text in MTGJSON: keep Oracle
    if printed and printed != card.get("oracle_text"):
        card = {**card, "oracle_text_current": card.get("oracle_text"), "oracle_text": printed}
    return card


def keep(card: dict) -> bool:
    if "image_uris" not in card or "art_crop" not in card["image_uris"]:
        return False
    if card.get("security_stamp") == "triangle":      # Universes Beyond (licensed IP = too easy)
        return False
    # special frames MSE's M15 template can't draw (text vanishes): Spacecraft, Planets (station)
    if re.search(r"\b(Spacecraft|Planet)\b", card.get("type_line", "")) or "Station" in (card.get("keywords") or []):
        return False
    if len(card.get("oracle_text", "")) > 420:          # would not fit the frame
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--rarity-weights", default=None,
                    help="e.g. 'common=55,uncommon=40,rare=4,mythic=1' (default: RARITY_WEIGHTS)")
    args = ap.parse_args()
    weights = parse_weights(args.rarity_weights or env("RARITY_WEIGHTS"))

    ensure_dirs()
    out_path = WORK / "real.json"
    cards = load_json(out_path, [])
    seen = {c["id"] for c in cards}
    names = {c["name"] for c in cards}
    s = session()

    tries = 0
    while len(cards) < args.count and tries < args.count * 6:
        tries += 1
        # rarity drawn first with the quiz weights, then a random card of that rarity
        r = s.get(f"{API}/cards/random", params={"q": f"({args.query}) r:{pick_rarity(weights)}"}, timeout=30)
        if r.status_code == 404:                          # no card of that rarity for this query
            r = s.get(f"{API}/cards/random", params={"q": args.query}, timeout=30)
        if r.status_code != 200:
            print(f"Scryfall error {r.status_code}: {r.text[:300]}", file=sys.stderr)
            if r.status_code in (400, 404):
                sys.exit(1)
            time.sleep(2)
            continue
        card = r.json()
        time.sleep(0.12)                                  # Scryfall asks for <10 req/s
        if card["id"] in seen or card["name"] in names or not keep(card):
            continue

        img = WORK_IMG / f"real_{card['id']}.jpg"
        normalize_image(fetch_bytes(s, card["image_uris"]["art_crop"]), img)
        time.sleep(0.12)
        ensure_set_icon(s, card["set"])

        entry = with_printed_text(s, {"id": card["id"], "real": True, **{k: card.get(k) for k in FIELDS},
                                      "art_crop": card["image_uris"]["art_crop"]})
        entry["image"] = img.name
        cards.append(entry)
        seen.add(card["id"]); names.add(card["name"])
        save_json(out_path, cards)                        # resumable
        print(f"[{len(cards)}/{args.count}] {card['name']}  ({card['set_name']})")

    print(f"Done: {len(cards)} real cards in {out_path}")


if __name__ == "__main__":
    main()
