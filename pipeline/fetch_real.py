"""Step 1 - Fetch real cards (text + art crop only) from the free Scryfall API.

Usage:
    python pipeline/fetch_real.py --count 60
    python pipeline/fetch_real.py --count 60 --query "set:dsk -type:basic"

Output: pipeline/work/real.json + pipeline/work/img/real_<id>.jpg
"""
from __future__ import annotations

import argparse
import sys
import time

from common import WORK, WORK_IMG, WORK_SETS, ensure_dirs, fetch_bytes, load_json, normalize_image, save_json, session

API = "https://api.scryfall.com"

# Modern single-faced paper cards, same frame era as what the AI imitates.
DEFAULT_QUERY = (
    "game:paper layout:normal lang:en frame:2015 year>=2016 "
    "(st:expansion or st:core) -is:funny -is:reprint -is:promo -type:basic"
)

FIELDS = ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
          "power", "toughness", "loyalty", "rarity", "colors", "cmc",
          "set", "set_name", "artist", "scryfall_uri")


def ensure_set_icon(s, code: str) -> None:
    """Download the official set symbol (SVG) once; the site colours it by rarity."""
    path = WORK_SETS / f"{code}.svg"
    if path.exists():
        return
    r = s.get(f"{API}/sets/{code}", timeout=30)
    time.sleep(0.12)
    r.raise_for_status()
    path.write_bytes(fetch_bytes(s, r.json()["icon_svg_uri"]))
    time.sleep(0.12)


def keep(card: dict) -> bool:
    if "image_uris" not in card or "art_crop" not in card["image_uris"]:
        return False
    if card.get("security_stamp") == "triangle":      # Universes Beyond (licensed IP = too easy)
        return False
    if len(card.get("oracle_text", "")) > 420:          # would not fit the frame
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--query", default=DEFAULT_QUERY)
    args = ap.parse_args()

    ensure_dirs()
    out_path = WORK / "real.json"
    cards = load_json(out_path, [])
    seen = {c["id"] for c in cards}
    names = {c["name"] for c in cards}
    s = session()

    tries = 0
    while len(cards) < args.count and tries < args.count * 6:
        tries += 1
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

        entry = {"id": card["id"], "real": True, **{k: card.get(k) for k in FIELDS}}
        entry["image"] = img.name
        cards.append(entry)
        seen.add(card["id"]); names.add(card["name"])
        save_json(out_path, cards)                        # resumable
        print(f"[{len(cards)}/{args.count}] {card['name']}  ({card['set_name']})")

    print(f"Done: {len(cards)} real cards in {out_path}")


if __name__ == "__main__":
    main()
