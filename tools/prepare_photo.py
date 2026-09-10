#!/usr/bin/env python3
"""
tools/prepare_photo.py — derives assets/headshot.png from the photograph Alon
supplied (data/אלון.png).

The supplied file is 141x142. The About slide shows it in a 200x200 frame, and
the QA harness renders at deviceScaleFactor 2, so the browser would be asked for
roughly 400 device pixels from 141 — a 2.8x blow-up done with bilinear filtering,
which looks smeared. Resampling once here with Lanczos gives the browser a source
at the size it actually needs; it adds no detail that was not in the original,
but it stops the deck from showing an interpolation artefact instead of a face.

Nothing else is done to the image: no retouching, no cropping, no generation.

    python3 tools/prepare_photo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "אלון.png"
DST = ROOT / "assets" / "headshot.png"
FRAME = 280          # the .ab-photo frame, in CSS pixels
DPR = 2              # qa/render.js renders at deviceScaleFactor 2


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: source photograph not found: {SRC.relative_to(ROOT)}", file=sys.stderr)
        return 1

    im = Image.open(SRC).convert("RGBA")
    w, h = im.size
    target = FRAME * DPR
    scale = target / min(w, h)
    out = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)

    DST.parent.mkdir(exist_ok=True)
    out.save(DST, "PNG", optimize=True)
    print(f"photo: {SRC.name} {w}x{h} -> {DST.relative_to(ROOT)} {out.size[0]}x{out.size[1]} "
          f"(Lanczos {scale:.2f}x, {DST.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
