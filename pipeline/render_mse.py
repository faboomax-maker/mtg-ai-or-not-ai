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
import time
import zipfile
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

from common import DOCS, ROOT, WORK, WORK_IMG, WORK_SETS, env, fetch_bytes, load_json, save_json, session

WORK_CARDS = WORK / "cards"
KEYRUNE = WORK / "keyrune"
KEYRUNE_CDN = "https://cdn.jsdelivr.net/npm/keyrune@3"
STYLE = "m15-altered"                        # "M15 Main" in MSE
STYLE_PW = "m15-mainframe-planeswalker"
PW_ART = (324, 428)                          # planeswalker art box (px at 150 dpi)
RARITY = {"mythic": "mythic rare"}
SYMBOL_DIR = "quiz"                          # folder inside magic-mainframe-extras.mse-include

# Rarity colours of printed set symbols, as Keyrune defines them (keyrune.andrewgioia.com,
# .ss-{rarity}.ss-grad): gradient (dark, light, dark) + outline (white for commons).
RARITY_LOOK = {
    "c": (("#1a1718", "#1a1718", "#1a1718"), "#ffffff"),
    "u": (("#7b8894", "#e4eaef", "#7b8894"), "#000000"),   # lighter than Keyrune's: as printed
    "r": (("#876a3b", "#dfbd6b", "#876a3b"), "#000000"),
    "m": (("#b21f0f", "#f38300", "#b21f0f"), "#000000"),
}
RARITY_LETTER = {"common": "c", "uncommon": "u", "rare": "r", "mythic": "m"}
SYMBOL_STROKE = 34                           # outline width at glyph size 900 (~2%, thin like print)
# Size and place of the set symbol, measured on Scryfall scans (fractions of the card):
# ~22 px high on a 375x523 card, at most ~54 px wide, right edge at 92.2%, centered at 59.25%.
SYMBOL_H = 20.5 / 523
SYMBOL_MAX_W = 54 / 375
SYMBOL_RIGHT = 0.922
SYMBOL_CY = 308 / 523                       # centre of the M15 type bar in MSE (rarity box 297 + 22/2)

# Old frame (1993-2003): white outlines (MSE's "Old Main" style); before Exodus (June 1998)
# every rarity was printed black.
OLD_LOOK = {
    "c": (("#1a1718", "#1a1718", "#1a1718"), "#ffffff"),
    "u": (("#545454", "#e0e0e0", "#545454"), "#ffffff"),
    "r": (("#5f5428", "#d6c45e", "#5f5428"), "#ffffff"),
}
OLD_LOOK["m"] = OLD_LOOK["r"]
RARITY_COLORS_SINCE = "1998-06-15"          # Exodus
NO_SYMBOL = {"lea", "leb", "2ed", "3ed", "4ed", "5ed"}   # Alpha -> Fifth Edition: no set symbol

# The three frame eras (see fetch_real.ERAS): MSE style, and where the set symbol goes
# (the style's rarity box, fractions of the card), same symbol height rule as M15 for now.
FRAMES = {
    "current": {"style": STYLE, "right": SYMBOL_RIGHT, "cy": SYMBOL_CY, "h": SYMBOL_H},
    "modern": {"style": "new", "right": 342 / 375, "cy": (297 + 11) / 523, "h": SYMBOL_H},
    "old": {"style": "old", "right": 337 / 375, "cy": (290 + 11) / 523, "h": SYMBOL_H},
}


def era(c: dict) -> str:
    return {"1993": "old", "1997": "old", "2003": "modern"}.get(c.get("frame") or "", "current")


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


def rules_text(text: str | None, marked: bool = False) -> str:
    """`marked`: the text carries its printed italics as <i>...</i> (read on the scan of a real
    card), used as is; otherwise ability words are put in italics by rule."""
    if marked:
        t = esc((text or "").replace("<i>", "\x01").replace("</i>", "\x02"))
        t = minus_signs(t).replace("\x01", "<i>").replace("\x02", "</i>")
    else:
        t = ABILITY_WORD.sub(_italic_ability_word, minus_signs(esc(text or "")))
    t = re.sub(r"\{([A-Z0-9/]+)\}", r"<sym>\1</sym>", _mana_common(t))
    return t.replace("</sym><sym>", "")


def split_type(type_line: str) -> tuple[str, str]:
    sup, _, sub = type_line.partition("—")
    return sup.strip(), sub.strip()


def planeswalker_fields(text: str, marked: bool = False) -> dict:
    """'+1: Draw a card.\\n−3: ...' -> one 'level N text' per ability + its loyalty cost
    (the planeswalker style lays each ability out after its '[+1]:' badge)."""
    fields = {}
    for i, line in enumerate((text or "").split("\n"), 1):
        m = re.match(r"^([+−\-]?(?:\d+|X)):\s*(.*)$", line)
        if m:
            fields[f"loyalty cost {i}"] = m.group(1).replace("-", "−")
            line = m.group(2)
        fields[f"level {i} text"] = rules_text(line, marked)
    return fields


