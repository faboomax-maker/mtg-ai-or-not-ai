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
    openai        OPENAI_API_KEY (or LLM_API_KEY), IMAGE_MODEL (default gpt-image-2.5-sunburst; or
                  gpt-image-2.5-flare), IMAGE_QUALITY (medium), IMAGE_SIZE (1536x1152 = 4:3);
                  reference images go through /v1/images/edits
    fal           FAL_KEY, FAL_MODEL (default fal-ai/flux-2/klein/4b/base/lora + LORA_URL/LORA_SCALE),
                  FAL_STEPS (50), FAL_GUIDANCE (3.5), FAL_IMAGE_SIZE (1280x960), negative prompt
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
import os
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
from fetch_real import API, BASE_QUERY, FIELDS, keep, parse_weights, with_printed_text
from realism import (KEYWORD_SINCE, add_missing_reminders, anachronism, art_focus, art_problem, artist_name, color_group,
                     fix_reminders, fix_templating, fix_type_line, fix_wording, misused_keywords,
                     fix_cost_order, flavor_fits, join_follow_ups, name_problem, old_frame_text, name_words, number_in_group, reminder_texts, rules_problem,
                     subtype_color_problem, printed_type_line,
                     tone_down, too_simple, uses_old_wording)

BATCH = 8
# Never name the game, a set or a "card" here: image models then paint logos and titles.
ART_PAINT = ("Traditional oil painting by a seasoned professional fantasy and science-fiction illustrator, "
             "true to the world described above: realistic anatomy and proportions, confident painterly "
             "brushwork with visible strokes and varied color. The focal subject is in sharp focus, "
             "crisply drawn with fine detail and a clear, well-lit silhouette; the background is painted "
             "a little more loosely but stays clear and readable - never blurry, foggy or muddy. "
             "Hand-made, not an airbrushed or plastic digital render. Natural lighting with good value "
             "contrast, restrained palette without neon glow, asymmetric readable composition with one "
             "clear focal subject.")
ART_CONSTRAINTS = ("Pure illustration with no text, no letters, no signs or lettering anywhere in the scene, "
                   "no logo, no title, no signature, no watermark, no border, no frame.")
ART_STYLE = f"{ART_PAINT} {ART_CONSTRAINTS}"
BRANDS = re.compile(r"\b(?:(?-i:Magic)(?::? the Gathering)?|MTG|Wizards of the Coast|"
                    r"trading card(?: game)?s?|cards?)\b(?:[’']s)?", re.I)   # "magic" stays


_NEW_SCENE = "Paint an entirely new scene: do not copy the subjects, characters or compositions of any reference."
REF_NOTES = {   # instruction matching the STYLE_REFS mode
    "mix": ("Reference images: the first ones are official illustrations of this same world - take its "
            "costumes, architecture, creatures and palette from them; the last one is a classic oil "
            "painting - imitate its brushwork and color handling. " + _NEW_SCENE),
    "set": ("The reference images are official illustrations of this same world by different artists: "
            "match their painting technique, palette, lighting and level of detail. " + _NEW_SCENE),
    "classic": ("The reference image is a classic oil painting: imitate its brushwork and color "
                "handling. " + _NEW_SCENE),
}


def ref_note() -> str:
    return REF_NOTES.get(env("STYLE_REFS", "mix"), REF_NOTES["mix"])

# Public-domain paintings (Wikimedia Commons, all "Public domain"), by kind of subject. One is
# added to the set's own illustrations to pull the model away from its polished default look.
CLASSICS = {
    "figure": ["John William Waterhouse - The Lady of Shalott - Google Art Project edit.jpg",
               "John William Waterhouse - The Crystal Ball.JPG",
               "Flaming June, by Frederic Lord Leighton (1830-1896).jpg",
               "John William Waterhouse - Hylas and the Nymphs.jpg",
               "Pyle Barbe Noire.jpg"],
    "battle": ["Eugène Delacroix - La liberté guidant le peuple.jpg",
               "Jean-Leon Gerome Pollice Verso.jpg",
               "Jean-Léon Gérôme - The Christian Martyrs' Last Prayer - Walters 37113.jpg"],
    "landscape": ["Albert Bierstadt - Among the Sierra Nevada, California - Google Art Project.jpg",
                  "Caspar David Friedrich - Wanderer above the sea of fog.jpg",
                  "Church Heart of the Andes.jpg",
                  "Arnold Böcklin - Die Toteninsel III (Alte Nationalgalerie, Berlin).jpg"],
    "creature": ["Saint George and the Dragon by Paolo Uccello (London) 01.jpg",
                 "John Bauer - The Princess and the Trolls - Google Art Project.jpg"],
    "cataclysm": ["John Martin - The Great Day of His Wrath - Google Art Project.jpg",
                  "Cole Thomas The Course of Empire Destruction 1836.jpg",
                  "Joseph Mallord William Turner - Snow Storm - Steam-Boat off a Harbour's Mouth - WGA23178.jpg"],
}
HUMANOIDS = {"Human", "Elf", "Dwarf", "Vampire", "Merfolk", "Kor", "Orc", "Goblin", "Kithkin", "Aetherborn",
             "Vedalken", "Viashino", "Leonin", "Minotaur", "Giant", "Zombie", "Siren", "Faerie", "Naga"}


def classic_ref(type_line: str) -> str:
    """URL of a public-domain painting suited to the card (Wikimedia thumbnail, 1024 px)."""
    t = type_line.lower()
    if "land" in t and "creature" not in t:
        kind = "landscape"
    elif "instant" in t or "sorcery" in t:
        kind = random.choice(["cataclysm", "battle"])
    elif "creature" in t:
        first = type_line.split("—")[1].split()[0] if "—" in type_line else ""
        kind = "figure" if first in HUMANOIDS else random.choice(["creature", "creature", "battle"])
    else:
        kind = random.choice(["figure", "landscape"])
    title = random.choice(CLASSICS[kind])
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(title)}?width=1024"


def subject(type_line: str) -> str:
    """What the image must visibly show, from the type line (a Human Soldier is a human)."""
    if "Creature" not in type_line or "—" not in type_line:
        return ""
    kinds = type_line.split("—")[1].strip()
    note = (" — an ordinary human being with a fully human face and body, no animal features"
            if kinds.split()[0] == "Human" else "")
    return f"Main subject: a {kinds}{note}. "


