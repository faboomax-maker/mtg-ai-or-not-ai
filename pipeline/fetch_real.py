"""Step 1 - Fetch real cards (text + art crop only) from the free Scryfall API.

Usage:
    python pipeline/fetch_real.py --count 60
    python pipeline/fetch_real.py --count 60 --query "set:dsk -type:basic"

Output: pipeline/work/real.json + pipeline/work/img/real_<id>.jpg

With an LLM key (OPENAI_API_KEY / LLM_API_KEY, or ANTHROPIC_API_KEY), the text of each card
is also read on its scan (italics included; SCAN_MODEL, default gpt-4.1-mini; SCAN_TEXT=0: off).
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

from realism import printed_type_line
from common import WORK, WORK_IMG, WORK_SETS, ensure_dirs, env, fetch_bytes, load_json, normalize_image, save_json, session

API = "https://api.scryfall.com"

# Single-faced paper cards of the regular sets, in three frame eras (Future Sight's frame,
# Planar Chaos' colorshifted cards and other special frames are left out).
BASE_QUERY = ("game:paper layout:normal lang:en (st:expansion or st:core) -is:funny -is:promo "
              "-is:universesbeyond -is:colorshifted -frame:future -type:basic -type:planeswalker")
ERAS = {
    "old": "(frame:1993 or frame:1997)",           # 1993-2003, white-bordered core sets included
    "modern": "frame:2003",                          # 8th Edition / Mirrodin -> Magic 2014
    "current": "frame:2015 year>=2016 -is:reprint",  # M15 frame
}
ERA_WEIGHTS = {"old": 1, "modern": 1, "current": 1}
DEFAULT_QUERY = f"{BASE_QUERY} {ERAS['current']}"


def era_query(era: str) -> str:
    return f"{BASE_QUERY} {ERAS[era]}"


def era_of(frame: str | None) -> str:
    return {"1993": "old", "1997": "old", "2003": "modern"}.get(frame or "", "current")

# Rares and mythics are the cards players know by heart: a famous real card is spotted at
# once, and so is a fake "mythic" nobody has heard of. Both pools (real cards here, AI card
# profiles in generate_fake.py) are drawn with these weights.
RARITY_WEIGHTS = {"common": 55, "uncommon": 40, "rare": 4, "mythic": 1}


def parse_weights(text: str | None, default: dict | None = None) -> dict[str, float]:
    """'common=55,uncommon=40,rare=4,mythic=1' -> dict (missing keys keep the default)."""
    weights = dict(RARITY_WEIGHTS if default is None else default)
    for part in (text or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            weights[k.strip().lower()] = float(v)
    return weights


def pick_rarity(weights: dict[str, float]) -> str:
    return random.choices(list(weights), weights=list(weights.values()))[0]


FIELDS = ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
          "power", "toughness", "loyalty", "rarity", "colors", "cmc", "keywords", "produced_mana", "edhrec_rank",
          "set", "set_name", "artist", "collector_number", "released_at", "scryfall_uri",
          "frame", "border_color")


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


def printed_texts(s, code: str) -> dict[str, dict]:
    """{scryfall id: {"text", "type"} as printed} for one set, from MTGJSON (cached).

    Scryfall only has the current Oracle wording ("When this creature enters"); the
    cards themselves say what was printed at the time ("When X enters the battlefield")."""
    path = WORK_SETS / f"{code}.printed2.json"
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
                if sid and c.get("language", "English") == "English" and (c.get("originalText") or c.get("originalType")):
                    texts[sid] = {"text": c.get("originalText"), "type": c.get("originalType")}
        except Exception as e:                     # fall back to Oracle text
            print(f"  no printed text for {code}: {e}", file=sys.stderr)
        save_json(path, texts)
    return texts


OLD_WORDING = [
    (r"enters the battlefield|comes into play", "enters"),
    (r"remove (.*?) from the game", r"exile \1"), (r"removed from the game", "exiled"),
    (r"is put into a graveyard from play", "dies"), (r"put into a graveyard from play", "dies"),
    (r"this (creature|artifact|enchantment|land|spell|permanent)", "this"),
    (r"converted mana cost", "mana value"), (r"target creature or player", "any target"),
    (r"\bplay(ed|s)?\b", r"cast\1"),
]


def gatherer_symbols(text: str | None) -> str | None:
    """Clean-up of the printed texts of old cards (from Gatherer): old tap/untap symbols
    'ocT' / 'ocQ', costs in one brace '{1W}', activated abilities without their colon
    ('{U} Mountainwalk until end of turn')."""
    if not text:
        return text
    text = re.sub(r"\boc([TQ])\b", r"{\1}", text)
    text = re.sub(r"\{(\d*)([WUBRGC]+)\}", lambda m: "".join(f"{{{x}}}" for x in
                  ([m.group(1)] if m.group(1) else []) + list(m.group(2))), text)
    return re.sub(r"(?m)^((?:\{[^}]+\})+) (?=[A-Z])", r"\1: ", text)


def same_card_text(printed: str, oracle: str, name: str, threshold: float = 0.6) -> bool:
    """Printed and Oracle texts differ only by wording updates ('enters the battlefield',
    self-reference by name...). MTGJSON sometimes attaches another card's text (SNC Most
    Wanted got a tri-land's): reject printed texts that don't resemble the Oracle text."""
    def norm(t: str) -> str:
        t = re.sub(r"\([^)]*\)", "", t.replace(name, "this")).lower()
        for old, new in OLD_WORDING:               # 1990s-2000s wording -> today's Oracle wording
            t = re.sub(old, new, t)
        return re.sub(r"\s+", " ", t).strip()
    return difflib.SequenceMatcher(None, norm(printed), norm(oracle)).ratio() >= threshold


# ------------------------------------------------------------ text read on the scan
# MTGJSON/Scryfall texts miss what only the printed card shows: which words are in italics
# (ability words, reminder text, named modes) and small wording differences. A vision model
# reads the card from the scan of this very printing; its reading is kept only if it agrees
# with the known text (same symbols, numbers and abilities), so it can fix but never invent.
SCAN_SYSTEM = """You transcribe the text box of a Magic: The Gathering card from a photo of the
printed card, exactly as printed, character for character. Answer with JSON only:
{"type_line": "...", "rules": "...", "flavor": "..."}.
- type_line: the type line, with " — " between types and subtypes.
- rules: the rules text only (no flavor text). One line per paragraph/ability as printed,
  separated by \\n; join lines that only wrap. Mark every italic span with <i>...</i> (reminder
  text in parentheses, ability words before " — ", italic mode names...). Write mana and tap
  symbols in braces: {T}, {Q}, {2}{G}, {W/U}, {E}. Use "—" for dashes and "−" for minus signs.
  Planeswalker abilities start with their loyalty cost: "+1: ...", "−3: ...".