# ------------------------------------------------------------------ set file
def value(key: str, v: str, indent: int = 1) -> str:
    tab = "\t" * indent
    if "\n" not in v:
        return f"{tab}{key}: {v}\n"
    return f"{tab}{key}:\n" + "".join(f"{tab}\t{line}\n" for line in v.split("\n"))


def card_block(c: dict, image_name: str, meta: dict, rarity_grow: int = 0, size: str = "", tag: str = "") -> str:
    sup, sub = split_type(c["type_line"])
    pw = "Planeswalker" in sup
    fields = {
        "notes": c["id"] + tag,              # used as the export file name
        "name": esc(c["name"]),
        # old frame: "Illus. Carl Critchlow" (the modern and M15 frames draw a brush instead)
        "illustrator": ("Illus. " if era(c) == "old" and c.get("artist") else "") + esc(c.get("artist") or ""),
        # the thin line between rules and flavor text is printed since Dominaria (April 2018)
        "separator": "flavor bar" if meta["released_at"] >= FLAVOR_BAR_SINCE else "none",
        "custom card number": TRACK.join(card_number(c, meta)),
        "casting cost": mana_cost(c.get("mana_cost")),
        "image": image_name,
        "super type": esc(sup),
        "sub type": esc(sub),
        "rarity": RARITY.get(c["rarity"], c["rarity"]),
        "power": c.get("power") or "",
        "toughness": c.get("toughness") or "",
        "loyalty": c.get("loyalty") or "",
    }
    # real cards: the text with its italics as read on the scan, when available
    marked = bool(c.get("printed_markup"))
    text = c["printed_markup"] if marked else c.get("oracle_text")
    fields.update(planeswalker_fields(text, marked) if pw else {"rule text": rules_text(text, marked)})
    if c.get("flavor_text"):
        # the attribution line ("—Arlinn Kord") follows without a paragraph gap: soft line break
        flavor = esc(c["flavor_text"]).replace("\n", "<soft-line>\n</soft-line>")
        fields["flavor text"] = f"<i-flavor>{flavor}</i-flavor>"
    if c.get("border_color") == "white":               # Revised, 4th-7th Edition...
        fields["border color"] = "rgb(255,255,255)"
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    frame = era(c)
    if pw:
        out = f"card:\n\thas styling: false\n\tstylesheet: {STYLE_PW}\n"
    elif frame == "old":
        # P/T in MPlantin before Mirage (October 1996), MPlantin-Bold after
        pt_font = "MPlantin" if meta["released_at"] < "1996-10-08" else "MPlantin-Bold"
        out = (f"card:\n\tstylesheet: old\n\thas styling: true\n\tstyling data:\n"
               f"\t\tpt font: {pt_font}\n\t\tcolored rarities: no\n")
    elif frame == "modern":
        out = "card:\n\tstylesheet: new\n\thas styling: false\n"
    else:   # text size chosen per card, like Wizards does (see text_size)
        out = (f"card:\n\thas styling: true\n\tstyling data:\n"
               f"\t\tfont cap: {size or BODY_SIZE}\n"
               f"\t\trarity offsets: 0,0,{rarity_grow}\n")   # type line stops before the symbol
    out += f"\ttime created: {now}\n\ttime modified: {now}\n"
    return out + "".join(value(k, v) for k, v in fields.items())


NEW_NUMBERING = "2023-04-01"                 # from March of the Machine: "C 0100" instead of "100/281 C"
FLAVOR_BAR_SINCE = "2018-04-27"              # Dominaria; none on Ixalan, Rivals, Amonkhet...
NYX_SETS = {"ths", "bng", "jou", "thb"}     # the starry enchantment frame is a Theros thing only


def card_number(c: dict, meta: dict) -> str:
    n = str(c.get("collector_number") or "")
    if meta["released_at"] < RARITY_COLORS_SINCE:
        return ""                            # no collector numbers before Exodus
    if not n.isdigit():                      # e.g. "123a", "★": print as is
        return n
    if era(c) != "current":                  # old and modern frames: "85/306", not zero-padded
        size = meta.get("printed_size") or meta.get("card_count")
        return f"{n}/{size}" if size else n
    if meta["released_at"] >= NEW_NUMBERING:
        return n.zfill(4)
    size = meta.get("printed_size") or meta.get("card_count")
    return f"{n.zfill(3)}/{str(size).zfill(3)}" if size else n.zfill(3)


def copyright_line(released: str) -> str:
    """The copyright as printed in the set's era."""
    y = released[:4]
    if released < "1998-01-01":
        return f"© {y} Wizards of the Coast, Inc."
    if released < "2009-01-01":
        return f"™ & © 1993-{y} Wizards of the Coast, Inc."
    if released < "2013-07-19":                      # Magic 2014: the year alone
        return f"™ & © 1993-{y} Wizards of the Coast LLC"
    return f"™ & © {y} Wizards of the Coast"