# LoRA for Replicate models that take one (black-forest-labs/flux-2-klein-4b-base-lora):
# "Light Fantasy" (FLUX.2 klein base 4B), trigger word "light_fantasy".
LORA_DEFAULT = ("https://huggingface.co/giannisan/light-fantasy-flux2-klein-base-lora/resolve/main/"
                "pytorch_lora_weights.safetensors")


def uses_lora(model: str) -> bool:
    return model.endswith("-lora") or model.endswith("/lora")


# fal.ai runs FLUX.2 klein base with LoRAs and lets us set the steps/guidance the base
# (undistilled) model needs - Replicate's version runs too few steps and comes out blurry.
FAL_DEFAULT = "fal-ai/flux-2/klein/4b/base/lora"
NEGATIVE = ("blurry, out of focus, foggy, muddy, low detail, low contrast, text, letters, signature, "
            "watermark, logo, frame, border, 3d render, cgi, anime, cartoon, plastic skin, airbrushed, "
            "deformed hands, extra fingers, extra limbs")


def lora_active() -> bool:
    """Is a LoRA (and its trigger word) used for the images of this run?"""
    provider = env("IMAGE_PROVIDER", "")
    return (provider == "fal" and uses_lora(env("FAL_MODEL", FAL_DEFAULT))) or \
        (provider == "replicate" and uses_lora(env("REPLICATE_MODEL", "")))


def refs_enabled() -> bool:
    """Does the image provider in use take reference images? With a LoRA the style comes from
    the LoRA, and the small klein model tends to copy references: off unless STYLE_REFS is set."""
    provider, model = env("IMAGE_PROVIDER", ""), env("REPLICATE_MODEL", "")
    if provider == "replicate" and uses_lora(model) and not env("STYLE_REFS"):
        return False
    return provider == "openai" or (provider == "replicate" and bool(ref_field(model)))


def ref_labels(n: int) -> str:
    """OpenAI's guide: name each input image by its index and give it one role."""
    mode = env("STYLE_REFS", "mix")
    world = "official illustrations of this same world - use them only for costumes, architecture, creatures and palette"
    classic = "a classic oil painting - use it only for its brushwork and color handling"
    if mode == "classic":
        labels = [f"Image 1: {classic}."]
    elif mode == "set":
        labels = [f"Images 1-{n}: {world}."]
    else:
        labels = [f"Images 1-{n - 1}: {world}." if n > 2 else f"Image 1: {world}.", f"Image {n}: {classic}."]
    return " ".join(labels) + (" Do not edit, reproduce or continue any input image: create a completely "
                               "new painting with its own subject and composition.")


def art_prompt(c: dict) -> str:
    """Image prompt: the subject, the scene, the set's world and art direction, the era - no brand names."""
    year = (c.get("released_at") or "")[:4]
    world = " ".join(filter(None, [c.get("set_description"), c.get("art_style")]))
    world = re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s{2,}", " ", BRANDS.sub("", world))).strip()
    refs = c.get("style_refs") if refs_enabled() else None
    if env("IMAGE_PROVIDER") == "openai":
        # OpenAI's prompting guide: short labeled segments, scene -> subject -> details -> constraints
        return "\n".join(filter(None, [
            "Intended use: a finished fantasy illustration, landscape 4:3, as painted by a professional illustrator.",
            f"Scene: {world} Painted around {year}.",
            f"Subject: {subject(c.get('type_line', ''))}{c['art_description']}",
            f"Details: {ART_PAINT}",
            f"References: {ref_labels(len(refs))}" if refs else "",
            f"Constraints: {ART_CONSTRAINTS}"]))
    note = ref_note() + " " if refs else ""
    trigger = f"{env('LORA_TRIGGER', 'light_fantasy')}, a detailed fantasy painting. " if lora_active() else ""
    return (f"{trigger}{subject(c.get('type_line', ''))}{c['art_description']} World and setting: {world} "
            f"Illustration as painted around {year}. {note}{ART_STYLE}")


def ref_field(model: str) -> str | None:
    """Replicate models that take reference images, and the name of that input."""
    if "/flux-2-klein" in model:
        return "images"                          # FLUX.2 klein (incl. base-lora): up to 5
    if "/flux-2" in model:
        return "input_images"                    # FLUX 2 pro/flex/max: up to 8
    if "nano-banana" in model or "seedream-4" in model:
        return "image_input"                     # Nano Banana (Pro), Seedream 4.x
    return None


def style_refs(card: dict, pool: list[dict], k: int = 3) -> list[str]:
    """Reference images for the illustration. STYLE_REFS=mix (default): 2 real illustrations of
    the set + 1 public-domain painting; 'set': 3 real illustrations; 'classic': the painting only."""
    mode = env("STYLE_REFS", "mix")
    if mode == "classic":
        return [classic_ref(card["type_line"])]
    refs = set_refs(card, pool, k - 1 if mode == "mix" else k)
    return refs + [classic_ref(card["type_line"])] if mode == "mix" else refs


def set_refs(card: dict, pool: list[dict], k: int) -> list[str]:
    """Real illustrations of the set closest to this card (colors, type), by different artists."""
    t, cols = type_bucket(card["type_line"]), set(card.get("colors") or [])
    ranked = sorted((c for c in pool if c.get("art_crop")), key=lambda c: (
        (type_bucket(c["type_line"]) != t) + len(set(c.get("colors") or []) ^ cols) + random.random()))
    refs, artists = [], set()
    for c in ranked:
        if c.get("artist") not in artists:
            refs.append(c["art_crop"]); artists.add(c.get("artist"))
        if len(refs) == k:
            break
    return refs

