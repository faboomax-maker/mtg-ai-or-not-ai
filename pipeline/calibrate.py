"""Calibrate the shared rendering rules against Scryfall scans of real cards.

Renders ~30 real cards exactly like the quiz does, downloads the scan of each printing and
measures both images with the same pixel code: text block and line height, lowest text line,
set symbol (height, right edge, vertical centre, outline width), collector info lines.
The medians of the differences give the values to use for the constants of render_mse.py
(SYMBOL_H, SYMBOL_RIGHT, SYMBOL_CY, SYMBOL_STROKE, text sizes...). They are applied to every
card, real or AI alike: nothing here is tuned per card, so no card gets better than another.

Usage (needs Magic Set Editor, like render_mse.py):
    python pipeline/calibrate.py --count 30
Output: pipeline/work/calib/calibration.json + sheet_N.png (render | scan, side by side)
"""
from __future__ import annotations

import argparse
import io
import json
import random
import statistics
import sys
import time

from PIL import Image, ImageDraw

from common import WORK, WORK_IMG, ensure_dirs, fetch_bytes, normalize_image, save_json, session
from fetch_real import (API, FIELDS, ensure_set_icon, era_query, keep, scan_llm, with_printed_text,
                        with_scan_text)
import render_mse as R

CALIB = WORK / "calib"
SIZE = (745, 1040)                  # measuring size (Scryfall 'png' scans); renders scaled up to it


# ------------------------------------------------------------------ sample
def sample(count: int, names: list[str] | None = None, era: str = "current") -> list[tuple[dict, str]]:
    """Real cards of one frame era (mostly commons/uncommons, some creatures) + scan URL;
    or the named cards."""
    s, llm = session(), scan_llm()
    q = era_query(era)
    queries = [f"({q}) r:common"] * 5 + [f"({q}) r:uncommon"] * 4 + [f"({q}) t:creature"] * 2
    todo = list(names or [])
    count = len(todo) or count
    out, seen, tries = [], set(), 0
    while len(out) < count and tries < count * 6:
        tries += 1
        if todo:
            name, _, code = todo.pop(0).partition("|")          # "Banishing Stroke|avr": that printing
            r = s.get(f"{API}/cards/named", params={"exact": name, **({"set": code} if code else {})}, timeout=30)
        else:
            r = s.get(f"{API}/cards/random", params={"q": random.choice(queries)}, timeout=30)
        time.sleep(0.12)
        if r.status_code != 200:
            time.sleep(2); continue
        card = r.json()
        if card["id"] in seen or not keep(card) or "png" not in card.get("image_uris", {}):
            continue
        seen.add(card["id"])
        img = WORK_IMG / f"real_{card['id']}.jpg"
        normalize_image(fetch_bytes(s, card["image_uris"]["art_crop"]), img)
        ensure_set_icon(s, card["set"])
        entry = with_printed_text(s, {"id": card["id"], "real": True, **{k: card.get(k) for k in FIELDS},
                                      "art_crop": card["image_uris"]["art_crop"]})
        entry = with_scan_text(s, entry, card["image_uris"]["png"], llm)
        entry["image"] = img.name
        out.append((entry, card["image_uris"]["png"]))
        print(f"[{len(out)}/{count}] {card['name']} ({card['set'].upper()})")
    return out


# ----------------------------------------------------------- measurements
def _dark(img: Image.Image, box: tuple[float, float, float, float], level: int = 90) -> Image.Image:
    W, H = img.size
    g = img.convert("L").crop((round(box[0] * W), round(box[1] * H), round(box[2] * W), round(box[3] * H)))
    return g.point(lambda v: 255 if v < level else 0)


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    """[(start, end)] of consecutive True values."""
    runs, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i)); start = None
    return runs


def text_block(img: Image.Image, pt: bool) -> dict | None:
    """Text lines of the rules box: top, bottom, median line height (a proxy for the type
    size), and how far right the lowest line runs (beside the P/T box or not)."""
    W, H = img.size
    x0, x1, y0, y1 = 0.085, 0.915, 0.625, 0.925
    m = _dark(img, (x0, y0, x1, y1))
    if pt:                                           # leave the P/T box out
        ImageDraw.Draw(m).rectangle((round((0.74 - x0) * W), round((0.87 - y0) * H), m.width, m.height), fill=0)
    ink = [sum(m.crop((0, y, m.width, y + 1)).getdata()) / 255 for y in range(m.height)]
    blocks = [(a, b) for a, b in _runs([v > 0 for v in ink]) if b - a >= 4]   # paragraphs (lines touch)
    if not blocks:
        return None
    last = m.crop((0, blocks[-1][0], m.width, blocks[-1][1])).getbbox()
    return {"top": (y0 * H + blocks[0][0]) / H, "bottom": (y0 * H + blocks[-1][1]) / H,
            "pitch": line_pitch(ink[blocks[0][0]:blocks[-1][1]], H), "paragraphs": len(blocks),
            "last_right": (x0 * W + (last[2] if last else 0)) / W}