def set_header(code: str, meta: dict) -> str:
    return f"""mse version: 2.0.2
game: magic
stylesheet: {STYLE}
set info:
\ttitle: quiz
	set code: {TRACK.join(code.upper())}
	set language: {TRACK.join('EN')}
\tcopyright: {copyright_line(meta['released_at'])}
\tautomatic copyright: yes
\tautomatic card numbers: no
\tcard number style: {"0001" if meta["released_at"] >= NEW_NUMBERING else "001/099"}
\trarity codes: yes
\tshorten types for rarity: yes
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


def write_set(code: str, cards: list[tuple[dict, Path]], dest: Path, rarity_grow: int = 0) -> None:
    """One MSE set; every non-planeswalker card appears once per candidate text size
    (notes '<id>__<k>'), the best render being picked afterwards (pick_size)."""
    meta = set_meta(code, [c for c, _ in cards])
    text = set_header(code, meta)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (c, art) in enumerate(cards, 1):
            z.writestr(f"image{i}", art_bytes(art, "Planeswalker" in c["type_line"]))
            if "Planeswalker" in c["type_line"] or era(c) != "current":   # (older frames: MSE's own fit)
                text += card_block(c, f"image{i}", meta, rarity_grow)
            else:
                for k, size in enumerate(SIZE_STEPS):
                    text += card_block(c, f"image{i}", meta, rarity_grow, f"{size:g}", f"__{k}")
        z.writestr("set", text)


# Candidate text sizes, largest first: MSE shrinks overflowing text in coarse steps and ends
# far below the size that fits, so each card is rendered at these sizes and the largest one
# whose text stays in the box (and above the P/T box) is kept.
# Calibrated on scans (calibrate.py): the largest printed size gives the line pitch of 13.9.
SIZE_STEPS = [13.9, 13.5, 13.1, 12.7, 12.3, 11.9, 11.5, 11.1, 10.7, 10.3]


def _text_rows(img: Image.Image, x0: float, x1: float, y0: float, y1: float) -> list[int]:
    """Rows (pixels) of the card that contain dark text pixels in a region."""
    W, H = img.size
    g = img.convert("L").crop((round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H)))
    g = g.point(lambda v: 255 if v < 90 else 0)
    return [round(y0 * H) + y for y in range(g.height) if g.crop((0, y, g.width, y + 1)).getbbox()]


def pick_size(out_dir: Path, card: dict) -> bool:
    """Keep the largest candidate size whose text stays clear of the box bottom and of
    the P/T box; rename it <id>.png and delete the other candidates."""
    cands = [out_dir / f"{card['id']}__{k}.png" for k in range(len(SIZE_STEPS))]
    cands = [p for p in cands if p.exists()]
    if not cands:
        return False
    pt = card.get("power") not in (None, "") or card.get("toughness") not in (None, "")
    best = cands[-1]
    for p in cands:
        img = Image.open(p)
        W, H = img.size
        # below the text: 4% band above the box's bottom border; for creatures the band
        # above the P/T box, over its columns
        # printed text (descenders included) runs down to ~.915 (calibrate.py)
        low = _text_rows(img, .09, .70 if pt else .90, .917, .921)        # border at .9235
        # a line may run over the P/T box's columns down to just above its outline (.891; the
        # descenders of such a line end ~.885, as on scans: calibrate.py); ink in the last few
        # rows above the outline means a line running into the box
        pt_low = _text_rows(img, .74, .88, .886, .8905) if pt else []
        img.close()
        if env("DEBUG_SIZES"):
            print(f"  {card['name']} {p.stem}: low rows {low[:3]} pt rows {pt_low[:3]} (H={H})")
        if not low and not pt_low:
            best = p
            break
    for p in cands:
        if p == best:
            p.replace(out_dir / f"{card['id']}.png")
        elif env("DEBUG_SIZES"):                  # kept for inspection
            (out_dir / "rejected").mkdir(exist_ok=True)
            p.replace(out_dir / "rejected" / p.name)
        else:
            p.unlink(missing_ok=True)
    return True


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


def official_symbol_mask(code: str, height: int = 900) -> Image.Image | None:
    """The set's official symbol shape: Scryfall's SVG (saved by fetch_real.py) rasterized.
    Keyrune redraws some symbols differently (Midnight Hunt: a disc with the wolf cut out,
    instead of the printed wolf inside a thin circle)."""
    svg = WORK_SETS / f"{code}.svg"
    if not svg.exists():
        try:                                      # sets seen only through AI cards
            info = session().get(f"https://api.scryfall.com/sets/{code}", timeout=30).json()
            svg.write_bytes(fetch_bytes(session(), info["icon_svg_uri"]))
        except Exception:
            return None
    try:
        import resvg_py
        text = svg.read_text(encoding="utf-8")
        png = resvg_py.svg_to_bytes(svg_string=text, height=height)
        img = Image.open(io.BytesIO(bytes(png))).convert("RGBA")
        mask = img.getchannel("A")
        return mask.crop(mask.getbbox()) if mask.getbbox() else None
    except Exception as e:
        print(f"  [{code}] official symbol unavailable ({e}); using Keyrune", file=sys.stderr)
        return None


def hole_count(solid: Image.Image, shape: Image.Image) -> int:
    """Number of enclosed holes in a symbol (areas of `solid` not covered by `shape`)."""
    holes = ImageChops.subtract(solid, shape).point(lambda v: 255 if v > 128 else 0)
    holes = holes.resize((max(1, holes.width // 8), max(1, holes.height // 8)), Image.NEAREST)
    count = 0
    while (bb := holes.getbbox()):
        seed = next((x, y) for y in range(bb[1], bb[3]) for x in range(bb[0], bb[2])
                    if holes.getpixel((x, y)) == 255)
        ImageDraw.floodfill(holes, seed, 0)
        count += 1
    return count


def outline_around_parts(shape: Image.Image, stroke: int, cut: float = 1.0) -> Image.Image:
    """The shape grown by `stroke` px, part by part, as printed: a thin cut between two parts
    (narrower than `cut` strokes) is filled with the outline colour, but a wider gap (the
    segments of the March of the Machine ring) keeps its light middle, each side outlined."""
    parts, work = [], shape.copy()
    while (bb := work.getbbox()):                   # connected parts of the symbol
        seed = next((x, y) for y in range(bb[1], bb[3]) for x in range(bb[0], bb[2])
                    if work.getpixel((x, y)) == 255)
        ImageDraw.floodfill(work, seed, 128)
        parts.append(work.point(lambda v: 255 if v == 128 else 0))
        ImageDraw.floodfill(work, seed, 0)
    reach = 2 * stroke + 1
    d1 = Image.new("L", shape.size, 255)             # distance to the nearest part
    d2 = Image.new("L", shape.size, 255)             # ... and to the second nearest one
    for part in parts:
        dist, cur = Image.new("L", shape.size, 255), part
        dist.paste(0, mask=part)
        for i in range(1, reach + 1):                # (chessboard) distance, up to `reach`
            grown = cur.filter(ImageFilter.MaxFilter(3))
            dist.paste(i, mask=ImageChops.subtract(grown, cur))
            cur = grown
        d2 = ImageChops.darker(d2, ImageChops.lighter(d1, dist))
        d1 = ImageChops.darker(d1, dist)
    out = Image.new("L", shape.size)
    out.putdata([255 if a <= stroke and (b == 255 or a + b <= cut * stroke or a <= 0.35 * (a + b)) else 0
                 for a, b in zip(d1.getdata(), d2.getdata())])
    return out


def symbol_images(code: str, font_path: Path, glyph: str | None, dest: Path) -> dict[str, Image.Image]:
    """Write <code>c/u/r/m.png: the set symbol filled with the rarity colours."""
    size, stroke = 900, SYMBOL_STROKE
    official = official_symbol_mask(code)
    if official is not None:
        pad = stroke + 2
        fill_mask = ImageOps.expand(official, pad, 0)
        # outline: the shape grown by `stroke` px (on a reduced copy, for speed); a second
        # version keeps the gaps between the symbol's parts open (see gaps_open)
        k = 4
        small = fill_mask.resize((fill_mask.width // k, fill_mask.height // k), Image.BILINEAR)
        big = lambda m: m.resize(fill_mask.size, Image.BILINEAR).point(lambda v: 255 if v > 100 else 0)
        outline_mask = big(small.filter(ImageFilter.MaxFilter(2 * (stroke // k) + 1)))
        open_outline = big(outline_around_parts(small.point(lambda v: 255 if v > 127 else 0), stroke // k))
    else:
        font = ImageFont.truetype(str(font_path), size)
        box = font.getbbox(glyph, stroke_width=stroke)
        w, h = box[2] - box[0] + 2 * stroke, box[3] - box[1] + 2 * stroke
        at = (stroke - box[0], stroke - box[1])
        fill_mask, outline_mask = Image.new("L", (w, h)), Image.new("L", (w, h))
        ImageDraw.Draw(fill_mask).text(at, glyph, font=font, fill=255)
        ImageDraw.Draw(outline_mask).text(at, glyph, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    ink = outline_mask.getbbox()                # empty space around the symbol:
    fill_mask, outline_mask = fill_mask.crop(ink), outline_mask.crop(ink)   # keep visible pixels only
    if official is not None:
        open_outline = open_outline.crop(ink)
    w, h = outline_mask.size
    # MSE draws its rarity symbol too small (~12 px high instead of ~19): it gets transparent
    # images, and the real-size symbol is pasted onto the rendered card (paste_symbol).
    symbols = {}
    # Keyrune draws inner details as holes; printed symbols fill them with the outline colour
    # (white letters on a black common M21, black ones on a gold rare): paint the whole
    # silhouette, gaps included, in the outline colour, then the symbol on top.
    # In the official SVGs, lettering is holes too (the "M21" of Core Set 2021, filled on print)
    # but a lone hole is part of the design (the centre of the RNA symbol shows the type bar):
    # fill the holes only when there are several.
    solid = ImageOps.expand(outline_mask, 2, 0)
    ImageDraw.floodfill(solid, (0, 0), 128)                  # flood the outside from a margin
    solid = solid.point(lambda v: 0 if v == 128 else 255).crop((2, 2, w + 2, h + 2))
    if official is not None and hole_count(solid, outline_mask) < 3:
        solid = outline_mask
    # Some sets print the gaps and holes of their symbol open (March of the Machine's ring,
    # the knuckle-duster holes of Streets of New Capenna), others as black lines and filled
    # lettering (Wilds of Eldraine, Core Set 2021): the scans decide.
    if official is not None and gaps_open(code, fill_mask, outline_mask, solid, open_outline):
        outline_mask = solid = open_outline
    inverted = common_inverted(code, fill_mask, outline_mask, solid)
    for r, (colors, outline) in RARITY_LOOK.items():
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if r == "c" and inverted:             # inverted common: white shape, black lines
            img.paste(Image.new("RGB", (w, h), "#000000"), mask=solid)
            img.paste(Image.new("RGB", (w, h), "#ffffff"), mask=fill_mask)
        else:
            img.paste(Image.new("RGB", (w, h), outline), mask=solid)
            img.paste(gradient((w, h), colors), mask=fill_mask)
        symbols[r] = img
        # transparent stand-in with the symbol's proportions: MSE reserves that width on the type line
        Image.new("RGBA", (round(100 * w / h), 100), (255, 255, 255, 1)).save(dest / f"{code}{r}.png")
    for r, (colors, outline) in OLD_LOOK.items():   # old frame colours: "old-c", "old-u"...
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.paste(Image.new("RGB", (w, h), outline), mask=solid)
        img.paste(gradient((w, h), colors), mask=fill_mask)
        symbols[f"old-{r}"] = img
    return symbols


def symbol_grow(symbol: Image.Image) -> int:
    """How much to widen MSE's (transparent) rarity box, 44 px wide on a 375 px card, so the
    type line stops before the pasted symbol, as on printed cards."""
    w = min(SYMBOL_H * 523 * symbol.width / symbol.height, SYMBOL_MAX_W * 375)
    return max(0, round(w - 44 + 3))


def gaps_open(code: str, fill: Image.Image, outline: Image.Image, solid: Image.Image,
              open_outline: Image.Image) -> bool:
    """Are the gaps and holes of the symbol open on print (March of the Machine's ring, the
    knuckle-duster holes of Streets of New Capenna) or black lines / filled lettering (Wilds of
    Eldraine, Core Set 2021)? Where the two versions differ, the scans of a few uncommons (silver
    shape, black outline) are either light like the type bar or dark like the outline (cached)."""
    path = WORK_SETS / f"{code}.gaps.json"
    cached = load_json(path, None)
    if cached is not None:
        return cached["open"]
    is_open = False
    try:
        s = session()
        r = s.get("https://api.scryfall.com/cards/search", timeout=60,
                  params={"q": f"e:{code} r:uncommon frame:2015 -t:basic -t:planeswalker", "order": "set"})
        gap, ring, bar = [], [], []
        for card in [c for c in r.json()["data"] if "image_uris" in c][:3]:
            img = Image.open(io.BytesIO(fetch_bytes(s, card["image_uris"]["large"]))).convert("L")
            W, H = img.size
            h = SYMBOL_H * H
            w = min(h * fill.width / fill.height, SYMBOL_MAX_W * W)
            x0, y0 = round(SYMBOL_RIGHT * W - w), round(SYMBOL_CY * H - h / 2)
            size = (round(SYMBOL_RIGHT * W) - x0, round(SYMBOL_CY * H + h / 2) - y0)
            m = lambda k: k.resize(size, Image.LANCZOS).point(lambda v: 255 if v > 200 else 0)
            areas = [m(a) for a in (ImageChops.subtract(solid, open_outline),   # open in one version only
                                    ImageChops.subtract(outline, fill),          # the black outline
                                    ImageOps.invert(solid.filter(ImageFilter.MaxFilter(9))))]  # type bar

            def mean(box: Image.Image, mask: Image.Image) -> float | None:
                vals = [p for p, v in zip(box.getdata(), mask.getdata()) if v]
                return sum(vals) / len(vals) if len(vals) >= 4 else None

            # the printed symbol may sit a pixel or two away: align our outline on its dark outline
            boxes = [img.crop((x0 + dx, y0 + dy, x0 + dx + size[0], y0 + dy + size[1]))
                     for dx in range(-4, 5) for dy in range(-4, 5)]
            box = min(boxes, key=lambda b: mean(b, areas[1]) or 255)
            for acc, area in zip((gap, ring, bar), areas):
                if (v := mean(box, area)) is not None:
                    acc.append(v)
        if gap and ring and bar:
            g, o, b = (sum(x) / len(x) for x in (gap, ring, bar))
            is_open = g > o + 0.55 * (b - o)          # clearly closer to the bar than to the outline
            print(f"  [{code}] symbol gaps {'open' if is_open else 'as lines'} "
                  f"(gaps {g:.0f}, outline {o:.0f}, type bar {b:.0f})")
    except Exception as e:
        print(f"  [{code}] symbol gaps check failed ({e})", file=sys.stderr)
    save_json(path, {"open": is_open})
    return is_open


def common_inverted(code: str, fill: Image.Image, outline: Image.Image, solid: Image.Image) -> bool:
    """Some sets print their common symbol inverted (white shape, black lines: Dominaria 2018,
    Rivals of Ixalan...). Both versions are drawn over the symbol of a few real commons of the
    set (Scryfall scans), and the one closer to the scans wins (cached)."""
    path = WORK_SETS / f"{code}.symbol3.json"
    cached = load_json(path, None)
    if cached is not None:
        return cached["inverted"]
    inverted = False
    try:
        s = session()
        r = s.get("https://api.scryfall.com/cards/search", timeout=60,
                  params={"q": f"e:{code} r:common frame:2015 -t:basic", "order": "set"})
        err_black = err_inv = 0.0
        for card in [c for c in r.json()["data"] if "image_uris" in c][:3]:
            img = Image.open(io.BytesIO(fetch_bytes(s, card["image_uris"]["normal"]))).convert("L")
            W, H = img.size
            h = SYMBOL_H * H
            w = min(h * fill.width / fill.height, SYMBOL_MAX_W * W)
            box = img.crop((round(SYMBOL_RIGHT * W - w), round(SYMBOL_CY * H - h / 2),
                            round(SYMBOL_RIGHT * W), round(SYMBOL_CY * H + h / 2)))
            m = lambda k: k.resize(box.size, Image.LANCZOS)
            black = box.copy(); black.paste(255, mask=m(outline)); black.paste(26, mask=m(fill))
            inv = box.copy(); inv.paste(0, mask=m(solid)); inv.paste(255, mask=m(fill))
            diff = lambda a: sum(abs(p - q) for p, q in zip(a.getdata(), box.getdata()))
            err_black += diff(black); err_inv += diff(inv)
        inverted = err_inv < err_black
        print(f"  [{code}] common symbol {'inverted' if inverted else 'black'} "
              f"(error black {err_black:.0f} / inverted {err_inv:.0f})")
    except Exception as e:
        print(f"  [{code}] common symbol check failed ({e}); using black", file=sys.stderr)
    save_json(path, {"inverted": inverted})
    return inverted
# Collector info (bottom left), measured on Scryfall scans (fractions of the card): line 1
# "085/196 U" digits from y .9365 to .9500, line 2 "RIX • EN" letters from .9548 to .9673,
# left edge .0644; Gotham Medium, widely letter-spaced ("085/196 U" is .137 of the width);
# the artist's brush .017 after "EN", .025 wide, then the name in Beleren Small Caps.
INFO_X, INFO_L1, INFO_L2, INFO_CAP = 0.0644, 0.9365, 0.9548, 0.0125
INFO_REF = ("085/196 U", 0.1369)


def _font_file(base: Path, name: str) -> Path | None:
    return next((p for p in (base / "Magic - Fonts").rglob(name)), None)


def _brush(base: Path, width: int) -> Image.Image | None:
    """The M15 artist brush, from the pack (magic-modules information/art.png), as a mask."""
    path = base / "data" / "magic-modules.mse-include" / "information" / "art.png"
    try:
        img = Image.open(path).convert("RGBA")
        a = img.getchannel("A")
        if a.getextrema()[0] == 255:            # opaque image: use darkness instead
            a = ImageOps.invert(img.convert("L"))
        a = a.crop(a.getbbox())
        return a.resize((width, max(1, round(a.height * width / a.width))), Image.LANCZOS)
    except Exception as e:
        print(f"  brush icon unavailable ({e})", file=sys.stderr)
        return None


def draw_info(card_png: Path, base: Path, line1: str, line2: str, artist: str) -> None:
    """Redraw the collector info like print: MSE cannot letter-space it."""
    gotham, beleren = _font_file(base, "Gotham Medium Regular.ttf"), _font_file(base, "belerensmallcaps-bold.ttf")
    if not gotham or not beleren:
        return
    card = Image.open(card_png).convert("RGBA")
    W, H = card.size
    d = ImageDraw.Draw(card)
    border = card.getpixel((round(0.03 * W), round(0.95 * H)))
    d.rectangle((round(0.045 * W), round(0.930 * H), round(0.42 * W), round(0.975 * H)), fill=border)
    ink = (255, 255, 255, 255) if sum(border[:3]) < 384 else (0, 0, 0, 255)
    cap = INFO_CAP * H
    probe = ImageFont.truetype(str(gotham), 100)
    e_box = probe.getbbox("E")
    size = 100 * cap / (e_box[3] - e_box[1])
    font = ImageFont.truetype(str(gotham), round(size * 4) / 4)
    natural = sum(font.getlength(ch) for ch in INFO_REF[0])
    track = (INFO_REF[1] * W - natural) / (len(INFO_REF[0]) - 1)

    def spaced(text: str, x: float, baseline: float) -> float:
        for ch in text:
            d.text((x, baseline), ch, font=font, fill=ink, anchor="ls")
            x += font.getlength(ch) + track
        return x - track

    spaced(line1, INFO_X * W, INFO_L1 * H + cap * 1.08)          # digits are a bit taller than E
    end = spaced(line2, INFO_X * W, INFO_L2 * H + cap)
    x = end + 0.017 * W
    brush = _brush(base, round(0.025 * W))
    if brush is not None and artist:
        top = INFO_L2 * H + (cap - brush.height) / 2
        card.paste(Image.new("RGBA", brush.size, ink), (round(x), round(top)), brush)
        x += brush.width + 0.006 * W
    if artist:
        af = ImageFont.truetype(str(beleren), round(size * 1.12 * 4) / 4)
        d.text((x, INFO_L2 * H + cap), artist, font=af, fill=ink, anchor="ls")
    card.save(card_png)


def paste_symbol(card_png: Path, symbol: Image.Image, box: dict | None = None) -> None:
    """Set symbol at the size and place measured on a real card of the set (else defaults)."""
    card = Image.open(card_png).convert("RGBA")
    cw, ch = card.size
    box = box or {}
    h = box.get("h", SYMBOL_H) * ch
    w = symbol.width * h / symbol.height
    if w > SYMBOL_MAX_W * cw:                  # very wide symbols (M21...) are width-limited
        w, h = SYMBOL_MAX_W * cw, symbol.height * SYMBOL_MAX_W * cw / symbol.width
    s = symbol.resize((max(1, round(w)), max(1, round(h))), Image.LANCZOS)
    at = (round(box.get("right", SYMBOL_RIGHT) * cw - s.width), round(box.get("cy", SYMBOL_CY) * ch - s.height / 2))
    card.alpha_composite(s, at)
    card.save(card_png)
    if env("DEBUG_SYMBOLS"):
        print(f"  symbol {symbol.size} -> {s.size} at {at} on {card.size} ({card_png.name})")


# ------------------------------------------------------------- style tweaks
# Rules text of the stock M15 style is a bit loosely spaced and grows up to size 14,
# so long texts spill onto the P/T box. Measured against printed cards (same scale):
# body text ~12.7, wrapped lines ~9% tighter, paragraphs ~8% tighter.
BODY_SIZE = env("MSE_BODY_SIZE", "13.9")       # standard print size; MSE shrinks long texts to fit
PT_CHOP = env("MSE_PT_CHOP", "0")                 # rules text stops this far above the P/T box
INFO_SIZE = env("MSE_INFO_SIZE", "5.6")         # bottom line (collector number, set code)
TRACK = ""                                     # (hair spaces are not drawn by MSE: no tracking)
OLD_TEXT_SIZE = env("MSE_OLD_TEXT_SIZE", "12.2")        # old frame (1993-2003), MSE: 14
MODERN_TEXT_SIZE = env("MSE_MODERN_TEXT_SIZE", "13.2")  # modern frame (2003-2014), MSE: 14
PW_TEXT_SIZE = env("MSE_PW_TEXT_SIZE", "10")  # planeswalker abilities, measured on scans (XLN Vraska)
LINE_HEIGHTS = dict(zip(("hard", "line", "soft"), env("MSE_LINE_HEIGHTS", "1.25,1.7,0.84").split(",")))


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
    # The text box runs down behind the P/T box, so MSE lets long texts go under it; on
    # printed creatures the text stops above it (about 16 px higher on a 523 px card)
    text, n3 = re.subn(r"(?m)^(\ttext:\s*\r?\n(?:\t\t.*\r?\n)*?\t\tbottom: )\{ bottom_of_textbox\(\) \}",
                       r'\g<1>{ bottom_of_textbox() - (if card.power != "" or card.toughness != "" then '
                       + PT_CHOP + r' else 0) }',
                       text, count=1)
    n2 += n3
    if n1 or n2:
        path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        print(f"M15 style tuned (font size: {n1} patch(es), line heights: {n2})")
    # Mana symbols in rules text: the pack pads each one (horizontal space 2), which prints
    # "{2} :" instead of "{2}:" and pushes words onto the next line
    sym = base / "data" / "magic-mana-small.mse-symbol-font" / "symbol-font"
    t = sym.read_text(encoding="utf-8-sig")
    if "horizontal space: 2\n" in t.replace("\r\n", "\n"):
        sym.write_text(re.sub(r"(?m)^horizontal space: 2\s*$", "horizontal space: 0", t), encoding="utf-8")
        print("text mana symbols: no extra spacing")
    # Older frames ("Old Main", "New Main"): rules text at size 14 in MSE, smaller on print
    # (compared with scans: calibrate.py --era old/modern)
    for style, size in (("old", OLD_TEXT_SIZE), ("new", MODERN_TEXT_SIZE)):
        p = base / "data" / f"magic-{style}.mse-style" / "style"
        t = p.read_text(encoding="utf-8-sig")
        block = re.search(r"(?m)^\ttext:\s*\n(?:\t\t.*\n|\s*\n)+", t.replace("\r\n", "\n"))
        if block and "size: 14\n" in block.group(0):
            new_block = block.group(0).replace("size: 14\n", f"size: {size}\n")
            p.write_text(t.replace("\r\n", "\n").replace(block.group(0), new_block), encoding="utf-8")
            print(f"{style} frame text size -> {size}")
    # Planeswalker abilities: the template sets 14 (13.8 with four abilities); printed
    # planeswalkers use smaller type (measured on scans: ~10)
    pw = base / "data" / f"magic-{STYLE_PW}.mse-style" / "style"
    t = pw.read_text(encoding="utf-8-sig")
    new = re.sub(r"(size: \{if styling\.font_size != \"\" then styling\.font_size else if has_four_abilities\(\) then )13\.8( else )14\}",
                 rf"\g<1>{float(PW_TEXT_SIZE) - 0.2:g}\g<2>{PW_TEXT_SIZE}}}", t)
    if new != t:
        pw.write_text(new, encoding="utf-8")
        print(f"planeswalker text size -> {PW_TEXT_SIZE}")
    # Bottom line (collector number, set code): Gotham on real cards; the pack's Relay-Medium
    # is heavier and tighter. Montserrat (installed by setup_mse.ps1) is the closer free match.
    font = env("INFO_FONT", "Gotham Medium")     # as printed; shipped in the Full Magic Pack fonts
    for p in (base / "data" / "magic-modules.mse-include" / "information").glob("card_fields*"):
        t = p.read_text(encoding="utf-8-sig")
        new = t.replace("Relay-Medium", font) if font != "Relay-Medium" else t
        # Montserrat is wider and taller than Relay: at the stock size 7 the collector number
        # and set code print larger than on real cards
        new = re.sub(rf"(name:\s*{re.escape(font)}\s*\r?\n\s*size:\s*\{{\s*)7(\s*\*)", rf"\g<1>{INFO_SIZE}\g<2>", new)
        if new != t:
            p.write_text(new, encoding="utf-8")
            print(f"bottom-line font -> {font} {INFO_SIZE} ({p.name})")


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
        if code in NO_SYMBOL or code in glyphs or official_symbol_mask(code, height=64) is not None:
            by_set[code].append((c, art))
        else:
            print(f"  skipped {c['name']!r}: no symbol for set {code!r}")

    failed = []
    for code, group in sorted(by_set.items()):
        todo = [(c, a) for c, a in group if not (out_dir / f"{c['id']}.png").exists()]
        if not todo:
            continue
        symbols = {} if code in NO_SYMBOL else symbol_images(code, font, glyphs.get(code), sym_dir)
        if code in NO_SYMBOL:                     # (MSE still looks for the rarity images)
            for r in RARITY_LOOK:
                Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(sym_dir / f"{code}{r}.png")
        set_path = WORK / f"quiz-{code}.mse-set"
        write_set(code, todo, set_path)
        cmd = [str(exe), "--export-images", str(set_path), str(out_dir / "{card.notes}.png")]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        try:
            out, _ = proc.communicate(timeout=float(env("MSE_TIMEOUT", "900")))
        except subprocess.TimeoutExpired:         # MSE waiting on a dialog: show it, then move on
            try:
                from PIL import ImageGrab
                ImageGrab.grab().save(out_dir / f"hang-{code}.png")
            except Exception as e:
                print(f"  (no screenshot: {e})")
            proc.kill()
            out, _ = proc.communicate()
            print(f"  [{code}] Magic Set Editor did not finish in time")
        log = "\n".join(line for line in (out or "").splitlines()
                        if line.strip() and "Unexpected key" not in line)
        if log:
            print(log[-2000:])
        for c, _ in todo:                        # keep the largest text size that fits
            if "Planeswalker" not in c["type_line"] and era(c) == "current":
                pick_size(out_dir, c)
        missing = [c["name"] for c, _ in todo if not (out_dir / f"{c['id']}.png").exists()]
        failed += missing
        meta = set_meta(code, [c for c, _ in todo])
        for c, _ in todo:                        # set symbol and collector info, as printed
            png = out_dir / f"{c['id']}.png"
            if png.exists() and symbols:
                letter, frame = RARITY_LETTER.get(c["rarity"], "r"), era(c)
                if frame == "old":                # white outlines; all black before Exodus
                    letter = "old-" + (letter if meta["released_at"] >= RARITY_COLORS_SINCE else "c")
                paste_symbol(png, symbols.get(letter, symbols["r"]), FRAMES[frame])
            if png.exists():
                if "Planeswalker" not in c["type_line"] and era(c) == "current":
                    num, rar = card_number(c, meta), RARITY_LETTER.get(c["rarity"], "r").upper()
                    new = meta["released_at"] >= NEW_NUMBERING
                    draw_info(png, base, f"{rar} {num}" if new else f"{num} {rar}",
                              f"{code.upper()} • EN", c.get("artist") or "")
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
