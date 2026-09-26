"""Step 3 - Render every card (real and AI alike) as a full card image with Magic Set Editor.

All cards go through the same MSE template (M15 frame of the Full Magic Pack),
so the frame can never tell real and AI cards apart. The set symbol is drawn
from the Keyrune font in the rarity colours and handed to MSE as a
"mainframe rarity" image.

Needs Magic Set Editor + the Full Magic Pack data (the GitHub workflow
downloads them): MSE_DIR = folder holding magicseteditor.com and data/.

Usage:
    python pipeline/render_mse.py              # every card of pipeline/work/{real,fake}.json
    python pipeline/render_mse.py --sample     # the cards of docs/ + 2 samples, to test the setup

Output: pipeline/work/cards/<id>.png (cards whose set has no symbol are skipped)
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

from common import DOCS, ROOT, WORK, WORK_IMG, WORK_SETS, env, fetch_bytes, load_json, session

WORK_CARDS = WORK / "cards"
KEYRUNE = WORK / "keyrune"
KEYRUNE_CDN = "https://cdn.jsdelivr.net/npm/keyrune@3"
STYLE = "m15-altered"                        # "M15 Main" in MSE
STYLE_PW = "m15-mainframe-planeswalker"
PW_ART = (324, 428)                          # planeswalker art box (px at 150 dpi)
RARITY = {"mythic": "mythic rare"}
SYMBOL_DIR = "quiz"                          # folder inside magic-mainframe-extras.mse-include

# Rarity colours of printed set symbols: gradient (dark, light, dark) + outline.
RARITY_LOOK = {
    "c": (("#1b1a1a", "#1b1a1a", "#1b1a1a"), "#d9d9d9"),
    "u": (("#5f6a74", "#d8e0e6", "#5f6a74"), "#000000"),
    "r": (("#8a6d2b", "#ecd594", "#8a6d2b"), "#000000"),
    "m": (("#b3260f", "#f7941d", "#b3260f"), "#000000"),
}


# ------------------------------------------------------------ text conversion
# Same conversions as the Scryfall importer of magic.mse-game.
def _mana_common(t: str) -> str:
    t = re.sub(r"\{(.)/(.)/P\}", r"{H/\1/\2}", t)
    return re.sub(r"\{(.)/P\}", r"{H/\1}", t)


def mana_cost(cost: str | None) -> str:
    """'{2}{W/U}{G}' -> '2W/UG' (the casting cost field takes bare symbols)."""
    return "".join(re.findall(r"\{([^}]+)\}", _mana_common(cost or "")))


def esc(t: str) -> str:
    return t.replace("<", "").replace(">", "")


# "Landfall — Whenever..." : ability/flavor words are printed in italics. Keywords that also
# use a dash (Boast, Exhaust...) and modal "Choose one —" stay roman.
# Also named modes: "• Smash the Chest — Destroy target artifact."
ABILITY_WORD = re.compile(r"^(• ?)?([A-Z][A-Za-z'’ -]{1,40}?) — ", re.M)
ROMAN_BEFORE_DASH = ("Choose", "Boast", "Companion", "Exhaust", "Forecast", "Max speed", "Solved")


def _italic_ability_word(m: re.Match) -> str:
    bullet, word = m.group(1) or "", m.group(2)
    return m.group(0) if word.startswith(ROMAN_BEFORE_DASH) else f"{bullet}<i>{word}</i> — "


def minus_signs(t: str) -> str:
    """Printed cards use a real minus sign in stat changes: '−2/−0', '−1/−1 counter'."""
    t = re.sub(r"(?<![\w/])-(?=[\dX]+/[+\-−]?[\dX])", "−", t)
    return re.sub(r"(?<=[\dX]/)-(?=[\dX])", "−", t)


def rules_text(text: str | None) -> str:
    t = ABILITY_WORD.sub(_italic_ability_word, minus_signs(esc(text or "")))
    t = re.sub(r"\{([A-Z0-9/]+)\}", r"<sym>\1</sym>", _mana_common(t))
    return t.replace("</sym><sym>", "")


def split_type(type_line: str) -> tuple[str, str]:
    sup, _, sub = type_line.partition("—")
    return sup.strip(), sub.strip()


def planeswalker_fields(text: str) -> dict:
    """'+1: Draw a card.\\n−3: ...' -> one 'level N text' per ability + its loyalty cost
    (the planeswalker style lays each ability out after its '[+1]:' badge)."""
    fields = {}
    for i, line in enumerate((text or "").split("\n"), 1):
        m = re.match(r"^([+−\-]?(?:\d+|X)):\s*(.*)$", line)
        if m:
            fields[f"loyalty cost {i}"] = m.group(1).replace("-", "−")
            line = m.group(2)
        fields[f"level {i} text"] = rules_text(line)
    return fields


# ------------------------------------------------------------------ set file
def value(key: str, v: str, indent: int = 1) -> str:
    tab = "\t" * indent
    if "\n" not in v:
        return f"{tab}{key}: {v}\n"
    return f"{tab}{key}:\n" + "".join(f"{tab}\t{line}\n" for line in v.split("\n"))


def card_block(c: dict, image_name: str, meta: dict) -> str:
    sup, sub = split_type(c["type_line"])
    pw = "Planeswalker" in sup
    fields = {
        "notes": c["id"],                    # used as the export file name
        "name": esc(c["name"]),
        "illustrator": esc(c.get("artist") or ""),
        "custom card number": card_number(c, meta),
        "casting cost": mana_cost(c.get("mana_cost")),
        "image": image_name,
        "super type": esc(sup),
        "sub type": esc(sub),
        "rarity": RARITY.get(c["rarity"], c["rarity"]),
        "power": c.get("power") or "",
        "toughness": c.get("toughness") or "",
        "loyalty": c.get("loyalty") or "",
    }
    fields.update(planeswalker_fields(c.get("oracle_text")) if pw
                  else {"rule text": rules_text(c.get("oracle_text"))})
    if c.get("flavor_text"):
        fields["flavor text"] = f"<i-flavor>{esc(c['flavor_text'])}</i-flavor>"
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if pw:
        out = f"card:\n\thas styling: false\n\tstylesheet: {STYLE_PW}\n"
    else:   # text size chosen per card, like Wizards does (see text_size)
        out = (f"card:\n\thas styling: true\n\tstyling data:\n"
               f"\t\tfont cap: {text_size(c.get('oracle_text'), c.get('flavor_text'))}\n")
    out += f"\ttime created: {now}\n\ttime modified: {now}\n"
    return out + "".join(value(k, v) for k, v in fields.items())


NEW_NUMBERING = "2023-04-01"                 # from March of the Machine: "C 0100" instead of "100/281 C"
NYX_SETS = {"ths", "bng", "jou", "thb"}      # the starry enchantment frame is a Theros thing only


def card_number(c: dict, meta: dict) -> str:
    n = str(c.get("collector_number") or "")
    if not n.isdigit():                      # e.g. "123a", "★": print as is
        return n
    if meta["released_at"] >= NEW_NUMBERING:
        return n.zfill(4)
    size = meta.get("printed_size") or meta.get("card_count")
    return f"{n.zfill(3)}/{str(size).zfill(3)}" if size else n.zfill(3)


def set_header(code: str, meta: dict) -> str:
    return f"""mse version: 2.0.2
