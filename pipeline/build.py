"""Step 3 - Merge real + AI cards into the static site (docs/).

- Keeps the same number of real and AI cards (unless --no-balance).
- Copies every illustration under a random file name (no "real_"/"fake_" hint).
- Stores the answer and credits lightly obfuscated, so they don't show up in
  plain text in the JSON (it's a party game, not a vault).

Usage: python pipeline/build.py
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

from common import DOCS, WORK, WORK_IMG, WORK_SETS, load_json, save_json
from render_mse import WORK_CARDS

PUBLIC = ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
          "power", "toughness", "loyalty", "rarity", "colors")


def seal(secret: dict, key: str) -> str:
    raw = json.dumps(secret, ensure_ascii=False).encode()
    k = hashlib.sha256(key.encode()).digest()
    return base64.b64encode(bytes(b ^ k[i % len(k)] for i, b in enumerate(raw))).decode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-balance", action="store_true")
    args = ap.parse_args()

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

    img_dir = DOCS / "img"
    shutil.rmtree(img_dir, ignore_errors=True)
    img_dir.mkdir(parents=True)

    set_dir = DOCS / "sets"
    shutil.rmtree(set_dir, ignore_errors=True)
    set_dir.mkdir(parents=True)

    out = []
    for c in random.sample(real + fake, len(real) + len(fake)):
        if rendered:                                      # full card image, symbol included
            name = secrets.token_hex(8) + ".webp"
            Image.open(WORK_CARDS / f"{c['id']}.png").save(img_dir / name, "WEBP", quality=86, method=6)
            secret = {"real": c["real"]}
            if c["real"]:
                secret.update(set=c.get("set_name"), artist=c.get("artist"), url=c.get("scryfall_uri"))
            else:
                secret.update(set=c.get("set_name"))      # symbol borrowed, said so on reveal
                if c.get("art_from"):                     # real art borrowed from another card
                    secret.update(artist=c.get("artist"), art_from=c["art_from"])
            out.append({**{k: c.get(k) for k in PUBLIC}, "card": True, "img": name, "s": seal(secret, name)})
            continue
        name = secrets.token_hex(8) + ".jpg"
        shutil.copyfile(WORK_IMG / c["image"], img_dir / name)
        icon = WORK_SETS / f"{c.get('set')}.svg"
        has_icon = bool(c.get("set")) and icon.exists()
        if has_icon:
            shutil.copyfile(icon, set_dir / icon.name)
        secret = {"real": c["real"]}
        if c["real"]:
            secret.update(set=c.get("set_name"), artist=c.get("artist"), url=c.get("scryfall_uri"))
        elif has_icon:
            secret.update(set=c.get("set_name"))          # symbol borrowed, said so on reveal
        out.append({**{k: c.get(k) for k in PUBLIC}, "set_icon": c["set"] if has_icon else None,
                    "img": name, "s": seal(secret, name)})

    save_json(DOCS / "data" / "cards.json",
              {"generated": dt.date.today().isoformat(), "count": len(out), "cards": out})
    print(f"Site data: {len(out)} cards ({len(real)} real / {len(fake)} AI) -> docs/")
    # new version stamp on the site's CSS/JS links: browsers fetch fresh files, not cached ones
    index = DOCS / "index.html"
    if index.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d%H%M")
        index.write_text(re.sub(r"\?v=[\w-]+", f"?v={stamp}", index.read_text(encoding="utf-8")),
                         encoding="utf-8")


if __name__ == "__main__":
    main()
