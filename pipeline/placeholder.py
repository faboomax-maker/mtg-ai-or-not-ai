"""Free placeholder art (soft gradients) to test the site without any API."""
from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw, ImageFilter


def gradient_jpeg(seed: int, w: int = 832, h: int = 608) -> bytes:
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    a = [rnd.randint(20, 120) for _ in range(3)]
    b = [rnd.randint(90, 230) for _ in range(3)]
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    for _ in range(14):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(30, 180)
        col = tuple(rnd.randint(40, 255) for _ in range(3))
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    img = img.filter(ImageFilter.GaussianBlur(28))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()