- flavor: the italic flavor text under the rules (null if none), without <i> tags; keep a \\n
  only before an attribution line starting with "—".
Never correct, modernise or complete the text: copy what is printed."""
SCAN_MODEL = {"openai": "gpt-4.1-mini", "anthropic": "claude-haiku-4-5"}


def scan_llm() -> str | None:
    """Provider for the scan reading (SCAN_TEXT=0 turns it off), from the keys available."""
    if env("SCAN_TEXT", "1") == "0":
        return None
    if env("LLM_API_KEY") or env("OPENAI_API_KEY"):
        return "openai"
    return "anthropic" if env("ANTHROPIC_API_KEY") else None


def scan_model(llm: str) -> str | None:
    """Default reading model; None (= LLM_MODEL) for OpenAI-compatible services other than OpenAI."""
    key = env("LLM_API_KEY") or env("OPENAI_API_KEY") or ""
    openai = key.startswith("sk-") and not key.startswith("sk-or-") and not env("LLM_BASE_URL")
    return SCAN_MODEL[llm] if llm == "anthropic" or openai else None


def _plain(t: str) -> str:
    return re.sub(r"</?i>", "", t or "")


def _tokens(t: str) -> list[str]:
    """Mana symbols and numbers outside reminder text: must be identical on both readings."""
    t = re.sub(r"\([^)]*\)", "", _plain(t)).replace("−", "-")
    return sorted(re.findall(r"\{[^}]+\}|\d+", t))


def scan_agrees(scan: dict, card: dict) -> str | None:
    """Why the scan reading can't be trusted (None: it can)."""
    rules, known = scan.get("rules") or "", card.get("oracle_text") or ""
    # cards of the 1990s were often reworded since ("If Elvish Spirit Guide is in your hand, you
    # may remove it from the game..." -> "Exile this card from your hand: ..."): a looser match
    # is enough, the symbols and numbers still have to be the same
    old = (card.get("released_at") or "") < "2003-07-28"
    if not same_card_text(_plain(rules), known, card["name"], 0.5 if old else 0.9):
        return "rules text differs"
    if _tokens(rules) != _tokens(known):
        return "symbols/numbers differ"
    if not old and len([l for l in rules.split("\n") if l.strip()]) != len([l for l in known.split("\n") if l.strip()]):
        return "line count differs"
    return None


