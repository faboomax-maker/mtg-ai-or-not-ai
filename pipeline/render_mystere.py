"""Render the cards of the day of « Carte mystère » with Magic Set Editor (same M15 frame as the quiz).

For today's and tomorrow's cards (docs/data/mystere.json) when not rendered yet, two images:
  - blank : the frame, the blurred art, the set symbol and the bottom line, but no name, cost,
            type line, rules text nor P/T. The game lays the hidden text over it, at the M15
            positions (docs/games/mystere/style.css, .my-mse);
  - full  : the real card, shown when the game is over.
They go to docs/img/mystere/<random>.webp, and their names into the (sealed) card of the day.
Day after day this renders one card (tomorrow's), ready before its Paris midnight; today's is
rendered too if missing (first run, or a day the workflow did not run). Images of past days are deleted.

Needs Magic Set Editor (Windows): see render_mse.py. Usage: python pipeline/render_mystere.py
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
import shutil
import time

from PIL import Image, ImageFilter

import mystere
from common import DOCS, WORK, fetch_bytes, normalize_image, session
from render_mse import render

DATA = DOCS / "data" / "mystere.json"
IMG = DOCS / "img" / "mystere"
TMP = WORK / "mystere"
AHEAD = 1                                    # render up to tomorrow's card
BLUR = 22                                    # art blur of the blank card (px on the 640 px art)


def art_crop(s, card: dict) -> str:
    i = card["id"]
    return f"https://cards.scryfall.io/art_crop/front/{i[0]}/{i[1]}/{i}.jpg"


def no_size_steps_for_blanks() -> None:
    """The blank cards have no text: one render each instead of render_mse's ten text sizes."""
    import render_mse
    original = render_mse.size_steps
    render_mse.size_steps = lambda c: [] if c["id"].endswith("-blank") else original(c)


def main() -> None:
    if not DATA.exists():
        raise SystemExit(f"{DATA} not found: run pipeline/fetch_prices.py first")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    IMG.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    s = session()
    today = mystere.paris_today()
    since, until = (today - dt.timedelta(days=1)).isoformat(), (today + dt.timedelta(days=AHEAD)).isoformat()
    keep, done, todo = set(), 0, []

    for date, blob in sorted(data["days"].items()):
        card = mystere.unseal(blob, date)
        imgs = card.get("img") or {}
        if imgs and all((IMG / f).exists() for f in imgs.values()):
            keep.update(imgs.values())
            continue
        if not (today.isoformat() <= date <= until):     # only today's and tomorrow's cards
            if date >= since and imgs:                    # yesterday's: kept (late players)
                keep.update(imgs.values())
            continue
        print(f"{date}: {card['n']}")
        art = TMP / f"art-{card['id']}.jpg"
        try:
            normalize_image(fetch_bytes(s, art_crop(s, card)), art)
        except Exception as e:
            print(f"  no art: {e}")
            continue
        blurred = TMP / f"blur-{card['id']}.jpg"
        Image.open(art).filter(ImageFilter.GaussianBlur(BLUR)).save(blurred, quality=90)

        base = {"id": "my-" + card["id"], "set": card.get("s") or "", "collector_number": card.get("cn") or "",
                "rarity": card.get("r") or "common", "artist": card.get("a") or "",
                "released_at": card.get("d") or "2020-01-01", "frame": "2015"}   # always the M15 frame
        full = {**base, "name": card["n"], "mana_cost": card.get("m") or "", "type_line": card.get("t") or "",
                "oracle_text": card.get("o") or "", "flavor_text": card.get("ft") or None,
                "power": card.get("p"), "toughness": card.get("h")}
        blank = {**base, "id": base["id"] + "-blank", "name": "", "mana_cost": "", "type_line": "",
                 "oracle_text": "", "flavor_text": None, "power": "", "toughness": ""}
        todo.append((date, card, full, art, blank, blurred))

    if todo:
        # every card (full and blank) in ONE render: Magic Set Editor is started once per set and
        # each set symbol is drawn once, instead of once per card and version
        out = TMP / "out"
        shutil.rmtree(out, ignore_errors=True)
        no_size_steps_for_blanks()
        t0 = time.time()
        try:
            render([x for d, c, f, a, b, bl in todo for x in ((f, a), (b, bl))], out)
        except SystemExit as e:              # render() exits when a card fails: keep the others
            print(f"  {e}")
        print(f"Rendu MSE : {time.time() - t0:.0f} s")
        for date, card, full, _, blank, _ in todo:
            fp, bp = out / f"{full['id']}.png", out / f"{blank['id']}.png"
            if not (fp.exists() and bp.exists()):
                print(f"{date}: not rendered (the game falls back to its own frame)")
                continue
            full_img, blank_img = Image.open(fp).convert("RGB"), Image.open(bp).convert("RGB")
            names = {"b": secrets.token_hex(8) + ".webp", "f": secrets.token_hex(8) + ".webp"}
            blank_img.save(IMG / names["b"], "WEBP", quality=86, method=6)
            full_img.save(IMG / names["f"], "WEBP", quality=86, method=6)
            card["img"] = names
            card["size"] = list(full_img.size)
            data["days"][date] = mystere.seal(card, date)
            keep.update(names.values())
            done += 1

    for f in IMG.glob("*.webp"):              # days gone from the schedule
        if f.name not in keep:
            f.unlink()
    DATA.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Carte mystère : {done} carte(s) rendue(s), {len(keep) // 2} disponible(s).")


if __name__ == "__main__":
    main()
