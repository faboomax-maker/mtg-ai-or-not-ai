"""Step 2 - Generate AI cards (text with an LLM, art with an image model).

Each fake card copies the "profile" (colours, card type, rarity, mana value,
flavour text or not) of a real card, so the fake and real pools have the same
distribution and only the content can give them away.

Usage:
    python pipeline/generate_fake.py --count 60
    python pipeline/generate_fake.py --count 60 --llm openai --images pollinations

LLM providers (--llm):
    anthropic  ANTHROPIC_API_KEY            (model: LLM_MODEL, default claude-haiku-4-5)
    openai     any OpenAI-compatible API: OpenAI, OpenRouter, Ollama (local, free)...
               LLM_API_KEY or OPENAI_API_KEY, LLM_MODEL, LLM_BASE_URL (default: OpenAI for
               an OpenAI key, otherwise https://openrouter.ai/api/v1)
Image providers (--images):
    replicate     REPLICATE_API_TOKEN, model REPLICATE_MODEL (default black-forest-labs/flux-schnell,
                  ~0.003 $ / image; e.g. black-forest-labs/flux-1.1-pro ~0.04 $, flux-2-pro)
    openai        OPENAI_API_KEY, gpt-image-1 low quality (IMAGE_MODEL / IMAGE_QUALITY to change)
    pollinations  POLLINATIONS_KEY (optional depending on their current policy)
    placeholder   coloured gradients, for testing the site without spending anything
    none          skip images (drop your own files in pipeline/work/img/fake_<id>.jpg)

Output: pipeline/work/fake.json + pipeline/work/img/fake_<id>.jpg (resumable)
        pipeline/work/raw/: untouched full-resolution images + index.json (name, prompt), for reuse
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import random
import re
import sys
import time
import uuid
from urllib.parse import quote

from collections import Counter, defaultdict

from PIL import Image

from common import (MANA_RE, WORK, WORK_IMG, WORK_SETS, ensure_dirs, env, fetch_bytes, load_json,
                    normalize_image, save_json, session)

WORK_RAW = WORK / "raw"                      # original full-resolution AI images, for reuse
from fetch_real import API, DEFAULT_QUERY, FIELDS, keep, with_printed_text

BATCH = 8
# Never name the game, a set or a "card" here: image models then paint logos and titles.
ART_STYLE = ("Traditional fantasy oil painting by a seasoned professional illustrator: realistic anatomy "
             "and proportions, confident painterly brushwork, dramatic yet natural lighting, rich detail, "
             "strong readable composition with one clear focal subject, atmospheric depth. "
             "Pure illustration with no text, no letters, no logo, no title, no signature, "
             "no watermark, no border, no frame.")
BRANDS = re.compile(r"\b(?:(?-i:Magic)(?::? the Gathering)?|MTG|Wizards of the Coast|"
                    r"trading card(?: game)?s?|cards?)\b(?:[’']s)?", re.I)   # "magic" stays


def art_prompt(c: dict) -> str:
    """Image prompt: the scene, the set's world and art direction, the era - no brand names."""
    year = (c.get("released_at") or "")[:4]
    world = " ".join(filter(None, [c.get("set_description"), c.get("art_style")]))
    world = re.sub(r"\s{2,}", " ", BRANDS.sub("", world)).strip()
    return (f"{c['art_description']} {world} Fantasy art as painted around {year}. {ART_STYLE}")

SYSTEM = """You are a senior Magic: The Gathering designer at Wizards of the Coast.
You write brand-new cards that are indistinguishable from cards printed in recent
Standard-legal expansions. Rules you always follow:
- Exact templating of the set, as printed on its cards: the examples show the text as
  printed at the time, so copy their wording exactly. Older cards say "enters the
  battlefield" and refer to themselves by their own name ("When Grim Scavenger enters the
  battlefield"); cards printed since 2024 say "enters" and "this creature". Include
  reminder text in parentheses when the examples do for the same keyword.
- Modal cards put each mode on its own line after a bullet: "Choose one —\\n• Destroy
  target artifact.\\n• Create a Treasure token." (never "Choose one — X; or Y").
- Ability words and named modes are followed by " — " ("Landfall — Whenever...",
  "• Smash the Chest — Destroy target artifact.").
- Power level of a normal set: mostly commons/uncommons are modest; no broken cards,
  no joke cards, no references to real-world brands or franchises.
- Use only existing keywords and mechanics; do not invent new keywords.
- Names must be original (never an existing card name) and sound like real Magic names.
- Flavor text: short, evocative, sometimes a quote attributed to a character
  (e.g. "—Kasra, lighthouse keeper"). Newlines inside flavor text are rare.
- Mana costs use braces: {2}{G}{G}. Oracle text uses \\n between abilities.
You answer with a JSON array only, no commentary."""