game: magic
stylesheet: {STYLE}
set info:
\ttitle: quiz
\tset code: {code.upper()}
\tset language: EN
\tcopyright: ™ & © {meta['released_at'][:4]} Wizards of the Coast
\tautomatic copyright: yes
\tautomatic card numbers: no
\tcard number style: {"0001" if meta["released_at"] >= NEW_NUMBERING else "001/099"}
\trarity codes: yes
\tauto nyx: {"yes" if code in NYX_SETS else "no"}
\tmainframe rarity name: {SYMBOL_DIR}/{code}.png
\tautomatic reminder text:
\tmark errors: no
\tauto correct: no
\tauto errata: no
\tcurly quotes: yes
\tmana cost sorting: unsorted
"""


def set_meta(code: str, cards: list[dict]) -> dict:
    """Release date and size of the set (saved by fetch_real.py), else guessed from the cards."""
    meta = load_json(WORK_SETS / f"{code}.meta.json", None) or {}
    dates = sorted(c["released_at"] for c in cards if c.get("released_at"))
    return {**meta, "released_at": meta.get("released_at") or (dates[0] if dates else "2020-01-01")}


PW_VISIBLE = 0.645                           # share of the planeswalker art box above the text box


def planeswalker_art(img: Image.Image) -> Image.Image:
    """The art crops are landscape; the planeswalker art box is tall and mostly hidden by
    the translucent text box. Like on printed cards, the art fills the visible top part and
    runs on (here blurred) under the text box - instead of a zoomed-in vertical strip."""
    w, h = PW_ART[0] * 2, PW_ART[1] * 2
    canvas = ImageOps.fit(img, (w, h), method=Image.LANCZOS).resize((24, 32), Image.BILINEAR) \
        .resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))
    vh = int(h * PW_VISIBLE)
    vw = int(vh * img.width / img.height)
    if vw < w:                                # narrow image: fit the width instead
        vw, vh = w, int(w * img.height / img.width)
    canvas.paste(img.resize((vw, vh), Image.LANCZOS), ((w - vw) // 2, 0))
    return canvas


def art_bytes(path: Path, planeswalker: bool) -> bytes:
    img = Image.open(path).convert("RGB")
    if planeswalker:
        img = planeswalker_art(img)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def write_set(code: str, cards: list[tuple[dict, Path]], dest: Path) -> None:
    meta = set_meta(code, [c for c, _ in cards])
    text = set_header(code, meta)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (c, art) in enumerate(cards, 1):
            z.writestr(f"image{i}", art_bytes(art, "Planeswalker" in c["type_line"]))
            text += card_block(c, f"image{i}", meta)
        z.writestr("set", text)


# --------------------------------------------------------------- set symbols
def keyrune() -> tuple[Path, dict[str, str]]:
    """Keyrune font + {set code: glyph}, downloaded once."""
    KEYRUNE.mkdir(parents=True, exist_ok=True)
    font, css = KEYRUNE / "keyrune.ttf", KEYRUNE / "keyrune.css"
    s = session()
    if not font.exists():
        font.write_bytes(fetch_bytes(s, f"{KEYRUNE_CDN}/fonts/keyrune.ttf"))
    if not css.exists():
        css.write_bytes(fetch_bytes(s, f"{KEYRUNE_CDN}/css/keyrune.css"))
    glyphs = {m[0]: chr(int(m[1], 16)) for m in re.findall(
        r"\.ss-([a-z0-9]+):before\s*\{\s*content:\s*\"\\([0-9a-f]+)\"", css.read_text(encoding="utf-8"))}
    return font, glyphs


def gradient(size: tuple[int, int], colors: tuple[str, str, str]) -> Image.Image:
    """Horizontal dark-light-dark gradient, like the metallic printed symbols."""
    stops = [ImageColor.getrgb(c) for c in colors]
    band = Image.new("RGB", (256, 1))
    for x in range(256):
        t = x / 255 * 2
        a, b, f = (stops[0], stops[1], t) if t <= 1 else (stops[1], stops[2], t - 1)
        band.putpixel((x, 0), tuple(round(a[i] + (b[i] - a[i]) * f) for i in range(3)))
    return band.resize(size, Image.BILINEAR)


def symbol_images(code: str, font_path: Path, glyph: str, dest: Path) -> None:
    """Write <code>c/u/r/m.png: the set glyph filled with the rarity colours."""
    size, stroke = 900, 40
    font = ImageFont.truetype(str(font_path), size)
    box = font.getbbox(glyph, stroke_width=stroke)
    w, h = box[2] - box[0] + 2 * stroke, box[3] - box[1] + 2 * stroke
    at = (stroke - box[0], stroke - box[1])
    fill_mask, outline_mask = Image.new("L", (w, h)), Image.new("L", (w, h))
    ImageDraw.Draw(fill_mask).text(at, glyph, font=font, fill=255)
    ImageDraw.Draw(outline_mask).text(at, glyph, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    for r, (colors, outline) in RARITY_LOOK.items():
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.paste(Image.new("RGB", (w, h), outline), mask=outline_mask)
        img.paste(gradient((w, h), colors), mask=fill_mask)
        img.save(dest / f"{code}{r}.png")


# ------------------------------------------------------------- style tweaks
# Rules text of the stock M15 style is a bit loosely spaced and grows up to size 14,
# so long texts spill onto the P/T box. Measured against printed cards (same scale):
# body text ~12.7, wrapped lines ~9% tighter, paragraphs ~8% tighter.
BODY_SIZE = env("MSE_BODY_SIZE", "14")
LINE_HEIGHTS = dict(zip(("hard", "line", "soft"), env("MSE_LINE_HEIGHTS", "1.1,1.0,0.84").split(",")))


def text_size(rules: str | None, flavor: str | None) -> str:
    """Printed cards set smaller type as the text gets longer (before the box is full):
    ~14.7 for 'T: Add G' + flavor, ~14.5 for a 3-line spell, ~12.7 for a 7-line modal card.
    MSE still shrinks further if the text doesn't fit."""
    length = len(rules or "") + len(flavor or "") / 2          # flavor text weighs half
    return f"{max(11.0, min(14.7, 16.5 - 0.017 * length)):.1f}"


