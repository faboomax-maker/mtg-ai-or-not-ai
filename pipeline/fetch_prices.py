"""Prices for the game « Plus cher ou moins cher ? » - one line per card, from Scryfall's free bulk data.

Usage:
    python pipeline/fetch_prices.py                  # -> docs/data/prix.json
    python pipeline/fetch_prices.py --min-eur 0.2    # leave out cheaper cards

Source: the "Oracle Cards" bulk file (one printing per card, the one Scryfall shows by default),
with its Cardmarket trend price in euros (prices.eur) and its Commander popularity (edhrec_rank,
1 = the most played). The game shows that same printing, so the picture and the price match.

Output (compact): {"generated": "YYYY-MM-DD", "cards": [[name, scryfall_id, cents, rank, set, number], ...]}
rank is 0 when EDHREC does not rank the card (not legal in Commander, or almost never played).
The image is rebuilt in the browser from the id: cards.scryfall.io/normal/front/<a>/<b>/<id>.jpg
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

from common import DOCS, session

BULK = "https://api.scryfall.com/bulk-data"          # list of the bulk files; we take type "oracle_cards"

SKIP_SET_TYPES = {"token", "memorabilia", "funny", "art_series", "minigame", "alchemy", "vanguard",
                  "treasure_chest", "planechase", "archenemy"}
SKIP_LAYOUTS = {"token", "double_faced_token", "emblem", "art_series", "planar", "scheme", "vanguard",
                "augment", "host", "reversible_card"}


def keep(c: dict, min_eur: float) -> bool:
    if c.get("digital") or c.get("oversized") or c.get("lang", "en") != "en":
        return False
    if c.get("set_type") in SKIP_SET_TYPES or c.get("layout") in SKIP_LAYOUTS:
        return False
    if "Basic Land" in (c.get("type_line") or ""):
        return False
    eur = (c.get("prices") or {}).get("eur")
    return bool(eur) and float(eur) >= min_eur


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--min-eur", type=float, default=0.10, help="prix minimum (défaut 0,10 €)")
    ap.add_argument("--out", default=str(DOCS / "data" / "prix.json"))
    args = ap.parse_args()

    s = session()
    meta = s.get(BULK, timeout=60)
    meta.raise_for_status()
    files = meta.json().get("data") or []
    url = next((f.get("download_uri") for f in files if f.get("type") == "oracle_cards"), None)
    if not url:
        raise SystemExit("Fichier « oracle_cards » introuvable dans la liste Scryfall : "
                         + (", ".join(str(f.get("type")) for f in files) or meta.text[:300]))
    print("Téléchargement", url)
    r = s.get(url, timeout=600)
    r.raise_for_status()
    cards = r.json()

    rows = []
    for c in cards:
        if not keep(c, args.min_eur):
            continue
        rows.append([c["name"], c["id"], round(float(c["prices"]["eur"]) * 100), c.get("edhrec_rank") or 0,
                     c.get("set", ""), c.get("collector_number", "")])
    rows.sort(key=lambda x: x[2])
    out = {"generated": dt.date.today().isoformat(), "count": len(rows), "cards": rows}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    ranked = sum(1 for x in rows if x[3])
    print(f"{len(rows)} cartes avec un prix (dont {ranked} classées par EDHREC) -> {args.out}")


if __name__ == "__main__":
    main()