SYSTEM = """You are a senior Magic: The Gathering designer at Wizards of the Coast.
You write brand-new cards that are indistinguishable from cards printed in recent
Standard-legal expansions. Rules you always follow:
- Exact templating of the set, as printed on its cards: the examples show the text as
  printed at the time, so copy their wording exactly. Older cards say "enters the
  battlefield" and refer to themselves by their own name ("When Grim Scavenger enters the
  battlefield"); cards printed since 2024 say "enters" and "this creature". Cards from the
  1990s and 2000s use the wording of their time, as in the examples: "comes into play",
  "is put into a graveyard from play", "remove ... from the game", "played" for spells,
  and their power level and simplicity (many vanilla or one-line creatures). Include
  reminder text in parentheses when the examples do for the same keyword.
- Modal cards put each mode on its own line after a bullet: "Choose one —\\n• Destroy
  target artifact.\\n• Create a Treasure token." (never "Choose one — X; or Y").
- Ability words and named modes are followed by " — " ("Landfall — Whenever...",
  "• Smash the Chest — Destroy target artifact.").
- Power level and complexity follow rarity, like a real set: commons are simple (one or
  two short abilities, often a vanilla or French-vanilla creature), uncommons a bit richer,
  rares and mythics have distinctive, build-around designs. No broken or joke cards, no
  references to real-world brands or franchises.
- Use the keywords/ability words listed in each profile (they are the ones of a real card
  of this set), exactly as their keyword_rules show: same syntax (costs and numbers such as
  "Offspring {2}", "Mobilize 2", "Ward {1}"), same meaning as the reminder text. A keyword is
  never followed by " — " like an ability word. Use only existing mechanics, never invent keywords. Creature types must be
  ones this set actually uses.
- Names: original (never an existing card name), in the naming style of this set's cards —
  proper nouns, places, factions and turns of phrase of this world. Avoid generic AI
  patterns like colour+noun ("Azurewing Tempest") or adjective+class ("Cunning Illusionist").
- Keyword actions (explore, connive, venture, scry, surveil, investigate...) are verbs inside
  sentences ("Whenever this creature attacks, it connives"), never a standalone line like
  keyword abilities (Flying, Ward {2}). Write "Draw a card", never "You draw a card".
- Modal cards: every mode must be a real choice of similar value for the card's cost.
- Timing: a sorcery is cast only in its controller's main phase, never during combat, so it
  never refers to attacking, blocking or unblocked creatures; combat tricks are instants.
- Lands produce the mana listed in their profile (produces_mana) and use its land_types:
  like the set's real lands (tapped duals, utility lands), never a plain "{T}: Add {C}." land.
- If the set has color-based factions (guilds, colleges, clans, families...), a multicolor
  card belongs to the faction of its colors: its name, flavor and art show that faction.
- Flavor text: like the real flavor texts of the set — concrete and specific to this world
  (a named character, place, creature, custom or event), sometimes wry or funny; quotes are
  attributed to characters, factions or places of this setting ("—Tasha, the witch queen"),
  not generic titles ("—master of the arcane"). Never vague motivational maxims about fate,
  victory, knowledge or wisdom. Newlines inside flavor text are rare.
- art_description is an art brief like the ones Wizards gives its illustrators: a specific
  subject of this world, what it is doing, the setting details, the light and mood, following
  the profile's art_focus. The scene is unmistakably set in THIS set's world, with its own
  technology, architecture, costumes and landscapes (starships and alien planets for a
  space-opera set, Greek-myth temples and heroes for a Greek-myth set, ...): never a generic
  medieval forest unless the set really looks like that. The main subject is visibly the
  card's creature types (a Human is an ordinary human, a Human Soldier is not a bird-man).
  Show faces and creatures clearly. Avoid AI clichés: hooded or
  cloaked figures with hidden faces, figures seen from behind, silhouettes against light,
  glowing tunnels, portals, orbs and magic wisps, "glowing" everything, perfectly centered
  symmetric scenes, lightning everywhere, modern cities or neon, generic "oriental" or
  "medieval" décor instead of this world's own look and era. No signs or written words.
- Mana costs use braces: {2}{G}{G}. Oracle text uses \\n between abilities.
You answer with a JSON array only, no commentary."""


def type_bucket(type_line: str) -> str:
    """'Legendary Creature — Elf Druid' -> 'Legendary Creature' (subtypes left to the LLM)."""
    return type_line.split("—")[0].strip()


def spec_from(card: dict) -> dict:
    """Profile copied from a real card of the set, keywords included (same mechanics mix)."""
    colors = "".join(card.get("colors") or []) or "colorless"
    text = card.get("oracle_text") or ""
    # Scryfall also lists the names of modes as "keywords" ("• Repair — ..."): not mechanics
    keywords = [k for k in card.get("keywords") or []
                if not (re.search(rf"•\s*{re.escape(k)}\b", text) and not re.search(rf"(^|\n){re.escape(k)}\b", text))]
    # Oracle lists keywords the card's era did not print (an old "can attack the turn it comes
    # into play" is Haste today): only the ones printed at the time
    released = card.get("released_at") or ""
    keywords = [k for k in keywords if released >= KEYWORD_SINCE.get(k.lower(), "")
                and k.lower() in text.lower()]
    spec = {"colors": colors, "type": type_bucket(card["type_line"]), "rarity": card["rarity"],
            "mana_value": int(card.get("cmc") or 0), "flavor_text": bool(card.get("flavor_text")),
            "keywords": keywords, "art_focus": art_focus(card["type_line"])}
    if "Land" in card["type_line"] and "Creature" not in card["type_line"]:
        # lands are colorless: what matters is the mana they make (dual land, utility land...)
        spec["produces_mana"] = card.get("produced_mana") or []
        spec["land_types"] = card["type_line"].split("—")[1].strip() if "—" in card["type_line"] else ""
    return spec


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


def call_llm(provider: str, system: str, user: str, image: bytes | None = None,
             detail: str = "low", model: str | None = None, temperature: float = 1.0,
             timeout: float = 600) -> str:
    """One chat call; `image` (JPEG bytes) is sent along for vision checks (`detail`: 'high'
    to read small print). `model` overrides LLM_MODEL."""
    s = session()
    b64 = base64.b64encode(image).decode() if image else None
    if provider == "anthropic":
        key = env("ANTHROPIC_API_KEY") or sys.exit("ANTHROPIC_API_KEY missing")
        content = ([{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}]
                   if b64 else []) + [{"type": "text", "text": user}]
        r = s.post("https://api.anthropic.com/v1/messages", timeout=min(timeout, 300), headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model or env("LLM_MODEL", "claude-haiku-4-5"), "max_tokens": 6000,
                  "temperature": temperature, "system": system,
                  "messages": [{"role": "user", "content": content}]})
        check(r)
        return "".join(b.get("text", "") for b in r.json()["content"])
    key = env("LLM_API_KEY") or env("OPENAI_API_KEY")
    # An OpenAI key (sk-..., not OpenRouter's sk-or-...) goes to OpenAI itself by default.
    is_openai = key and key.startswith("sk-") and not key.startswith("sk-or-")
    base = env("LLM_BASE_URL", "https://api.openai.com/v1" if is_openai else "https://openrouter.ai/api/v1").rstrip("/")
    model = model or env("LLM_MODEL", "gpt-4.1-mini" if "api.openai.com" in base else "anthropic/claude-haiku-4.5")
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    content = user if not b64 else [
        {"type": "text", "text": user},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": detail}}]
    r = s.post(f"{base}/chat/completions", timeout=timeout, headers=headers, json={
        "model": model, "temperature": temperature,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]})
    check(r)
    return r.json()["choices"][0]["message"]["content"]


