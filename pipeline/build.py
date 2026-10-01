"""Step 3 - Put real + AI cards into the static site (docs/), for one game mode.

Two stages, so that big decks can be made by several jobs in parallel:
- chunk: the cards made by one job (pipeline/work) -> a folder with their images, public
  data and answers (sealed with QUIZ_ADMIN_TOKEN when set: job artifacts can be downloaded).
- merge: chunks -> the mode's deck, replacing it or adding to it (--append). Duplicates
  between chunks and with the existing deck are dropped (same card name; an AI card whose art
  comes from a real card of the deck, or whose art is already used by another AI card), and
  the added cards keep as many real cards as AI ones.

Modes: "normal" (shown as "Facile") -> docs/data/cards.json + docs/img/normal/,
       "hardcore" -> docs/data/hardcore.json + docs/img/hardcore/.
Answers: with the game server (LEADERBOARD=1), they are NOT in the public deck: they go to
pipeline/work/key-<mode>.json, sent to the server by upload_deck.py. Without it, they stay in
the deck, lightly obfuscated, and the game is played in the browser alone.

Usage:
    python pipeline/build.py [--mode normal|hardcore]            # this job's cards -> the deck
    python pipeline/build.py --chunk out/chunk                     # this job's cards -> a chunk
    python pipeline/build.py --mode M --merge DIR [DIR...] [--append]
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import random
import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

from common import DOCS, WORK, WORK_IMG, env, load_json, save_json, session
from render_mse import WORK_CARDS

PUBLIC = ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
          "power", "toughness", "loyalty", "rarity", "colors")
DECK_FILE = {"normal": "cards.json", "hardcore": "hardcore.json"}


def seal(secret, key: str) -> str:
    raw = json.dumps(secret, ensure_ascii=False).encode()
    k = hashlib.sha256(key.encode()).digest()
    return base64.b64encode(bytes(b ^ k[i % len(k)] for i, b in enumerate(raw))).decode()


def unseal(sealed: str, key: str):
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


def with_server() -> bool:
    return env("LEADERBOARD", "") == "1"


def stamp_index() -> None:
    """New version stamp on the site's CSS/JS links: browsers fetch fresh files, not cached ones."""
    index = DOCS / "index.html"
    if index.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d%H%M")
        index.write_text(re.sub(r"\?v=[\w-]+", f"?v={stamp}", index.read_text(encoding="utf-8")),
                         encoding="utf-8")


# ------------------------------------------------------------------ chunk
def make_chunk(out: Path, balance: bool = True) -> int:
    """This job's rendered cards -> out/img/*.webp + out/cards.json ({img, card} list, where
    card = public data) + out/key.json (answers, sealed with QUIZ_ADMIN_TOKEN when set)."""
    rendered = WORK_CARDS.exists() and any(WORK_CARDS.glob("*.png"))
    ok = (lambda c: (WORK_CARDS / f"{c['id']}.png").exists()) if rendered else (lambda c: bool(c.get("image")))
    real = [c for c in load_json(WORK / "real.json", []) if ok(c)]
    fake = [c for c in load_json(WORK / "fake.json", []) if ok(c)]
    if not real or not fake:
        raise SystemExit(f"Need both pools with {'rendered cards' if rendered else 'art'} "
                         f"(real={len(real)}, ai={len(fake)}).")
    if balance:
        n = min(len(real), len(fake))
        real, fake = random.sample(real, n), random.sample(fake, n)
    shutil.rmtree(out, ignore_errors=True)
    (out / "img").mkdir(parents=True)
    cards, key = [], {}
    for c in real + fake:
        if rendered:                                      # full card image, symbol included
            name = secrets.token_hex(8) + ".webp"
            Image.open(WORK_CARDS / f"{c['id']}.png").save(out / "img" / name, "WEBP", quality=86, method=6)
        else:
            name = secrets.token_hex(8) + ".jpg"
            shutil.copyfile(WORK_IMG / c["image"], out / "img" / name)
        cards.append({"img": name, "card": {**{k: c.get(k) for k in PUBLIC}, "card": rendered, "img": name}})
        key[name] = secret_of(c)
    token = env("QUIZ_ADMIN_TOKEN")
    save_json(out / "cards.json", cards)
    save_json(out / "key.json", {"sealed": seal(key, token)} if token else key)
    print(f"Chunk: {len(real)} real + {len(fake)} AI cards -> {out}")
    return len(cards)


def chunk_key(folder: Path) -> dict:
    data = load_json(folder / "key.json", {})
    if "sealed" in data:
        token = env("QUIZ_ADMIN_TOKEN") or sys.exit("QUIZ_ADMIN_TOKEN needed to read the chunks' answers")
        return unseal(data["sealed"], token)
    return data


# ------------------------------------------------------------------ merge
def existing_deck(mode: str) -> tuple[list[dict], dict]:
    """The mode's published cards and their answers (from the server, or unsealed from the deck)."""
    deck = load_json(DOCS / "data" / DECK_FILE[mode], None)
    if not deck or not deck.get("cards"):
        return [], {}
    if deck.get("api"):
        token = env("QUIZ_ADMIN_TOKEN") or sys.exit("QUIZ_ADMIN_TOKEN needed to read the deck's answers")
        r = session().get(f"{deck['api']}/admin/deck", params={"mode": mode}, timeout=60,
                          headers={"Authorization": f"Bearer {token}"})
        if not r.ok:
            sys.exit(f"cannot read the {mode} deck's answers from the server: HTTP {r.status_code} {r.text[:200]}")
        key = r.json().get("key") or {}
    else:
        key = {c["img"]: unseal(c["s"], c["img"]) for c in deck["cards"] if c.get("s")}
    cards = [{k: v for k, v in c.items() if k != "s"} for c in deck["cards"] if c["img"] in key]
    return cards, key