def tune_style(base: Path) -> None:
    """Patch the installed M15 Main style once (idempotent: only matches stock values)."""
    path = base / "data" / f"magic-{STYLE}.mse-style" / "style"
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    text, n1 = re.subn(
        r'(swap_fonts_body2?_default := \[\r?\n\t\tname: \{"MPlantin"\},\r?\n\t\tsize: \{[^\r\n]*?else )14\}',
        rf"\g<1>{BODY_SIZE}}}", text)
    # "max" line heights let MSE spread short texts over the whole box (big gap before the
    # flavor text); printed cards keep a compact block, centered: max = normal height.
    lh = LINE_HEIGHTS
    text, n2 = re.subn(
        r"(?m)(^\ttext:\s*\r?\n(?:\t\t.*\r?\n)*?)\t\tline height hard: 1\.2(\r?\n)"
        r"\t\tline height line: 1\.5(\r?\n)\t\tline height soft: 0\.9(\r?\n)"
        r"\t\tline height hard max: 1\.3(\r?\n)\t\tline height line max: 1\.6",
        rf"\g<1>\t\tline height hard: {lh['hard']}\g<2>\t\tline height line: {lh['line']}\g<3>"
        rf"\t\tline height soft: {lh['soft']}\g<4>\t\tline height hard max: {lh['hard']}\g<5>"
        rf"\t\tline height line max: {lh['line']}", text, count=1)
    if n1 or n2:
        path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        print(f"M15 style tuned (font size: {n1} patch(es), line heights: {n2})")