def parse_array(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError("no JSON array in answer")
    raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([\]}])", r"\1", raw))   # common LLM slip: trailing commas


def validate(c: dict, spec: dict) -> str | None:
    for k in ("name", "type_line", "oracle_text") + (() if "illustration" in spec else ("art_description",)):
        if not isinstance(c.get(k), str) or not c[k].strip():
            return f"missing {k}"
    if not MANA_RE.match(c.get("mana_cost") or ""):
        return "bad mana cost"
    tl = c["type_line"]
    if "Creature" in tl and not (c.get("power") and c.get("toughness")):
        return "creature without P/T"
    if "Planeswalker" in tl:
        return "planeswalker (not used in the quiz)"
    if len(c["oracle_text"]) > 480 or len(c.get("flavor_text") or "") > 200:
        return "too long"
    if re.search(r"\bCARDNAME\b|~", c["oracle_text"]):
        return "placeholder name in text"
    if re.search(r"[Cc]hoose (?:one|two|one or both|one or more) —(?!\n•)", c["oracle_text"]):
        return "modes not bulleted"
    missing = [k for k in spec.get("keywords", []) if k.lower() not in c["oracle_text"].lower()]
    if missing:
        return f"missing keyword(s) {missing}"
    if "produces_mana" in spec:
        text, types = c["oracle_text"], c["type_line"]
        basic = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
        lacking = [m for m in spec["produces_mana"] if m in basic
                   and f"{{{m}}}" not in text and basic[m] not in types and "any color" not in text]
        if lacking:
            return f"land does not produce {lacking} like its profile"
        if re.fullmatch(r"(?:[^\n]*enters[^\n]*tapped\.\n)?\{T\}: Add \{C\}\.", text.strip()):
            return "vanilla colorless land (never printed)"
    return None


def name_is_new(s, name: str) -> bool:
    r = s.get(f"{API}/cards/named", params={"exact": name}, timeout=30)
    time.sleep(0.12)
    return r.status_code == 404


# ------------------------------------------------------------------------ images
_REF_CACHE: dict[str, str] = {}


def ref_bytes(url: str) -> bytes:
    """Download a reference illustration ourselves (Scryfall refuses Replicate's fetcher),
    shrunk to a 768 px JPEG."""
    if url not in _REF_CACHE:
        img = Image.open(io.BytesIO(fetch_bytes(session(), url))).convert("RGB")
        img.thumbnail((768, 768))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        _REF_CACHE[url] = buf.getvalue()
    return _REF_CACHE[url]


def ref_data_uri(url: str) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(ref_bytes(url)).decode()


def gen_image(provider: str, prompt: str, seed: int, refs: list[str] | None = None) -> bytes | None:
    """One illustration. With a provider that takes reference images, `refs` are sent as style
    references; if that fails, the image is made once more without them."""
    if refs and refs_enabled():
        try:
            if provider == "openai":
                return _gen_image(provider, prompt, seed, [ref_bytes(u) for u in refs])
            return _gen_image(provider, prompt, seed, [ref_data_uri(u) for u in refs])
        except (Exception, SystemExit) as e:
            print(f"  references refused ({e}); retrying without them", file=sys.stderr)
            annotate("warning", f"style references refused, image made without them: {e}")
            prompt = re.sub(r"\nReferences: [^\n]*", "", prompt.replace(ref_note() + " ", ""))
    return _gen_image(provider, prompt, seed, None)