def type_bucket(type_line: str) -> str:
    """'Legendary Creature — Elf Druid' -> 'Legendary Creature' (subtypes left to the LLM)."""
    return type_line.split("—")[0].strip()


def spec_from(card: dict) -> dict:
    colors = "".join(card.get("colors") or []) or "colorless"
    return {"colors": colors, "type": type_bucket(card["type_line"]), "rarity": card["rarity"],
            "mana_value": int(card.get("cmc") or 0), "flavor_text": bool(card.get("flavor_text"))}


def example_text(c: dict) -> dict:
    return {k: c[k] for k in ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
                              "power", "toughness", "loyalty", "rarity") if c.get(k)}


# --------------------------------------------------------------------------- LLM
def check(r, fatal=(400, 401, 403, 404)) -> None:
    """Raise with the provider's own error message; stop at once on config errors."""
    if r.ok:
        return
    msg = f"HTTP {r.status_code} from {r.url}: {r.text[:500]}"
    if r.status_code in fatal:                  # bad key / model / URL: retrying won't help
        sys.exit(f"API config error -> {msg}")
    raise RuntimeError(msg)


def call_llm(provider: str, system: str, user: str) -> str:
    s = session()
    if provider == "anthropic":
        key = env("ANTHROPIC_API_KEY") or sys.exit("ANTHROPIC_API_KEY missing")
        r = s.post("https://api.anthropic.com/v1/messages", timeout=300, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": env("LLM_MODEL", "claude-haiku-4-5"), "max_tokens": 6000,
                  "temperature": 1.0, "system": system,
                  "messages": [{"role": "user", "content": user}]})
        check(r)
        return "".join(b.get("text", "") for b in r.json()["content"])
    key = env("LLM_API_KEY") or env("OPENAI_API_KEY")
    # An OpenAI key (sk-..., not OpenRouter's sk-or-...) goes to OpenAI itself by default.
    is_openai = key and key.startswith("sk-") and not key.startswith("sk-or-")
    base = env("LLM_BASE_URL", "https://api.openai.com/v1" if is_openai else "https://openrouter.ai/api/v1").rstrip("/")
    model = env("LLM_MODEL", "gpt-4.1-mini" if "api.openai.com" in base else "anthropic/claude-haiku-4.5")
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    r = s.post(f"{base}/chat/completions", timeout=600, headers=headers, json={
        "model": model, "temperature": 1.0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    check(r)
    return r.json()["choices"][0]["message"]["content"]


def parse_array(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError("no JSON array in answer")
    return json.loads(m.group(0))


def validate(c: dict, spec: dict) -> str | None:
    for k in ("name", "type_line", "oracle_text", "art_description"):
        if not isinstance(c.get(k), str) or not c[k].strip():
            return f"missing {k}"
    if not MANA_RE.match(c.get("mana_cost") or ""):
        return "bad mana cost"
    tl = c["type_line"]
    if "Creature" in tl and not (c.get("power") and c.get("toughness")):
        return "creature without P/T"
    if "Planeswalker" in tl and not c.get("loyalty"):
        return "planeswalker without loyalty"
    if len(c["oracle_text"]) > 480 or len(c.get("flavor_text") or "") > 200:
        return "too long"
    if re.search(r"\bCARDNAME\b|~", c["oracle_text"]):
        return "placeholder name in text"
    if re.search(r"[Cc]hoose (?:one|two|one or both|one or more) —(?!\n•)", c["oracle_text"]):
        return "modes not bulleted"
    return None


def name_is_new(s, name: str) -> bool:
    r = s.get(f"{API}/cards/named", params={"exact": name}, timeout=30)
    time.sleep(0.12)
    return r.status_code == 404


# ------------------------------------------------------------------------ images
def gen_image(provider: str, prompt: str, seed: int) -> bytes | None:
    s = session()
    if provider == "replicate":
        token = env("REPLICATE_API_TOKEN") or sys.exit("REPLICATE_API_TOKEN missing")
        h = {"authorization": f"Bearer {token}", "content-type": "application/json", "prefer": "wait"}
        model = env("REPLICATE_MODEL", "black-forest-labs/flux-schnell")
        inp = {"prompt": prompt, "aspect_ratio": "4:3", "seed": seed}
        if model.startswith("black-forest-labs/"):
            inp.update(output_format="jpg", output_quality=95)
        if model.endswith("flux-schnell"):
            inp.update(num_outputs=1, go_fast=True)
        for attempt in range(8):                # low-credit accounts are heavily rate limited
            r = s.post(f"https://api.replicate.com/v1/models/{model}/predictions",
                       headers=h, timeout=180, json={"input": inp})
            if r.status_code != 429:
                break
            ra = r.headers.get("retry-after", "")
            wait = float(ra) + 1 if ra.replace(".", "", 1).isdigit() else 10 + attempt * 5
            print(f"  replicate rate limit, waiting {wait:.0f}s")
            time.sleep(wait)
        check(r, fatal=(401, 403, 404))
        pred = r.json()
        while pred.get("status") not in ("succeeded", "failed", "canceled"):
            time.sleep(1.5)
            pred = s.get(pred["urls"]["get"], headers=h, timeout=60).json()
        if pred["status"] != "succeeded":
            raise RuntimeError(f"replicate: {pred.get('error')}")
        out = pred["output"]
        return fetch_bytes(s, out[0] if isinstance(out, list) else out)
    if provider == "openai":
        key = env("OPENAI_API_KEY") or env("LLM_API_KEY") or sys.exit("OPENAI_API_KEY missing")
        r = s.post("https://api.openai.com/v1/images/generations", timeout=300,
                   headers={"authorization": f"Bearer {key}", "content-type": "application/json"},
                   json={"model": env("IMAGE_MODEL", "gpt-image-1"), "prompt": prompt,
                         "size": "1536x1024", "quality": env("IMAGE_QUALITY", "low"), "n": 1})
        check(r, fatal=(401, 403, 404))         # 400 = this prompt refused: skip the card
        return base64.b64decode(r.json()["data"][0]["b64_json"])
    if provider == "pollinations":
        url =(f"https://gen.pollinations.ai/image/{quote(prompt)}"
               f"?model=flux&width=832&height=608&seed={seed}&nologo=true")
        headers = {"authorization": f"Bearer {env('POLLINATIONS_KEY')}"} if env("POLLINATIONS_KEY") else {}
        return fetch_bytes(s, url, headers=headers)
    if provider == "placeholder":
        from placeholder import gradient_jpeg
        return gradient_jpeg(seed)
    return None


def save_raw(raw: bytes, card: dict, prompt: str) -> None:
    """Keep the untouched full-resolution image + an index (card name, prompt) for reuse."""
    fmt = (Image.open(io.BytesIO(raw)).format or "jpg").lower().replace("jpeg", "jpg")
    name = f"{re.sub(r'[^a-z0-9]+', '-', card['name'].lower()).strip('-')}_{card['id'][:6]}.{fmt}"
    (WORK_RAW / name).write_bytes(raw)
    index = load_json(WORK_RAW / "index.json", [])
    index.append({"file": name, "name": card["name"], "set": card["set_name"],
                  "type_line": card["type_line"], "prompt": prompt})
    save_json(WORK_RAW / "index.json", index)


# -------------------------------------------------------------------------- main
def set_pool(code: str, quiz_ids: set[str]) -> list[dict]:
    """Cards of one real set, used as examples/profiles (quiz cards excluded)."""
    path = WORK_SETS / f"{code}.json"
    cards = load_json(path, None)
    if cards is None:
        r = session().get(f"{API}/cards/search", timeout=60,
                          params={"q": f"e:{code} {DEFAULT_QUERY}", "order": "name"})
        time.sleep(0.12)
        cards = []
        if r.status_code == 200:
            s = session()
            cards = [with_printed_text(s, {"id": c["id"], **{k: c.get(k) for k in FIELDS}})
                     for c in r.json()["data"] if keep(c)]
        save_json(path, cards)
    return [c for c in cards if c["id"] not in quiz_ids]


BRIEF_SYSTEM = """You are an expert on Magic: The Gathering sets and their art direction.
Answer with one JSON object only, no commentary."""


def set_brief(llm: str, code: str, meta: dict, pool: list[dict]) -> dict:
    """Description, mechanics and art direction of a real set, written once by the LLM (cached)."""
    path = WORK_SETS / f"{code}.brief.json"
    brief = load_json(path, None)
    if brief:
        return brief
    keywords = Counter(k for c in pool for k in (c.get("keywords") or [])).most_common(15)
    types = Counter(w for c in pool if "—" in c["type_line"]
                    for w in c["type_line"].split("—")[1].split()).most_common(15)
    user = (
        f"Set: «{meta['name']}» ({code.upper()}), released {meta['released_at']}.\n"
        f"Most frequent keywords/ability words in its cards: {[k for k, _ in keywords]}\n"
        f"Most frequent subtypes: {[t for t, _ in types]}\n\n"
        "Return a JSON object with keys:\n"
        "- description: 2-3 sentences on the plane/world, story and themes of this set;\n"
        "- mechanics: the set's signature mechanics and how they are worded on cards;\n"
        "- art_style: 2-3 sentences for an illustrator: setting, architecture, costumes, "
        "creatures, palette, lighting and painting style of the set's illustrations. Describe the "
        "world only: never name the game, the set, the publisher or any product."
    )
    try:
        text = call_llm(llm, BRIEF_SYSTEM, user)
        brief = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    except Exception as e:                       # the brief is a bonus, never a blocker
        print(f"  no brief for {code}: {e}", file=sys.stderr)
        brief = {}
    brief = {k: str(brief.get(k) or "") for k in ("description", "mechanics", "art_style")}
    save_json(path, brief)
    return brief


def real_artists(s) -> set[str]:
    """Names of every real Magic illustrator (Scryfall catalog), to never reuse one."""
    path = WORK_SETS / "artists.json"
    names = load_json(path, None)
    if names is None:
        r = s.get(f"{API}/catalog/artist-names", timeout=60)
        names = r.json().get("data", []) if r.ok else []
        save_json(path, names)
    return {n.lower() for n in names}


def set_meta(code: str, name: str, pool: list[dict]) -> dict:
    """Release date and size of a real set (saved by fetch_real.py)."""
    meta = load_json(WORK_SETS / f"{code}.meta.json", None) or {}
    dates = sorted(c["released_at"] for c in pool if c.get("released_at"))
    return {"name": name, "printed_size": None, "card_count": None,
            **meta, "released_at": meta.get("released_at") or (dates[0] if dates else "2020-01-01")}


# Used only if the LLM gives no name or a real artist's name (checked against Scryfall).
FALLBACK_ARTISTS = ["Mireille Castan", "Tobiah Wrenfield", "Anouk Velder", "Dario Mestrovic",
                    "Selene Adebayo", "Jorund Haakes", "Ines Carvalho-Roth", "Kenji Arakawa-Bell"]


def collector_number(meta: dict, taken: set[str]) -> str:
    """A free number within the set's main range, like a real card of that set."""
    size = meta.get("printed_size") or meta.get("card_count") or 250
    free = [str(n) for n in range(1, size + 1) if str(n) not in taken]
    return random.choice(free or [str(size + 1)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--llm", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--images", choices=["replicate", "openai", "pollinations", "placeholder", "none"],
                    default="replicate")
    ap.add_argument("--no-name-check", action="store_true")
    args = ap.parse_args()

    ensure_dirs()
    WORK_RAW.mkdir(parents=True, exist_ok=True)
    out_path = WORK / "fake.json"
    fakes = load_json(out_path, [])
    real = load_json(WORK / "real.json", [])
    if not real or not all(c.get("set") for c in real):
        sys.exit("Run fetch_real.py first (the AI cards reuse the sets of the real cards).")
    quiz_ids = {c["id"] for c in real}
    s = session()
    banned = {c["name"].lower() for c in real}

    # Same set distribution as the real pool: every AI card gets a real set symbol,
    # and is designed from that set's own cards, so its mechanics match the symbol.
    real_sets = Counter(c["set"] for c in real)
    set_names = {c["set"]: c["set_name"] for c in real}
    artists = real_artists(s)
    FALLBACK_ARTISTS[:] = [a for a in FALLBACK_ARTISTS if a.lower() not in artists] or ["Mireille Castan"]
    numbers: dict[str, set[str]] = defaultdict(set)   # collector numbers already on a quiz card
    for c in real + fakes:
        numbers[c["set"]].add(str(c.get("collector_number")))
    target = {code: round(k * args.count / len(real)) for code, k in real_sets.items()}
    fails = 0
    while len(fakes) < args.count and fails < 10:
        have = Counter(c["set"] for c in fakes)
        deficits = {code: target[code] - have[code] for code in target if target[code] > have[code]}
        code = max(deficits, key=deficits.get) if deficits else random.choice(list(real_sets.elements()))
        pool = set_pool(code, quiz_ids)
        if len(pool) < 6:                       # too few cards to learn the set from
            target.pop(code, None); real_sets.pop(code, None)
            if not real_sets:
                sys.exit("No usable set pools (Scryfall unreachable?)")
            continue
        banned |= {c["name"].lower() for c in pool}
        meta = set_meta(code, set_names[code], pool)
        brief = set_brief(args.llm, code, meta, pool)
        n = min(BATCH, args.count - len(fakes), max(deficits.get(code, 1), 1))
        specs = [spec_from(c) for c in random.choices(pool, k=n)]
        shots = [example_text(c) for c in random.sample(pool, min(10, len(pool)))]
        about = "".join(f"{k.replace('_', ' ').capitalize()}: {v}\n" for k, v in brief.items() if v)
        user = (
            f"All cards below come from the real set «{set_names[code]}» ({meta['released_at'][:4]}). "
            "Your new cards will be printed in that same set: reuse its mechanics, keywords, "
            "creature types, factions and world.\n" + about +
            "Examples from the set (match their templating, tone and power level):\n"
            + json.dumps(shots, ensure_ascii=False, indent=1)
            + f"\n\nDesign {n} NEW cards, one per profile below, in this order:\n"
            + json.dumps(specs, indent=1)
            + "\n\nReturn a JSON array of objects with keys: name, mana_cost, type_line, oracle_text, "
              "flavor_text (null if the profile says false), power, toughness, loyalty (strings or null), "
              "rarity, art_description (one or two sentences describing the illustration: subject, "
              "setting, mood; no artist names, no text in the image), artist (an invented, "
              "believable illustrator full name; never the name of a real Magic artist)."
        )
        try:
            batch = parse_array(call_llm(args.llm, SYSTEM, user))
        except Exception as e:
            fails += 1; print("LLM error:", e, file=sys.stderr); annotate("warning", f"LLM error: {e}")
            time.sleep(3); continue
        for c, spec in zip(batch, specs):
            err = validate(c, spec)
            if not err and c["name"].lower() in banned:
                err = "name already used"
            if not err and not args.no_name_check and not name_is_new(s, c["name"]):
                err = "existing card name"
            if err:
                print(f"  rejected {c.get('name')!r}: {err}")
                annotate("notice", f"rejected {c.get('name')!r}: {err}"); continue
            banned.add(c["name"].lower())
            artist = str(c.get("artist") or "").strip()
            if not artist or artist.lower() in artists:  # never credit a real artist for AI art
                artist = random.choice(FALLBACK_ARTISTS)
            number = collector_number(meta, numbers[code])
            numbers[code].add(number)
            fakes.append({"id": uuid.uuid4().hex, "real": False,
                          **{k: (c.get(k) or None) for k in
                             ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
                              "power", "toughness", "loyalty", "art_description")},
                          "rarity": spec["rarity"], "colors": list(spec["colors"]) if spec["colors"] != "colorless" else [],
                          "set": code, "set_name": set_names[code], "artist": artist,
                          "collector_number": number, "released_at": meta["released_at"],
                          "set_description": brief.get("description", ""),
                          "art_style": brief.get("art_style", ""), "image": None})
            print(f"[{len(fakes)}/{args.count}] {c['name']}")
        save_json(out_path, fakes)

    # --- images
    if args.images != "none":
        for i, c in enumerate(fakes):
            img = WORK_IMG / f"fake_{c['id']}.jpg"
            if img.exists():
                c["image"] = img.name; continue
            prompt = art_prompt(c)
            try:
                raw = gen_image(args.images, prompt, seed=random.randint(1, 2**31 - 1))
            except Exception as e:
                print(f"  image failed for {c['name']}: {e}", file=sys.stderr)
                annotate("warning", f"image failed: {e}"); continue
            save_raw(raw, c, prompt)
            normalize_image(raw, img)
            c["image"] = img.name
            save_json(out_path, fakes)
            print(f"  art {i + 1}/{len(fakes)}: {c['name']}")
    else:  # pick up manually added files
        for c in fakes:
            if (WORK_IMG / f"fake_{c['id']}.jpg").exists():
                c["image"] = f"fake_{c['id']}.jpg"
    save_json(out_path, fakes)
    with_art = sum(1 for c in fakes if c["image"])
    print(f"Done: {len(fakes)} AI cards, {with_art} with art.")
    if not fakes:
        sys.exit("No AI card generated: see the LLM errors / rejections above.")
    if not with_art and args.images != "none":
        sys.exit("No AI card got an illustration: see the image errors above.")


def annotate(level: str, msg) -> None:
    """On GitHub Actions, also show the message on the run summary page."""
    if env("GITHUB_ACTIONS"):
        print(f"::{level}::{str(msg).replace(chr(10), ' ')[:900]}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if isinstance(e.code, str):
            annotate("error", e.code)
        raise
    except Exception as e:
        annotate("error", f"{type(e).__name__}: {e}")
        raise
