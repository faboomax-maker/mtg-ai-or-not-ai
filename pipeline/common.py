"""Shared helpers: paths, HTTP session, image normalisation, JSON I/O."""
from __future__ import annotations

import io
import json
import os
import re
import time
from pathlib import Path

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "pipeline" / "work"          # intermediate files (git-ignored)
WORK_IMG = WORK / "img"
WORK_SETS = WORK / "sets"                    # set symbols (SVG) + per-set card lists
DOCS = ROOT / "docs"                         # published site (GitHub Pages)

# Every illustration (real or AI) is re-encoded to exactly this size/quality,
# so neither resolution, compression nor metadata can give the answer away.
ART_W, ART_H = 640, 468
JPEG_QUALITY = 82

USER_AGENT = "mtg-real-or-ai-quiz/1.0 (fan project)"

MANA_RE = re.compile(r"^(\{[0-9WUBRGCXSP/]+\})*$")


def session() -> requests.Session:
    s = requests.Session()
    # Scryfall requires an explicit User-Agent and Accept header.
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json;q=0.9,*/*;q=0.8"})
    return s


def ensure_dirs() -> None:
    WORK_IMG.mkdir(parents=True, exist_ok=True)
    WORK_SETS.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_image(raw: bytes, dest: Path) -> None:
    """Center-crop to the common aspect ratio, resize, strip metadata, save as JPEG."""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img = ImageOps.fit(img, (ART_W, ART_H), method=Image.LANCZOS, centering=(0.5, 0.4))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)


def fetch_bytes(s: requests.Session, url: str, *, retries: int = 3, **kw) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            r = s.get(url, timeout=120, **kw)
            if r.status_code == 429:
                time.sleep(2 + attempt * 3)
                continue
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:  # pragma: no cover - network
            last = e
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f"Download failed: {url} ({last})")


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v else default