def _gen_image(provider: str, prompt: str, seed: int, refs: list[str] | None = None) -> bytes | None:
    s = session()
    if provider == "replicate":
        token = env("REPLICATE_API_TOKEN") or sys.exit("REPLICATE_API_TOKEN missing")
        h = {"authorization": f"Bearer {token}", "content-type": "application/json", "prefer": "wait"}
        model = env("REPLICATE_MODEL", "black-forest-labs/flux-schnell")
        inp = {"prompt": prompt, "aspect_ratio": "4:3"}
        if model.startswith("black-forest-labs/"):
            inp.update(seed=seed, output_format="jpg", output_quality=95)
        if model.endswith("flux-schnell"):
            inp.update(num_outputs=1, go_fast=True)
        if "nano-banana" in model:
            inp.update(output_format="jpg")
        if uses_lora(model):                     # e.g. flux-2-klein-4b-base-lora + "Light Fantasy"
            inp.update(lora_weights=[env("LORA_URL", LORA_DEFAULT)],
                       lora_scales=[float(env("LORA_SCALE", "0.8"))])
        if "/flux-2-klein" in model:             # render larger, then downscale: crisper detail
            inp.update(output_megapixels=env("IMAGE_MEGAPIXELS", "2"))
        if ref_field(model) and refs:            # real illustrations of the set as style references
            inp[ref_field(model)] = refs
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
    if provider == "fal":
        key = env("FAL_KEY") or sys.exit("FAL_KEY missing")
        model = env("FAL_MODEL", FAL_DEFAULT)
        w, h = (int(x) for x in env("FAL_IMAGE_SIZE", "1280x960").split("x"))
        body = {"prompt": prompt, "negative_prompt": NEGATIVE, "image_size": {"width": w, "height": h},
                "num_inference_steps": int(env("FAL_STEPS", "50")),        # LoRA author: 50 steps,
                "guidance_scale": float(env("FAL_GUIDANCE", "3.5")),       # guidance 3.5
                "acceleration": env("FAL_ACCELERATION", "none"),
                "seed": seed, "num_images": 1, "output_format": "jpeg"}
        if uses_lora(model):
            body["loras"] = [{"path": env("LORA_URL", LORA_DEFAULT), "scale": float(env("LORA_SCALE", "0.8"))}]
        r = s.post(f"https://fal.run/{model}", timeout=600, json=body,
                   headers={"authorization": f"Key {key}", "content-type": "application/json"})
        check(r, fatal=(401, 403, 404, 422))    # 422 = invalid input: fix the settings
        return fetch_bytes(s, r.json()["images"][0]["url"])
    if provider == "openai":
        key = env("OPENAI_API_KEY") or env("LLM_API_KEY") or sys.exit("OPENAI_API_KEY missing")
        params = {"model": env("IMAGE_MODEL", "gpt-image-2.5-sunburst"), "prompt": prompt,
                  "size": env("IMAGE_SIZE", "1536x1152"),            # 4:3 like the art box
                  "quality": env("IMAGE_QUALITY", "medium"),        # OpenAI's balanced default
                  "output_format": "jpeg", "moderation": "low", "n": 1}
        auth = {"authorization": f"Bearer {key}"}
        if refs:   # reference images go through the edits endpoint, as a multipart list image[]
            files = [("image[]", (f"ref{i + 1}.jpg", b, "image/jpeg")) for i, b in enumerate(refs)]
            r = s.post("https://api.openai.com/v1/images/edits", timeout=600, headers=auth,
                       data={k: str(v) for k, v in params.items()}, files=files)
        else:
            r = s.post("https://api.openai.com/v1/images/generations", timeout=600,
                       headers={**auth, "content-type": "application/json"}, json=params)
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
        s, cards = session(), []
        url, params = f"{API}/cards/search", {"q": f"e:{code} {BASE_QUERY}", "order": "set"}
        for _ in range(6):                       # the whole set (175 cards per page)
            r = s.get(url, params=params, timeout=60)
            time.sleep(0.12)
            if r.status_code != 200:
                break
            page = r.json()
            cards += [with_printed_text(s, {"id": c["id"], **{k: c.get(k) for k in FIELDS},
                                            "art_crop": c["image_uris"]["art_crop"]})
                      for c in page["data"] if keep(c)]
            if not page.get("has_more"):
                break
            url, params = page["next_page"], None
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
        "- factions: the set's color-based factions (guilds, colleges, clans, families...) with their "
        "colors, themes and visual identity; empty string if the set has none;\n"
        "- art_style: 2-3 sentences for an illustrator: setting, architecture, costumes, "
        "creatures, palette, lighting and painting style of the set's illustrations. Be specific "
        "to this plane's own visual culture rather than generic fantasy or cultural clichés. "
        "Describe the world only: never name the game, the set, the publisher or any product."
    )
    try:
        text = call_llm(llm, BRIEF_SYSTEM, user)
        brief = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    except Exception as e:                       # the brief is a bonus, never a blocker
        print(f"  no brief for {code}: {e}", file=sys.stderr)
        brief = {}
    brief = {k: str(brief.get(k) or "") for k in ("description", "mechanics", "factions", "art_style")}
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


def keyword_catalogs(s) -> tuple[set[str], set[str], set[str]]:
    """Scryfall's lists of keyword abilities, keyword actions and ability words (cached)."""
    path = WORK_SETS / "keywords.json"
    cats = load_json(path, None)
    if cats is None:
        cats = {}
        for name in ("keyword-abilities", "keyword-actions", "ability-words"):
            r = s.get(f"{API}/catalog/{name}", timeout=60)
            time.sleep(0.12)
            cats[name] = r.json().get("data", []) if r.ok else []
        save_json(path, cats)
    low = lambda k: {x.lower() for x in cats.get(k, [])}
    return low("keyword-abilities"), low("keyword-actions"), low("ability-words")


REVIEW_SYSTEM = """You are the lead developer of Magic: The Gathering's Play Design team.
You review new card designs before print, comparing each one with real cards of the same
set, rarity, card type and mana value. Fix only what is wrong:
- Power level: a card must be about as strong as its real comparables - neither clearly
  weaker nor clearly stronger for its mana value and rarity.
- Modal cards: every mode must be a real choice. If one mode is obviously better (e.g.
  "Draw three cards" vs "Target creature you control explores" at 4 mana), raise the weak
  mode (explores twice, then draw a card), lower the strong one (draw two cards), or change
  the mana cost, so that each mode is fair for the cost and useful in some situations.
- Rules validity: every ability must work under the Comprehensive Rules. Only creatures
  fight, attack, block or deal combat damage; an "Enchant X" card is an Aura (its type line
  says "Enchantment — Aura"); Equipment says "Equip"; targets must be legal; no ability may
  do nothing. Rewrite any ability that doesn't work.
- Rares and mythics must be distinctive build-around designs; commons stay simple.
- Keyword actions (explore, connive, venture, scry, surveil, mill, investigate...) are verbs
  in sentences ("Whenever this creature attacks, it connives"), never standalone lines.
- Keyword abilities keep their exact syntax and meaning: their cost or number ("Offspring {2}",
  "Mobilize 2", "Ward {2}") and never a " — " after them as if they were ability words.
  Stat changes "get" +N/+N (never "gain +N/+N").
- Keep each card's colors, rarity, card type, name, flavor text and art description unless
  they are the problem; keep the set's templating and wording exactly.
Answer with the full JSON array of cards, same order and same keys, no commentary."""


def color_distance(a: set[str], b: set[str]) -> float:
    """0 for the same colors, 1 for nothing in common (colorless counts as its own color)."""
    a, b = a or {"C"}, b or {"C"}
    return 1 - len(a & b) / len(a | b)


def comparables(card: dict, pool: list[dict], k: int = 3) -> list[dict]:
    """Real cards of the set closest to this design: same rarity, card type and colors, near mana value."""
    t, mv = type_bucket(card.get("type_line", "")), int(card.get("mana_value") or 0)
    cols = {x for x in (card.get("colors") or "") if x in "WUBRG"}
    scored = sorted(pool, key=lambda c: ((c["rarity"] != card.get("rarity")) * 2
                                         + (type_bucket(c["type_line"]) != t) * 2
                                         + 2 * color_distance(set(c.get("colors") or []), cols)
                                         + abs(int(c.get("cmc") or 0) - mv) + random.random()))
    return [example_text(c) for c in scored[:k]]


def dev_review(llm: str, batch: list[dict], specs: list[dict], pool: list[dict], set_name: str) -> list[dict]:
    """Second pass: balance and power level checked against real comparables of the set."""
    items = [{"card": c, "rarity": sp["rarity"], "real_comparables": comparables(
        {**c, "rarity": sp["rarity"], "mana_value": sp["mana_value"], "colors": sp["colors"]}, pool)}
        for c, sp in zip(batch, specs)]
    user = (f"Set: «{set_name}». Review these new cards; each comes with real cards of the set "
            "to compare with:\n" + json.dumps(items, ensure_ascii=False, indent=1))
    try:
        reviewed = parse_array(call_llm(llm, REVIEW_SYSTEM, user))
        if len(reviewed) == len(batch) and all(isinstance(c, dict) for c in reviewed):
            return [{**c, **r} for c, r in zip(batch, reviewed)]   # keys the review omits are kept
    except (Exception, SystemExit) as e:          # the review is a bonus, never a blocker
        print(f"  review skipped: {e}", file=sys.stderr)
    return batch


