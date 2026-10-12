"""Prices for the game « Plus cher ou moins cher ? » - one line per card, from Scryfall's free bulk data.
Also writes the cards of the day of « Carte mystère » (pipeline/mystere.py -> docs/data/mystere.json).

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
import gzip
import json
import re

import bannies
import legal_check
import mystere
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


def strings(x):
    """Every string inside a JSON value (nested objects and lists included)."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def download_url(s, entry: dict) -> str:
    """The file's address in a bulk-data entry: download_uri / jsonl_download_uri, or any link to a
    .json or .jsonl file (gzipped or not),
    or else the entry's own page (uri), fetched in full."""
    for key in ("download_uri", "jsonl_download_uri", "download_url", "url"):
        if isinstance(entry.get(key), str) and entry[key].startswith("http"):
            return entry[key]
    for v in strings(entry):
        if v.startswith("http") and re.search(r"\.jsonl?(\.gz)?(\?|$)", v):
            return v
    if isinstance(entry.get("uri"), str):
        full = s.get(entry["uri"], timeout=60)
        full.raise_for_status()
        detail = full.json()
        for key in ("download_uri", "jsonl_download_uri", "download_url"):
            if isinstance(detail.get(key), str):
                return detail[key]
    raise SystemExit("Pas de lien de téléchargement pour « oracle_cards ». Champs reçus : "
                     + json.dumps(entry, ensure_ascii=False)[:600])


def parse_cards(raw: bytes) -> list[dict]:
    """A JSON array of cards, or JSON Lines (one card per line, Scryfall's format since 2026)."""
    text = raw.decode("utf-8").lstrip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--min-eur", type=float, default=0.10, help="prix minimum (défaut 0,10 €)")
    ap.add_argument("--out", default=str(DOCS / "data" / "prix.json"))
    args = ap.parse_args()

    s = session()
    meta = s.get(BULK, timeout=60)
    meta.raise_for_status()
    files = meta.json().get("data") or []
    entry = next((f for f in files if f.get("type") == "oracle_cards"), None)
    if not entry:
        raise SystemExit("Fichier « oracle_cards » introuvable dans la liste Scryfall : "
                         + (", ".join(str(f.get("type")) for f in files) or meta.text[:300]))
    url = download_url(s, entry)
    print("Téléchargement", url)
    r = s.get(url, timeout=600)
    r.raise_for_status()
    raw = r.content
    if raw[:2] == b"\x1f\x8b":                            # gzipped file served as is
        raw = gzip.decompress(raw)
    cards = parse_cards(raw)

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

    # « Carte mystère »: the cards of the day come from the same Scryfall file
    try:
        mystere.build(cards, DOCS / "data" / "mystere.json")
    except Exception as e:                            # the prices are published anyway
        print("Carte mystère : échec de la mise à jour :", e)

    # « Est-ce légal ? »: every card of the situations checked against its Oracle text
    try:
        legal_check.build(cards, DOCS / "games" / "legal" / "scenarios.json", DOCS / "data" / "legal-cards.json")
    except Exception as e:
        print("Est-ce légal : échec de la vérification :", e)

    # « Carte bannie ? »: banlists of Modern, Legacy and Duel Commander
    try:
        bannies.build(cards, DOCS / "data" / "bannies.json")
    except Exception as e:
        print("Carte bannie : échec de la mise à jour :", e)


if __name__ == "__main__":
    main()