def line_pitch(profile: list[float], H: int) -> float | None:
    """Distance between baselines (a proxy for the type size). Ink per row is highest just above
    a baseline and collapses right under it (only descenders go on): each collapse is a baseline.
    Pitch = median gap between consecutive baselines of the same paragraph."""
    bases, r = [], round(0.015 * H)
    for y in range(1, len(profile) - 1):
        top = max(profile[y], profile[y - 1])
        near = max(profile[max(0, y - r):y + r + 1])     # ascenders of the next line: weak drops
        if top >= 15 and top >= 0.4 * near and profile[y + 1] < 0.35 * top and (not bases or y - bases[-1] > 4):
            bases.append(y)
    gaps = [b - a for a, b in zip(bases, bases[1:])]
    if not gaps:
        return None
    gaps = [g for g in gaps if g <= 1.35 * min(gaps)]   # leave out paragraph gaps
    return statistics.median(gaps) / H if len(gaps) >= 2 else None   # (one gap may be a paragraph)


def symbol(img: Image.Image) -> dict | None:
    """Set symbol on the type line: its black outline, found from the right edge of the bar."""
    W, H = img.size
    x0, x1, y0, y1 = 0.76, 0.928, 0.568, 0.614      # inside the bar's dark border and rounded end
    m = _dark(img, (x0, y0, x1, y1), 70)
    # dark blobs; the bar's own border (long lines, the rounded end running the full height)
    # is left out, and the symbol is the rightmost group of compact blobs
    blobs, work = [], m.copy()
    while (bb := work.getbbox()):
        seed = next((x, y) for y in range(bb[1], bb[3]) for x in range(bb[0], bb[2]) if work.getpixel((x, y)) == 255)
        ImageDraw.floodfill(work, seed, 128)
        blob = work.point(lambda v: 255 if v == 128 else 0).getbbox()
        ImageDraw.floodfill(work, seed, 0)
        if blob[2] - blob[0] < m.width - 2 and 3 <= blob[3] - blob[1] < m.height - 2:
            blobs.append(blob)
    if not blobs:
        return None
    first = max(blobs, key=lambda b: b[2])
    group = [b for b in blobs if b[2] >= first[0] - 0.012 * W]
    left, right = min(b[0] for b in group), max(b[2] for b in group) - 1
    top, bottom = min(b[1] for b in group), max(b[3] for b in group)
    if right >= m.width - 2 or top <= 0 or bottom >= m.height:
        return None                                  # symbol merged with the bar: not measurable
    mid = m.crop((left, (top + bottom) // 2, right + 1, (top + bottom) // 2 + 1))
    run = next((b - a for a, b in _runs([mid.getpixel((x, 0)) == 255 for x in range(mid.width)])), 0)
    return {"h": (bottom - top) / H, "right": (x0 * W + right + 1) / W,
            "cy": (y0 * H + (top + bottom) / 2) / H, "outline": run / H}


def info_lines(img: Image.Image) -> dict | None:
    """Collector info (light ink on the black border): top of each line, left edge, line-1 width."""
    W, H = img.size
    x0, y0 = 0.04, 0.928
    g = img.convert("L").crop((round(x0 * W), round(y0 * H), round(0.40 * W), round(0.975 * H)))
    m = g.point(lambda v: 255 if v > 150 else 0)
    rows = [bool(m.crop((0, y, m.width, y + 1)).getbbox()) for y in range(m.height)]
    lines = [(a, b) for a, b in _runs(rows) if b - a >= 3][:2]
    if len(lines) < 2:
        return None
    l1 = m.crop((0, lines[0][0], m.width, lines[0][1])).getbbox()
    return {"l1": (y0 * H + lines[0][0]) / H, "l2": (y0 * H + lines[1][0]) / H,
            "x": (x0 * W + l1[0]) / W, "l1_w": (l1[2] - l1[0]) / W,
            "cap": (lines[1][1] - lines[1][0]) / H}


def measure(img: Image.Image, card: dict) -> dict:
    if R.era(card) != "current":                 # measuring boxes are the M15 frame's: sheets only
        return {"text": None, "symbol": None, "info": None}
    pt = card.get("power") not in (None, "") or card.get("toughness") not in (None, "")
    pw = "Planeswalker" in card["type_line"]
    sym = None if pw else symbol(img)             # (the planeswalker frame has its own type bar)
    if sym and card["rarity"] == "common":       # black shape, light outline: bbox only
        sym.pop("outline")
    return {"text": None if pw else text_block(img, pt), "symbol": sym,
            "info": None if pw else info_lines(img)}


# ----------------------------------------------------------------- report
def deltas(results: list[dict]) -> dict:
    """Median scan-minus-render difference (and ratio for sizes) of every measurement."""
    out = {}
    for part in ("text", "symbol", "info"):
        keys = {k for r in results if r["scan"].get(part) for k in r["scan"][part]}
        for k in sorted(keys):
            pairs = [(a, b) for r in results
                     for a, b in [((r["scan"].get(part) or {}).get(k), (r["render"].get(part) or {}).get(k))]
                     if a is not None and b is not None]
            if not pairs:
                continue
            d = [a - b for a, b in pairs]
            entry = {"n": len(pairs), "median_delta": round(statistics.median(d), 5),
                     "mean_abs": round(statistics.mean(abs(x) for x in d), 5)}
            if all(b > 0 for _, b in pairs):
                entry["median_ratio"] = round(statistics.median(a / b for a, b in pairs), 4)
            out[f"{part}.{k}"] = entry
    return out


def recommend(d: dict) -> dict:
    """New values of the render_mse.py constants from the median differences."""
    rec = {}
    g = lambda k, f: d[k][f] if k in d and f in d[k] else None
    if g("symbol.h", "median_ratio"):
        rec["SYMBOL_H"] = f"{R.SYMBOL_H * 523 * g('symbol.h', 'median_ratio'):.1f} / 523"
    if g("symbol.right", "median_delta") is not None:
        rec["SYMBOL_RIGHT"] = round(R.SYMBOL_RIGHT + g("symbol.right", "median_delta"), 4)
    if g("symbol.cy", "median_delta") is not None:
        rec["SYMBOL_CY"] = f"{(R.SYMBOL_CY + g('symbol.cy', 'median_delta')) * 523:.1f} / 523"
    # (symbol.outline is only 1-2 px wide at this resolution: reported, too coarse to set SYMBOL_STROKE)
    if g("text.pitch", "median_ratio"):
        # >1: print uses larger type than we pick -> SIZE_STEPS / PW_TEXT_SIZE scaled by this factor
        rec["text size factor"] = g("text.pitch", "median_ratio")
    if g("text.bottom", "median_delta") is not None:
        rec["text bottom shift (fraction of height)"] = g("text.bottom", "median_delta")
    for k, const in (("info.l1", "INFO_L1"), ("info.l2", "INFO_L2"), ("info.x", "INFO_X")):
        if g(k, "median_delta") is not None:
            rec[const] = round(getattr(R, const) + g(k, "median_delta"), 4)
    if g("info.cap", "median_ratio"):
        rec["INFO_CAP"] = round(R.INFO_CAP * g("info.cap", "median_ratio"), 4)
    return rec


def sheets(pairs: list[tuple[dict, Image.Image, Image.Image]], per_page: int = 8) -> None:
    """Render | scan side by side, 4 pairs per row."""
    w, h = 300, round(300 * SIZE[1] / SIZE[0])
    for page in range(0, len(pairs), per_page):
        chunk = pairs[page:page + per_page]
        rows = (len(chunk) + 3) // 4
        sheet = Image.new("RGB", (4 * (2 * w + 30), rows * (h + 30)), "white")
        d = ImageDraw.Draw(sheet)
        for i, (card, ren, scan) in enumerate(chunk):
            x, y = (i % 4) * (2 * w + 30), (i // 4) * (h + 30)
            sheet.paste(ren.resize((w, h), Image.LANCZOS), (x, y + 20))
            sheet.paste(scan.resize((w, h), Image.LANCZOS), (x + w, y + 20))
            d.text((x + 4, y + 4), f"{card['name']} ({card['set'].upper()})  render | scan", fill="black")
        sheet.save(CALIB / f"sheet_{page // per_page + 1}.png")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--cards", default="", help="';'-separated card names instead of a random sample")
    ap.add_argument("--era", default="current", choices=["old", "modern", "current"], help="frame era")
    args = ap.parse_args()
    ensure_dirs()
    CALIB.mkdir(parents=True, exist_ok=True)
    cards = sample(args.count, [n.strip() for n in args.cards.split(";") if n.strip()], args.era)
    out_dir = CALIB / "render"
    R.render([(c, WORK_IMG / c["image"]) for c, _ in cards], out_dir)

    s, results, pairs = session(), [], []
    for card, png_url in cards:
        png = out_dir / f"{card['id']}.png"
        if not png.exists():
            continue
        ren = Image.open(png).convert("RGB")
        scan = Image.open(io.BytesIO(fetch_bytes(s, png_url))).convert("RGB")
        # same blur on both: the scan goes through the render's resolution first
        scan = scan.resize(ren.size, Image.LANCZOS).resize(SIZE, Image.LANCZOS)
        ren = ren.resize(SIZE, Image.LANCZOS)
        time.sleep(0.12)
        results.append({"name": card["name"], "set": card["set"], "rarity": card["rarity"],
                        "scan_text": bool(card.get("printed_markup")),
                        "render": measure(ren, card), "scan": measure(scan, card)})
        pairs.append((card, ren, scan))
    if not results:
        sys.exit("nothing rendered")
    d = deltas(results)
    report = {"cards": len(results), "deltas": d, "recommended": recommend(d), "per_card": results}
    save_json(CALIB / "calibration.json", report)
    sheets(pairs)
    print(json.dumps({"deltas": d, "recommended": report["recommended"]}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