def read_scan(s, card: dict, png_url: str, llm: str) -> dict:
    """{"type_line", "rules" (with <i> marks), "flavor"} read on the scan, cached per card."""
    path = WORK_SETS / f"{card['set']}.scan_text.json"
    cache = load_json(path, {})
    if card["id"] not in cache:
        from generate_fake import call_llm              # (generate_fake imports this module)
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(fetch_bytes(s, png_url))).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92)
        time.sleep(0.12)
        text = call_llm(llm, SCAN_SYSTEM, f"Transcribe the text of this card, «{card['name']}».",
                        image=buf.getvalue(), detail="high", timeout=90,
                        model=env("SCAN_MODEL") or scan_model(llm), temperature=0)
        cache[card["id"]] = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        save_json(path, cache)
    return cache[card["id"]]


def with_scan_text(s, card: dict, png_url: str | None, llm: str | None) -> dict:
    """Card entry with the text exactly as printed (italics in `printed_markup`), when the
    scan reading agrees with the known text; otherwise unchanged."""
    if not (png_url and llm):
        return card
    try:
        scan = read_scan(s, card, png_url, llm)
    except (Exception, SystemExit) as e:                 # a bonus, never a blocker
        print(f"  scan not read for {card['name']}: {e}", file=sys.stderr)
        return card
    why = scan_agrees(scan, card)
    if why:
        print(f"  scan reading of {card['name']} ignored: {why}", file=sys.stderr)
        return card
    rules = scan["rules"].replace(" - ", " — ").strip()
    card = {**card, "oracle_text": _plain(rules), "printed_markup": rules}
    flavor = (scan.get("flavor") or "").strip()
    if flavor and card.get("flavor_text") and difflib.SequenceMatcher(
            None, flavor.lower(), card["flavor_text"].lower()).ratio() >= 0.9:
        card["flavor_text"] = flavor
    tl = re.sub(r"\s+[-–]\s+", " — ", (scan.get("type_line") or "").strip())
    if tl and tl.split("—")[0].strip() == card["type_line"].split("—")[0].strip() and \
            difflib.SequenceMatcher(None, tl, card["type_line"]).ratio() >= 0.8:
        card["type_line"] = tl
    elif tl and (card.get("released_at") or "") < "2007-10-12":
        # older type lines ("Summon Knight", "Enchant Creature", "Creature — Cleric" before
        # Lorwyn added "Human"): any words the card's current type line or its era has
        known = set(re.findall(r"\w+", card.get("type_line_current") or card["type_line"]))
        era_words = {"Summon", "Legend", "Enchant", "Creature", "Land", "Artifact", "World", "Interrupt",
                     "Mana", "Source", "Enchantment", "Wall"}
        stem = lambda words: {w.rstrip("s") for w in words}          # "Summon Knights"
        if stem(re.findall(r"\w+", tl)) <= stem(known | era_words):
            card["type_line"] = tl
    return card


