"""Step 3 - Merge real + AI cards into the static site (docs/), for one game mode.

- Keeps the same number of real and AI cards (unless --no-balance).
- Copies every card image under a random file name (no "real_"/"fake_" hint).
- Modes: "normal" -> docs/data/cards.json + docs/img/normal/,
         "hardcore" -> docs/data/hardcore.json + docs/img/hardcore/ (the other mode is untouched).
- Answers: with the leaderboard Worker (LEADERBOARD=1), they are NOT in the public deck: they go
  to pipeline/work/key-<mode>.json, uploaded to the Worker, which reveals each one after the
  player's answer (so scores can't be faked). Without it, they stay in the deck, lightly
  obfuscated, and the game is played in the browser alone (no leaderboard).

Usage: python pipeline/build.py [--mode normal|hardcore]
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import re
import random
import secrets
import shutil

from PIL import Image

from common import DOCS, WORK, WORK_IMG, env, load_json, save_json
from render_mse import WORK_CARDS

PUBLIC = ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
          "power", "toughness", "loyalty", "rarity", "colors")
DECK_FILE = {"normal": "cards.json", "hardcore": "hardcore.json"}


def seal(secret: dict, key: str) -> str:
    raw = json.dumps(secret, ensure_ascii=False).encode()
    k = hashlib.sha256(key.encode()).digest()
    return base64.b64encode(bytes(b ^ k[i % len(k)] for i, b in enumerate(raw))).decode()


def unseal(sealed: str, key: str) -> dict:
    raw = base64.b64decode(sealed)
    k = hashlib.sha256(key.encode()).digest()
    return json.loads(bytes(b ^ k[i % len(k)] for i, b in enumerate(raw)).decode())


def secret_of(c: dict) -> dict:
    """What the reveal tells about a card (truth and credits)."""
    secret = {"real": c["real"]}
    if c["real"]:
        secret.update(set=c.get("set_name"), artist=c.get("artist"), url=c.get("scryfall_uri"))
    else:
        secret.update(set=c.get("set_name"))              # symbol borrowed, said so on reveal
        if c.get("art_from"):                             # real art borrowed from another card
            secret.update(artist=c.get("artist"), art_from=c["art_from"])
    return secret


def stamp_index() -> None:
    """New version stamp on the site's CSS/JS links: browsers fetch fresh files, not cached ones."""
    index = DOCS / "index.html"
    if index.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d%H%M")
        index.write_text(re.sub(r"\?v=[\w-]+", f"?v={stamp}", index.read_text(encoding="utf-8")),
                         encoding="utf-8")


def write_deck(mode: str, out: list[dict], key: dict, sealed: bool) -> None:
    img_prefix = f"img/{mode}/"
    save_json(DOCS / "data" / DECK_FILE[mode],
              {"generated": dt.date.today().isoformat(), "mode": mode, "count": len(out),
               "img": img_prefix, "api": None if sealed else (env("QUIZ_API_URL") or "").rstrip("/"),
               "cards": out})
    save_json(WORK / f"key-{mode}.json", key)
    stamp_index()


def migrate(mode: str) -> None:
    """One-time: move the current single deck (answers sealed, images in docs/img/) to the
    per-mode layout, and write its key file (for the Worker)."""
    path = DOCS / "data" / "cards.json"
    deck = load_json(path, None)
    if not deck or deck.get("mode"):
        raise SystemExit("nothing to migrate")
    img_dir = DOCS / "img" / mode
    img_dir.mkdir(parents=True, exist_ok=True)
    sealed = env("LEADERBOARD", "") != "1"
    key, out = {}, []
    for c in deck["cards"]:
        (DOCS / "img" / c["img"]).replace(img_dir / c["img"])
        key[c["img"]] = unseal(c["s"], c["img"])
        out.append(c if sealed else {k: v for k, v in c.items() if k != "s"})
    write_deck(mode, out, key, sealed)
    print(f"Migrated {len(out)} cards to the {mode} deck")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=list(DECK_FILE), default="normal")
    ap.add_argument("--no-balance", action="store_true")
    ap.add_argument("--migrate", action="store_true", help="move the old single deck to --mode's layout")
    args = ap.parse_args()
    if args.migrate:
        return migrate(args.mode)
    sealed = env("LEADERBOARD", "") != "1"               # no Worker: answers stay in the deck

    # With Magic Set Editor renders (render_mse.py), only rendered cards are used, for both pools.
    rendered = WORK_CARDS.exists() and any(WORK_CARDS.glob("*.png"))
    ok = (lambda c: (WORK_CARDS / f"{c['id']}.png").exists()) if rendered else (lambda c: bool(c.get("image")))
    real = [c for c in load_json(WORK / "real.json", []) if ok(c)]
    fake = [c for c in load_json(WORK / "fake.json", []) if ok(c)]
    if not real or not fake:
        raise SystemExit(f"Need both pools with {'rendered cards' if rendered else 'art'} "
                         f"(real={len(real)}, ai={len(fake)}).")
    if not args.no_balance:
        n = min(len(real), len(fake))
        real, fake = random.sample(real, n), random.sample(fake, n)

    img_dir = DOCS / "img" / args.mode
    shutil.rmtree(img_dir, ignore_errors=True)
    img_dir.mkdir(parents=True)
    for old in (DOCS / "img").glob("*.*"):                 # images of the old single-deck layout
        old.unlink()
    shutil.rmtree(DOCS / "sets", ignore_errors=True)       # (set icons of the pre-MSE layout)

    out, key = [], {}
    for c in random.sample(real + fake, len(real) + len(fake)):
        if rendered:                                      # full card image, symbol included
            name = secrets.token_hex(8) + ".webp"
            Image.open(WORK_CARDS / f"{c['id']}.png").save(img_dir / name, "WEBP", quality=86, method=6)
        else:
            name = secrets.token_hex(8) + ".jpg"
            shutil.copyfile(WORK_IMG / c["image"], img_dir / name)
        key[name] = secret_of(c)
        entry = {**{k: c.get(k) for k in PUBLIC}, "card": rendered, "img": name}
        if sealed:
            entry["s"] = seal(key[name], name)
        out.append(entry)

    write_deck(args.mode, out, key, sealed)
    print(f"Site data ({args.mode}): {len(out)} cards ({len(real)} real / {len(fake)} AI) -> docs/, "
          f"answers {'in the deck (no leaderboard)' if sealed else 'in ' + f'work/key-{args.mode}.json'}")


if __name__ == "__main__":
    main()