def merge(mode: str, chunks: list[Path], append: bool, expected: int = 0, force: bool = False) -> None:
    img_dir = DOCS / "img" / mode
    old_cards, key = existing_deck(mode) if append else ([], {})
    names = {c["name"].lower() for c in old_cards}
    real_names = {c["name"].lower() for c in old_cards if key[c["img"]]["real"]}
    used_art = {key[c["img"]].get("art_from", "").lower() for c in old_cards if not key[c["img"]]["real"]} - {""}

    new_real, new_ai = [], []
    for folder in chunks:
        if not (folder / "cards.json").exists():
            print(f"  (no cards in {folder}: that job failed)"); continue
        ckey = chunk_key(folder)
        for e in load_json(folder / "cards.json", []):
            secret = ckey.get(e["img"])
            if secret:
                (new_real if secret["real"] else new_ai).append((folder, e, secret))
    random.shuffle(new_real); random.shuffle(new_ai)
    kept_real, kept_ai, dropped = [], [], 0
    for folder, e, secret in new_real:                   # real cards first: they are the reference
        n = e["card"]["name"].lower()
        if n in names:
            dropped += 1; continue
        names.add(n); real_names.add(n); kept_real.append((folder, e, secret))
    for folder, e, secret in new_ai:
        n, art = e["card"]["name"].lower(), (secret.get("art_from") or "").lower()
        if n in names or (art and (art in real_names or art in used_art)):
            dropped += 1; continue
        names.add(n); kept_ai.append((folder, e, secret))
        if art:
            used_art.add(art)
    k = min(len(kept_real), len(kept_ai))                 # as many real cards as AI ones
    added = kept_real[:k] + kept_ai[:k]
    if not added and not old_cards:
        sys.exit("no cards to publish")
    if not append and expected and k < expected / 2 and not force:
        # most chunks failed: never replace a deck with a much smaller one
        current = load_json(DOCS / "data" / DECK_FILE[mode], {}).get("count", 0)
        if current > 2 * k:
            print(f"::error::Only {k} + {k} cards of the {expected} + {expected} requested: the {mode} deck "
                  f"({current} cards) is kept. Look at the failed chunks, then run again, or add these "
                  f"cards with « Ajouter au paquet existant ».")
            sys.exit(1)

    if not append:
        shutil.rmtree(img_dir, ignore_errors=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    for old in (DOCS / "img").glob("*.*"):                 # images of the old single-deck layout
        old.unlink()
    shutil.rmtree(DOCS / "sets", ignore_errors=True)
    new_cards = []
    for folder, e, secret in added:
        shutil.copyfile(folder / "img" / e["img"], img_dir / e["img"])
        new_cards.append(e["card"])
        key[e["img"]] = secret
    cards = old_cards + new_cards
    random.shuffle(cards)
    key = {c["img"]: key[c["img"]] for c in cards}
    sealed = not with_server()
    if sealed:
        cards = [{**c, "s": seal(key[c["img"]], c["img"])} for c in cards]
    save_json(DOCS / "data" / DECK_FILE[mode],
              {"generated": dt.date.today().isoformat(), "mode": mode, "count": len(cards),
               "img": f"img/{mode}/", "api": None if sealed else (env("QUIZ_API_URL") or "").rstrip("/"),
               "cards": cards})
    save_json(WORK / f"key-{mode}.json", key)
    stamp_index()
    real_n = sum(1 for c in cards if key[c["img"]]["real"])
    print(f"Deck {mode}: {len(cards)} cards ({real_n} real / {len(cards) - real_n} AI); "
          f"{'added' if append else 'new'}: {k} real + {k} AI; dropped duplicates: {dropped}; "
          f"answers {'in the deck (no leaderboard)' if sealed else f'in work/key-{mode}.json'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=list(DECK_FILE), default="normal")
    ap.add_argument("--chunk", type=Path, help="write this job's cards to a chunk folder")
    ap.add_argument("--merge", type=Path, nargs="+", help="chunk folders to put in the deck")
    ap.add_argument("--append", action="store_true", help="add to the mode's deck instead of replacing it")
    ap.add_argument("--expected", type=int, default=0, help="cards of each type requested (safety check)")
    ap.add_argument("--force", action="store_true", help="replace the deck even with far fewer cards")
    ap.add_argument("--no-balance", action="store_true")
    args = ap.parse_args()
    if args.chunk:
        make_chunk(args.chunk, not args.no_balance)
    elif args.merge:
        merge(args.mode, args.merge, args.append, args.expected, args.force)
    else:                                                  # one job: straight into the deck
        tmp = Path(tempfile.mkdtemp())
        make_chunk(tmp / "chunk", not args.no_balance)
        merge(args.mode, [tmp / "chunk"], args.append)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
