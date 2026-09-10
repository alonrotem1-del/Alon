#!/usr/bin/env python3
"""
tools/prepare_photo.py — derives assets/headshot.png from the best photograph
Alon has supplied.

Every image in data/ is a candidate; the one with the most pixels wins, so
dropping a larger file into data/ is the whole procedure for replacing the
portrait. (The first supplied file was 141x142; a 199x200 version followed.)

The About slide shows the portrait in a 280x280 frame and the QA harness renders
at deviceScaleFactor 2, so the browser wants roughly 560 device pixels. Every
source so far is smaller than that, so the image is resampled once here with
Lanczos rather than being left for Chrome to stretch bilinearly — Lanczos is no
worse at any ratio and visibly better at large ones. It adds no detail that was
not in the original.

Nothing else is done to the image: no retouching, no cropping, no generation.

    python3 tools/prepare_photo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "data"
DST = ROOT / "assets" / "headshot.png"
SRC_SUFFIXES = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".tif", ".tiff", ".bmp"}
FRAME = 280          # the .ab-photo frame, in CSS pixels
DPR = 2              # qa/render.js renders at deviceScaleFactor 2


def candidates() -> list[tuple[int, Path, tuple[int, int]]]:
    out = []
    for f in sorted(SRC_DIR.iterdir()):
        if f.suffix.lower() not in SRC_SUFFIXES:
            continue
        try:
            with Image.open(f) as im:
                out.append((im.size[0] * im.size[1], f, im.size))
        except Exception as e:                      # not an image after all
            print(f"  skipping {f.name}: {e}", file=sys.stderr)
    return sorted(out, reverse=True)


def main() -> int:
    found = candidates()
    if not found:
        print(f"ERROR: no photograph found in {SRC_DIR.relative_to(ROOT)}", file=sys.stderr)
        return 1

    for px, f, size in found:
        mark = "->" if f is found[0][1] else "  "
        print(f"  {mark} {f.name}  {size[0]}x{size[1]}")

    _, src, (w, h) = found[0]
    im = Image.open(src).convert("RGB")
    target = FRAME * DPR
    scale = target / min(w, h)
    out = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)

    DST.parent.mkdir(exist_ok=True)
    out.save(DST, "PNG", optimize=True)
    print(f"photo: {src.name} {w}x{h} -> {DST.relative_to(ROOT)} "
          f"{out.size[0]}x{out.size[1]} (Lanczos {scale:.2f}x, "
          f"{DST.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