CREATIVE_SYSTEM = """You are a senior writer on Magic: The Gathering's Creative team.
You polish the names and flavor text of new cards so they read exactly like the real
cards of their set. Good flavor text is concrete and specific to the world: a named
character, place, creature, custom, rumor or event; often a quote with an in-world
attribution on its own line ("\\n—Tasha, the witch queen"); sometimes dry humor or irony;
short (usually under 25 words). Bad flavor text is a vague maxim about fate, victory,
knowledge, wisdom, balance, legends or "the heart of" something - rewrite those.
Names must sound like this set's real names: specific to the world, not generic
adjective+class or colour+noun patterns; keep a name if it is already good.
Never add flavor text to a card that has none, never change rules text.
Answer with a JSON array of {"name": ..., "flavor_text": ...} in the same order, no commentary."""


def creative_review(llm: str, batch: list[dict], flavors: list[str], brief: dict, set_name: str) -> list[dict]:
    """Third pass: names and flavor text rewritten in the voice of the set's real cards."""
    cards = [{"name": c.get("name"), "type_line": c.get("type_line"), "oracle_text": c.get("oracle_text"),
              "flavor_text": c.get("flavor_text")} for c in batch]
    user = (f"Set: «{set_name}». {brief.get('description', '')} {brief.get('factions', '')}\n"
            "Real flavor texts of this set:\n" + json.dumps(flavors, ensure_ascii=False, indent=1)
            + "\n\nNew cards to polish:\n" + json.dumps(cards, ensure_ascii=False, indent=1))
    try:
        out = parse_array(call_llm(llm, CREATIVE_SYSTEM, user))
        if len(out) == len(batch):
            for c, o in zip(batch, out):
                if isinstance(o, dict) and o.get("name"):
                    c["name"] = str(o["name"]).strip()
                    if c.get("flavor_text"):            # never add flavor to a card without it
                        c["flavor_text"] = o.get("flavor_text") or c["flavor_text"]
    except (Exception, SystemExit) as e:          # a bonus, never a blocker
        print(f"  creative pass skipped: {e}", file=sys.stderr)
    return batch


ART_CHECK_SYSTEM = """You are the art director of Magic: The Gathering, checking a freelance
illustration before print. Gender, age, skin tone and body type of characters are free
choices: never report them. List only real, visible problems among: a setting, costumes or
technology that do not belong to the set's world as described (e.g. medieval knights in a
forest for a space-opera world, a generic forest with no Greek-myth element for a Greek-myth
world); text, letters, signs,
logos, watermark or signature in the image; a hooded or cloaked figure with a hidden face;
a main figure seen from behind; neon colors or glowing haze dominating the image; anime,
cartoon, 3D-render or photo look instead of a painting; an over-polished "AI" finish (airbrushed, plastic
skin, no visible brushwork); a blurry, out-of-focus, foggy or
muddy image, or one so dark or low-contrast that the subject is hard to read (these are serious
problems: a printed illustration must be crisp); malformed anatomy (hands, limbs,
faces); modern objects (cars, skyscrapers, screens) that don't belong to the described world;
a border or frame; a main subject that is not what the description says (e.g. a Human
with an animal head or a bird face, a Dwarf drawn as a giant, the wrong creature). Answer with JSON only: {"problems": ["...", ...]} (empty list if fine)."""


def art_check(llm: str, jpeg: bytes, brief: str, world: str = "") -> list[str]:
    """Vision check of a generated illustration; [] when fine or when the check is unavailable."""
    try:
        text = call_llm(llm, ART_CHECK_SYSTEM, f"The set's world: {world}\n"
                                               f"The illustration should show: {brief}", image=jpeg)
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        return [str(p) for p in data.get("problems", []) if p][:4]
    except (Exception, SystemExit) as e:
        print(f"  art check skipped: {e}", file=sys.stderr)
        return []


def real_art() -> bool:
    """ART_SOURCE=real (default): AI cards reuse the illustration of the real card whose profile
    they copy (credited to its real artist); 'generate': illustrations made by an image model."""
    return env("ART_SOURCE", "real") == "real"


def obscurity(card: dict) -> float:
    """Weight favoring little-played cards, whose art players are unlikely to recognize."""
    rank = card.get("edhrec_rank")
    return 1.0 if not rank or rank > 8000 else 0.3 if rank > 3000 else 0.05


DESCRIBE_SYSTEM = """You describe fantasy illustrations for a card designer. In 2-3 plain
sentences: the main subject (what kind of creature, person or object, and what it looks like),
what it is doing, the setting, the mood. Describe only what is visible; no game terms."""
_ART_DESCRIPTIONS: dict[str, str] = {}


def describe_art(llm: str, url: str) -> str:
    """What a real illustration shows (vision), so the AI card's text can match its art."""
    if url not in _ART_DESCRIPTIONS:
        try:
            _ART_DESCRIPTIONS[url] = call_llm(llm, DESCRIBE_SYSTEM, "Describe this illustration.",
                                              image=ref_bytes(url)).strip()
        except (Exception, SystemExit) as e:
            print(f"  could not describe {url}: {e}", file=sys.stderr)
            _ART_DESCRIPTIONS[url] = ""
    return _ART_DESCRIPTIONS[url]


def keyword_rules(keywords: list[str], pool: list[dict], by_keyword: dict) -> dict:
    """{keyword: {"reminder": the set's reminder text, "real_example": a real line using it}},
    so the LLM knows e.g. that Offspring takes a cost and what it does."""
    rules = {}
    for kw in keywords:
        line = next((ln for c in pool for ln in (c.get("oracle_text") or "").split("\n")
                     if re.search(rf"\b{re.escape(kw)}\w*", ln, re.I)), None)
        entry = {k: v for k, v in (("reminder", by_keyword.get(kw.lower())), ("real_example", line)) if v}
        if entry:
            rules[kw] = entry
    return rules