# -------------------------------------------------------------------- render
def mse_dir() -> tuple[Path, Path]:
    base = Path(env("MSE_DIR", str(ROOT / "mse")))
    for name in ("magicseteditor.com", "mse.com"):
        if (base / name).exists():
            return base, base / name
    sys.exit(f"Magic Set Editor not found in {base} (set MSE_DIR)")


def render(cards: list[tuple[dict, Path]], out_dir: Path) -> None:
    base, exe = mse_dir()
    tune_style(base)
    out_dir.mkdir(parents=True, exist_ok=True)
    sym_dir = base / "data" / "magic-mainframe-extras.mse-include" / SYMBOL_DIR
    sym_dir.mkdir(parents=True, exist_ok=True)
    font, glyphs = keyrune()

    by_set: dict[str, list] = defaultdict(list)
    for c, art in cards:
        code = (c.get("set") or "").lower()
        if code in glyphs:
            by_set[code].append((c, art))
        else:
            print(f"  skipped {c['name']!r}: no Keyrune symbol for set {code!r}")

    failed = []
    for code, group in sorted(by_set.items()):
        todo = [(c, a) for c, a in group if not (out_dir / f"{c['id']}.png").exists()]
        if not todo:
            continue
        symbol_images(code, font, glyphs[code], sym_dir)
        set_path = WORK / f"quiz-{code}.mse-set"
        write_set(code, todo, set_path)
        cmd = [str(exe), "--export-images", str(set_path), str(out_dir / "{card.notes}.png")]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=1800)
        log = "\n".join(line for line in (r.stdout + r.stderr).splitlines()
                        if line.strip() and "Unexpected key" not in line)
        if log:
            print(log[-2000:])
        missing = [c["name"] for c, _ in todo if not (out_dir / f"{c['id']}.png").exists()]
        failed += missing
        print(f"[{code}] {len(todo) - len(missing)}/{len(todo)} cards rendered")
    done = len(list(out_dir.glob("*.png")))
    print(f"Done: {done} card images in {out_dir}")
    if failed:
        sys.exit(f"MSE failed to render {len(failed)} cards: {failed[:10]}")


