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
    replicate     REPLICATE_API_TOKEN, FLUX schnell (~0.003 $ / image)
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

from collections import Counter

from PIL import Image

from common import (MANA_RE, WORK, WORK_IMG, WORK_SETS, ensure_dirs, env, fetch_bytes, load_json,
                    normalize_image, save_json, session)

WORK_RAW = WORK / "raw"                      # original full-resolution AI images, for reuse
from fetch_real import API, DEFAULT_QUERY, FIELDS, keep

BATCH = 8
ART_STYLE = ("epic fantasy illustration, detailed digital painting, modern trading card game art, "
             "dramatic cinematic lighting, rich colors, painterly brushwork, "
             "no text, no letters, no border, no frame, no watermark")

SYSTEM = """You are a senior Magic: The Gathering designer at Wizards of the Coast.
You write brand-new cards that are indistinguishable from cards printed in recent
Standard-legal expansions. Rules you always follow:
- Exact modern Oracle templating ("When this creature enters, ...", "any target",
  "Ward {2}", "Create a 1/1 white Soldier creature token.", "Activate only as a sorcery.").
  Since 2024, cards refer to themselves as "this creature"/"this artifact"/etc. except
  legendary cards, which use their short name. Look at the examples and copy their style.
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
    if len(c["oracle_text"]) > 420 or len(c.get("flavor_text") or "") > 200:
        return "too long"
    if re.search(r"\bCARDNAME\b|~", c["oracle_text"]):
        return "placeholder name in text"
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
        for attempt in range(8):                # low-credit accounts are heavily rate limited
            r = s.post("https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions",
                       headers=h, timeout=180, json={"input": {
                           "prompt": prompt, "aspect_ratio": "4:3", "output_format": "jpg",
                           "output_quality": 95, "num_outputs": 1, "seed": seed, "go_fast": True}})
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
            cards = [{"id": c["id"], **{k: c.get(k) for k in FIELDS}} for c in r.json()["data"] if keep(c)]
        save_json(path, cards)
    return [c for c in cards if c["id"] not in quiz_ids]


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
        n = min(BATCH, args.count - len(fakes), max(deficits.get(code, 1), 1))
        specs = [spec_from(c) for c in random.choices(pool, k=n)]
        shots = [example_text(c) for c in random.sample(pool, min(10, len(pool)))]
        user = (
            f"All cards below come from the real set «{set_names[code]}». Your new cards will be printed "
            "in that same set: reuse its mechanics, keywords, creature types, factions and world.\n"
            "Examples from the set (match their templating, tone and power level):\n"
            + json.dumps(shots, ensure_ascii=False, indent=1)
            + f"\n\nDesign {n} NEW cards, one per profile below, in this order:\n"
            + json.dumps(specs, indent=1)
            + "\n\nReturn a JSON array of objects with keys: name, mana_cost, type_line, oracle_text, "
              "flavor_text (null if the profile says false), power, toughness, loyalty (strings or null), "
              "rarity, art_description (one or two sentences describing the illustration: subject, "
              "setting, mood; no artist names, no text in the image)."
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
            fakes.append({"id": uuid.uuid4().hex, "real": False,
                          **{k: (c.get(k) or None) for k in
                             ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
                              "power", "toughness", "loyalty", "art_description")},
                          "rarity": spec["rarity"], "colors": list(spec["colors"]) if spec["colors"] != "colorless" else [],
                          "set": code, "set_name": set_names[code], "image": None})
            print(f"[{len(fakes)}/{args.count}] {c['name']}")
        save_json(out_path, fakes)

    # --- images
    if args.images != "none":
        for i, c in enumerate(fakes):
            img = WORK_IMG / f"fake_{c['id']}.jpg"
            if img.exists():
                c["image"] = img.name; continue
            prompt = f"{c['art_description']} {ART_STYLE}"
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