def with_printed_text(s, card: dict) -> dict:
    """Card entry with the printed rules text (Oracle text kept in oracle_text_current)."""
    entry = printed_texts(s, card["set"]).get(card["id"]) or {}
    printed, ptype = gatherer_symbols(entry.get("text")), entry.get("type")
    # (older printings were reworded more by Oracle updates: "As Body Double comes into play, you
    # may choose..." -> "You may have this creature enter as a copy...")
    threshold = 0.45 if (card.get("released_at") or "") < "2010-01-01" else 0.6
    if printed and card.get("oracle_text") and not same_card_text(printed, card["oracle_text"], card["name"], threshold):
        printed = ptype = None                            # wrong card in MTGJSON: keep Oracle
    if printed and printed != card.get("oracle_text"):
        card = {**card, "oracle_text_current": card.get("oracle_text"), "oracle_text": printed}
    # printed type line: creature types renamed since (MTGJSON updates its "original" type too;
    # the exact old types, "Summon Knight", come from the scan: with_scan_text)
    printed_tl = printed_type_line(card["type_line"], card.get("released_at") or "")
    if printed_tl != card["type_line"]:
        card = {**card, "type_line_current": card["type_line"], "type_line": printed_tl}
    return card


def keep(card: dict) -> bool:
    if "image_uris" not in card or "art_crop" not in card["image_uris"]:
        return False
    if card.get("security_stamp") == "triangle" or "universesbeyond" in (card.get("promo_types") or []):
        return False                                  # Universes Beyond (licensed IP = too easy)
    # special frames MSE's M15 template can't draw (text vanishes): Spacecraft, Planets (station)
    if re.search(r"\b(Spacecraft|Planet)\b", card.get("type_line", "")) or "Station" in (card.get("keywords") or []):
        return False
    if "Planeswalker" in card.get("type_line", ""):    # famous characters, frame hard to match: none
        return False
    if len(card.get("oracle_text", "")) > 420:          # would not fit the frame
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--query", default=None, help="one Scryfall query instead of the era mix")
    ap.add_argument("--rarity-weights", default=None,
                    help="e.g. 'common=55,uncommon=40,rare=4,mythic=1' (default: RARITY_WEIGHTS)")
    ap.add_argument("--era-weights", default=None,
                    help="e.g. 'old=1,modern=1,current=1' (default: ERA_WEIGHTS)")
    args = ap.parse_args()
    weights = parse_weights(args.rarity_weights or env("RARITY_WEIGHTS"))
    eras = parse_weights(args.era_weights or env("ERA_WEIGHTS"), ERA_WEIGHTS)
    llm = scan_llm()
    print(f"text read on the scans: {llm or 'off (no API key or SCAN_TEXT=0)'}")

    ensure_dirs()
    out_path = WORK / "real.json"
    cards = load_json(out_path, [])
    seen = {c["id"] for c in cards}
    names = {c["name"] for c in cards}
    s = session()

    tries = 0
    while len(cards) < args.count and tries < args.count * 6:
        tries += 1
        # frame era and rarity drawn first with the quiz weights, then a random card of both
        query = args.query or era_query(pick_rarity(eras))
        r = s.get(f"{API}/cards/random", params={"q": f"({query}) r:{pick_rarity(weights)}"}, timeout=30)
        if r.status_code == 404:                          # no card of that rarity (old sets: no mythics)
            r = s.get(f"{API}/cards/random", params={"q": query}, timeout=30)
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
        entry = with_scan_text(s, entry, card["image_uris"].get("png"), llm)
        entry["image"] = img.name
        cards.append(entry)
        seen.add(card["id"]); names.add(card["name"])
        save_json(out_path, cards)                        # resumable
        print(f"[{len(cards)}/{args.count}] {card['name']}  ({card['set_name']}, {era_of(card.get('frame'))} frame)")

    print(f"Done: {len(cards)} real cards in {out_path}")


if __name__ == "__main__":
    main()