SAMPLES = [
    {"id": "sample-pw", "set": "dom", "released_at": "2018-04-27", "collector_number": "56",
     "artist": "Anouk Velder", "name": "Kasra, Tidecaller", "mana_cost": "{2}{U}{U}",
     "type_line": "Legendary Planeswalker — Kasra", "rarity": "mythic", "loyalty": "4",
     "oracle_text": "+1: Draw a card, then discard a card.\n−2: Tap target creature. It doesn't untap "
                    "during its controller's next untap step.\n−7: You get an emblem with \"Spells you "
                    "cast cost {1} less to cast.\""},
    {"id": "sample-tap", "set": "blb", "released_at": "2024-08-02", "collector_number": "187",
     "artist": "Mireille Castan", "name": "Warden of the Grove", "mana_cost": "{1}{G/W}{G/W}",
     "type_line": "Creature — Rabbit Druid", "rarity": "uncommon", "power": "2", "toughness": "3",
     "oracle_text": "Vigilance\n{T}: Add {G} or {W}.\nValiant — Whenever this creature becomes the target "
                    "of a spell or ability you control for the first time each turn, put a +1/+1 counter on it.",
     "flavor_text": "\"Roots remember what the wind forgets.\"\n—Maelis, grove warden"},
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="render docs/ cards + samples, no API needed")
    args = ap.parse_args()

    if args.sample:
        imgs = sorted((DOCS / "img").glob("*.jpg"))
        docs = load_json(DOCS / "data" / "cards.json", {"cards": []})["cards"]
        cards = [({**c, "id": Path(c["img"]).stem, "set": c.get("set_icon") or "dom"}, DOCS / "img" / c["img"])
                 for c in docs if c["img"].endswith(".jpg")]
        cards += [(s, imgs[i % len(imgs)]) for i, s in enumerate(SAMPLES)]
    else:
        pool = load_json(WORK / "real.json", []) + load_json(WORK / "fake.json", [])
        cards = [(c, WORK_IMG / c["image"]) for c in pool if c.get("image")]
    render(cards, WORK_CARDS)


if __name__ == "__main__":
    main()