def subtypes(pool: list[dict]) -> list[str]:
    """Creature/other subtypes this set actually prints, most common first."""
    return [t for t, _ in Counter(w for c in pool if "—" in c["type_line"]
                                  for w in c["type_line"].split("—")[1].split()).most_common(40)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--llm", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--images", choices=["replicate", "fal", "openai", "pollinations", "placeholder", "none"],
                    default="replicate")
    ap.add_argument("--no-name-check", action="store_true")
    ap.add_argument("--rarity-weights", default=None,
                    help="e.g. 'common=55,uncommon=40,rare=4,mythic=1' (same as fetch_real.py)")
    args = ap.parse_args()
    weights = parse_weights(args.rarity_weights or env("RARITY_WEIGHTS"))
    os.environ["IMAGE_PROVIDER"] = args.images          # read by art_prompt / gen_image

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
    used_artists = {c["artist"] for c in fakes if c.get("artist")}
    used_name_words = {w for c in fakes for w in name_words(c["name"])}
    used_art = {c["art_source_id"] for c in fakes if c.get("art_source_id")}   # one card per real art
    kw_catalogs = keyword_catalogs(s)
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
        by_clause, by_keyword, remind_rates = reminder_texts(pool)   # the set's real reminder texts
        old_wording = uses_old_wording(pool)               # "enters the battlefield" or "enters"
        n = min(BATCH, args.count - len(fakes), max(deficits.get(code, 1), 1))
        # profiles drawn with the quiz rarity weights (not the set's natural ~30% rares/mythics)
        per_rarity = Counter(c["rarity"] for c in pool)
        w = [weights.get(c["rarity"], 0) / per_rarity[c["rarity"]] for c in pool]
        if real_art():                           # the source card lends its art: prefer obscure ones
            w = [x * obscurity(c) if c["id"] not in used_art else 0 for x, c in zip(w, pool)]
        sources = random.choices(pool, k=n, weights=w if sum(w) > 0 else None)
        specs = [spec_from(c) for c in sources]
        for sp, src in zip(specs, sources):      # how each keyword works, from the set's own cards
            if sp["keywords"]:
                sp["keyword_rules"] = keyword_rules(sp["keywords"], pool, by_keyword)
            if real_art():                       # the card is designed around its (real) art
                sp["illustration"] = describe_art(args.llm, src["art_crop"])
                sp.pop("art_focus", None)
        # examples: a real card close to each profile (same rarity/type/cost) + random ones -
        # never the source cards themselves (their art is reused, their text must not be)
        others = [p for p in pool if p["id"] not in {s_["id"] for s_ in sources}]
        near = [comparables({"type_line": c["type_line"], "rarity": c["rarity"], "mana_value": c.get("cmc"),
                             "colors": "".join(c.get("colors") or [])}, others, 1)[0] for c in sources]
        shots = list({s_["name"]: s_ for s_ in near + [example_text(c) for c in
                      random.sample(others, min(8, len(others)))]}.values())[:16]
        flavors = [c["flavor_text"] for c in random.sample(pool, len(pool)) if c.get("flavor_text")][:10]
        about = "".join(f"{k.replace('_', ' ').capitalize()}: {v}\n" for k, v in brief.items() if v)
        wording = {True: 'This set says "enters the battlefield" and cards refer to themselves by name.',
                   False: 'This set says "enters" (not "enters the battlefield") and "this creature".',
                   None: ""}[old_wording]
        user = (
            f"All cards below come from the real set «{set_names[code]}» ({meta['released_at'][:4]}). "
            "Your new cards will be printed in that same set: reuse its mechanics, keywords, "
            "creature types, factions and world.\n" + about + wording + "\n"
            f"Subtypes printed in this set: {', '.join(subtypes(pool))}.\n"
            "Examples from the set (match their names, templating, tone and power level):\n"
            + json.dumps(shots, ensure_ascii=False, indent=1)
            + "\n\nReal flavor texts of this set (match their concreteness and voice):\n"
            + json.dumps(flavors, ensure_ascii=False, indent=1)
            + (f"\n\nDesign {n} NEW cards, one per profile below, in this order. Each card must use "
               "the keywords listed in its profile. Its illustration is already chosen and described "
               "in the profile ('illustration'): the card's name, creature types, abilities and flavor "
               "text must fit what the illustration shows. Creature types name what is visibly drawn "
               "(an ordinary person is a Human; use a race like Aetherborn, Vampire or Merfolk only if "
               "the illustration shows one), and the set must print that type in the card's colors.\n"
               if real_art() else
               f"\n\nDesign {n} NEW cards, one per profile below, in this order. Each card must use "
               "the keywords listed in its profile, and its art must follow the profile's art_focus:\n")
            + json.dumps(specs, ensure_ascii=False, indent=1)
            + "\n\nReturn a JSON array of objects with keys: name, mana_cost, type_line, oracle_text, "
              "flavor_text (null if the profile says false), power, toughness, loyalty (strings or null), "
              "rarity" + ("." if real_art() else
              ", art_description (2-3 sentences: an art brief naming the subject, its action, "
              "the setting details of this world, light and mood; no text in the image).")
        )
        try:
            batch = parse_array(call_llm(args.llm, SYSTEM, user))
        except Exception as e:
            fails += 1; print("LLM error:", e, file=sys.stderr); annotate("warning", f"LLM error: {e}")
            time.sleep(3); continue
        batch = [c for c in batch if isinstance(c, dict)][:len(specs)]
        batch = dev_review(args.llm, batch, specs[:len(batch)], pool, set_names[code])   # balance pass
        batch = creative_review(args.llm, batch, flavors, brief, set_names[code])        # names, flavor
        for c, spec, src in zip(batch, specs, sources):
            err = validate(c, spec)
            if not err:
                c["oracle_text"] = fix_templating(c["oracle_text"], meta["released_at"])
                c["type_line"] = printed_type_line(fix_type_line(c["type_line"], c["oracle_text"]), meta["released_at"])
                bad_kw = misused_keywords(c["oracle_text"], *kw_catalogs)
                err = (f"keyword action used as an ability {bad_kw}" if bad_kw
                       else f"too simple for a {spec['rarity']}" if (meta["released_at"] >= "2003-07-28"   # (old rares were often simple)
                                                                     and too_simple(c["oracle_text"], spec["rarity"], c["type_line"], spec["colors"]))
                       else rules_problem(c["oracle_text"], c["type_line"])
                       or anachronism(c["oracle_text"], meta["released_at"])
                       or subtype_color_problem(c["type_line"], spec["colors"], pool)
                       or name_problem(c["name"], used_name_words)
                       or (None if real_art() else art_problem(c["art_description"])))
            if not err and c["name"].lower() in banned:
                err = "name already used"
            if not err and not args.no_name_check and not name_is_new(s, c["name"]):
                err = "existing card name"
            if err:
                print(f"  rejected {c.get('name')!r}: {err}")
                annotate("notice", f"rejected {c.get('name')!r}: {err}"); continue
            banned.add(c["name"].lower())
            used_name_words |= name_words(c["name"])
            # Text: the set's real reminder texts (added where the set prints them at this
            # rarity) and era wording, whatever the LLM wrote. Art brief without "glowing" haze.
            text = fix_reminders(c["oracle_text"], by_clause, by_keyword)
            text = add_missing_reminders(text, spec["rarity"], by_keyword, remind_rates, by_clause)
            text = join_follow_ups(fix_wording(text, c["name"], c["type_line"], old_wording))
            c["oracle_text"] = fix_cost_order(old_frame_text(text, c["name"], c["type_line"], meta["released_at"]))
            if "Land" in c["type_line"]:
                c["mana_cost"] = None            # lands have no mana cost (not even {0})
            if not flavor_fits(c["oracle_text"], c.get("flavor_text")):
                c["flavor_text"] = None          # like printed cards: no room left for flavor
            # Credits: with real art, its real artist (and the card it comes from, told on reveal);
            # otherwise an ordinary invented name (never a real Magic artist, no repeats).
            # Collector number in the range where this set prints this colour.
            if real_art():
                artist, art = src.get("artist") or "", {
                    "art_url": src["art_crop"], "art_source_id": src["id"], "art_from": src["name"],
                    "art_description": spec.get("illustration", "")}
                used_art.add(src["id"])
            else:
                c["art_description"] = tone_down(c["art_description"])
                artist, art = artist_name(artists, used_artists), {}
            colors = list(spec["colors"]) if spec["colors"] != "colorless" else []
            number = number_in_group(pool, color_group(colors, c["type_line"]), numbers[code],
                                     meta.get("printed_size"))
            numbers[code].add(number)
            fakes.append({"id": uuid.uuid4().hex, "real": False,
                          **{k: (c.get(k) or None) for k in
                             ("name", "mana_cost", "type_line", "oracle_text", "flavor_text",
                              "power", "toughness", "loyalty", "art_description")},
                          "rarity": spec["rarity"], "colors": list(spec["colors"]) if spec["colors"] != "colorless" else [],
                          "set": code, "set_name": set_names[code], "artist": artist,
                          "collector_number": number, "released_at": meta["released_at"],
                          # printed like the real card it copies: same frame and border colour
                          "frame": src.get("frame"), "border_color": src.get("border_color"),
                          "set_description": brief.get("description", ""),
                          "art_style": brief.get("art_style", ""),
                          "style_refs": [] if real_art() else
                          style_refs({"type_line": c["type_line"], "colors": colors}, pool),
                          **art, "image": None})
            print(f"[{len(fakes)}/{args.count}] {c['name']}")
        save_json(out_path, fakes)

    # --- images
    if args.images != "none":
        model = {"replicate": env("REPLICATE_MODEL", "black-forest-labs/flux-schnell"),
                 "fal": f"{env('FAL_MODEL', FAL_DEFAULT)} ({env('FAL_STEPS', '50')} steps, guidance {env('FAL_GUIDANCE', '3.5')})",
                 "openai": f"{env('IMAGE_MODEL', 'gpt-image-2.5-sunburst')} "
                           f"({env('IMAGE_QUALITY', 'medium')}, {env('IMAGE_SIZE', '1536x1152')})"}.get(args.images, args.images)
        lora = (f"; LoRA {env('LORA_URL', LORA_DEFAULT).split('/')[4]} x{env('LORA_SCALE', '0.8')}"
                if lora_active() else "")
        if real_art():
            annotate("notice", "illustrations: real art of the source cards (ART_SOURCE=real), "
                               "credited to their artists")
        else:
            annotate("notice", f"image model: {model}{lora}; reference images ({env('STYLE_REFS', 'mix')}): "
                               f"{'yes' if refs_enabled() else 'no'}")
        for i, c in enumerate(fakes):
            img = WORK_IMG / f"fake_{c['id']}.jpg"
            if img.exists():
                c["image"] = img.name; continue
            if c.get("art_url"):                  # real illustration of the source card
                try:
                    normalize_image(fetch_bytes(session(), c["art_url"]), img)
                    c["image"] = img.name
                    save_json(out_path, fakes)
                    print(f"  art {i + 1}/{len(fakes)}: {c['name']} <- {c.get('art_from')} ({c.get('artist')})")
                except Exception as e:
                    print(f"  art download failed for {c['name']}: {e}", file=sys.stderr)
                    annotate("warning", f"art download failed: {e}")
                continue
            prompt, best = art_prompt(c), None      # best = (problem count, raw, prompt)
            world = " ".join(filter(None, [c.get("set_description"), c.get("art_style")]))
            # Up to ART_TRIES images, each checked by the vision model (wrong world or creature,
            # text in the image, hooded figures, glow, anime look, bad anatomy...) and redone with
            # the problems named; the image with the fewest problems is kept.
            tries = max(1, int(env("ART_TRIES", "3")))
            for attempt in range(tries):
                try:
                    raw = gen_image(args.images, prompt, seed=random.randint(1, 2**31 - 1),
                                    refs=c.get("style_refs"))
                except Exception as e:
                    print(f"  image failed for {c['name']}: {e}", file=sys.stderr)
                    annotate("warning", f"image failed: {e}"); break
                if tries == 1 or args.images == "placeholder":
                    best = (0, raw, prompt); break
                normalize_image(raw, img)
                problems = art_check(args.llm, img.read_bytes(),
                                     subject(c["type_line"]) + c["art_description"], world)
                if best is None or len(problems) < best[0]:
                    best = (len(problems), raw, prompt)
                if not problems:
                    break
                print(f"  art redo for {c['name']}: {problems}")
                annotate("notice", f"art redo for {c['name']!r}: {problems}")
                prompt = f"{art_prompt(c)} Must avoid: {'; '.join(problems)}."
            if best is None:
                continue
            _, raw, prompt = best
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
