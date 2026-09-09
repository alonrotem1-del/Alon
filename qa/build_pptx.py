#!/usr/bin/env python3
"""
qa/build_pptx.py — turns dist/deck_extract.json into a REAL editable PowerPoint.

Text stays text (real runs you can click and retype), tables stay tables, shapes
stay shapes. No slide is ever pasted in as an image.

Geometry, per the build rules:
    1920 px = 13.333 in  ->  6350 EMU per pixel
    1 px    = 0.5 pt     (so the 24px type floor lands on 12pt)

DOM order is preserved, because PowerPoint's z-order follows shape insertion
order rather than any CSS stacking rule — ancestors (card backgrounds) are
emitted before the text that sits on them.

All autofit is stripped from the saved package: every text frame carries
<a:noAutofit/>, so PowerPoint never silently rescales the type.
"""

from __future__ import annotations

import base64
import copy
import io
import json
import re
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

ROOT = Path(__file__).resolve().parent.parent
EXTRACT = ROOT / "dist" / "deck_extract.json"
OUT = ROOT / "dist" / "deck.pptx"

EMU_PER_PX = 6350          # 1920 px -> 13.333 in
PT_PER_PX = 0.5
LRI = "\u2066"          # LEFT-TO-RIGHT ISOLATE
PDI = "\u2069"          # POP DIRECTIONAL ISOLATE
# Faces that carry Hebrew on both Windows and macOS. The web deck's Frank Ruhl
# Libre / Assistant pairing is mapped onto the nearest guaranteed pair, keeping
# the serif-display / sans-text contrast that the design depends on.
FONT_DISPLAY = "Times New Roman"
FONT_TEXT = "Arial"

ALIGN = {"right": PP_ALIGN.RIGHT, "left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER}


def px(v) -> Emu:
    return Emu(int(round(v * EMU_PER_PX)))


def pt(v) -> Pt:
    return Pt(round(v * PT_PER_PX, 2))


def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h.lstrip("#").upper()[:6])


def set_rtl(paragraph, rtl: bool) -> None:
    """PowerPoint needs an explicit rtl flag on the paragraph for Hebrew."""
    pPr = paragraph._p.get_or_add_pPr()
    pPr.set("rtl", "1" if rtl else "0")


def strip_autofit(tf) -> None:
    """Replace whatever autofit the frame has with an explicit <a:noAutofit/>."""
    bodyPr = tf._txBody.bodyPr
    for tag in ("a:normAutofit", "a:spAutoFit"):
        for el in bodyPr.findall(qn(tag)):
            bodyPr.remove(el)
    if bodyPr.find(qn("a:noAutofit")) is None:
        bodyPr.append(bodyPr.makeelement(qn("a:noAutofit"), {}))


def add_rect(slide, it: dict):
    radius = it.get("radius") or 0
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius > 0.5 else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, px(it["x"]), px(it["y"]), px(it["w"]), px(it["h"]))

    if shape_type is MSO_SHAPE.ROUNDED_RECTANGLE:
        # PowerPoint's corner adjustment is a fraction of the shorter side
        adj = max(0.0, min(0.5, radius / max(1.0, min(it["w"], it["h"]))))
        shp.adjustments[0] = adj

    if it.get("fill"):
        shp.fill.solid()
        shp.fill.fore_color.rgb = rgb(it["fill"])
    else:
        shp.fill.background()

    stroke = it.get("stroke")
    if stroke and stroke.get("color"):
        shp.line.color.rgb = rgb(stroke["color"])
        shp.line.width = pt(stroke["width"])
    else:
        shp.line.fill.background()

    shp.shadow.inherit = False
    # python-pptx attaches a <p:style> that points at the theme's fill, line and
    # effect refs — effectRef idx="2" is a drop shadow. An empty <a:effectLst/>
    # is meant to override it, but not every renderer honours that precedence,
    # so the deck picked up shadows the HTML never had. Drop <p:style> entirely
    # and let <p:spPr> be the whole truth, independent of whatever theme the
    # recipient's PowerPoint applies.
    style = shp._element.find(qn("p:style"))
    if style is not None:
        shp._element.remove(style)

    # a decorative shape must never swallow a click as if it were a text box
    shp.text_frame.word_wrap = False
    strip_autofit(shp.text_frame)
    return shp


# A block that occupies one line in the browser must not wrap in PowerPoint.
# Shrink-to-fit blocks (flex items such as .cred-v) get a box exactly as wide as
# their text, so the slightest metric difference — LibreOffice vs Chromium, or
# the recipient's real Arial vs the Liberation Sans measured here — pushes the
# last word onto a second line. Give single-line boxes the width their text
# needs plus headroom, extended away from the alignment edge so the text does
# not move. Multi-line blocks keep their width: there the wrap points are part
# of the layout.
SINGLE_LINE_HEADROOM = 1.12
SINGLE_LINE_PAD_PX = 8


def fit_single_line(it: dict) -> tuple[float, float, float]:
    """Return (x, w, h) for this text block, widened if it is a single line.

    Hebrew is wider in Arial than in Assistant, so a block that sits on one
    line on screen can need more room here. Widen it — but never past the
    container it is drawn inside. An over-wide box grows into its neighbour and
    the two texts overprint; a capped box merely wraps, which is the graceful
    failure. Where the cap bites, hand back the height Arial actually needs so
    the box still describes the text it holds.
    """
    x, w, h = it["x"], it["w"], it["h"]
    lh = it.get("lineHeight") or 0
    lines = round(h / lh) if lh > 0 else 1
    if lines > 1:
        return x, w, h
    need = (it.get("nowrapW") or 0) * SINGLE_LINE_HEADROOM + SINGLE_LINE_PAD_PX
    if need <= w:
        return x, w, h

    grown = min(need, max(w, it.get("containerW") or w))
    extra = grown - w
    if extra > 0:
        align = it.get("align", "right")
        if align == "right":
            x -= extra                       # grow leftwards; right edge fixed
        elif align == "center":
            x -= extra / 2
        w = grown                            # left-aligned: grows rightwards
    if grown < need:
        h = max(h, it.get("arialH") or h)    # it will wrap; own up to the height
    return x, w, h


def add_text(slide, it: dict):
    tx, tw, th = fit_single_line(it)
    box = slide.shapes.add_textbox(px(tx), px(it["y"]), px(tw), px(th))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    strip_autofit(tf)

    p = tf.paragraphs[0]
    p.alignment = ALIGN.get(it.get("align"), PP_ALIGN.RIGHT)
    set_rtl(p, it.get("rtl", True))
    p.line_spacing = pt(it["lineHeight"])

    for r in it["runs"]:
        run = p.add_run()
        text = r["t"]
        if r.get("ltr") and it.get("rtl", True):
            # CSS said unicode-bidi:isolate on this run. PowerPoint has no
            # per-run direction, so carry the same instruction as Unicode
            # isolate marks; without them an RTL paragraph renders the range
            # "9,000 - 13,000" as "13,000 - 9,000".
            text = LRI + text + PDI
        run.text = text
        f = run.font
        face = FONT_DISPLAY if r.get("serif") else FONT_TEXT
        f.name = face
        f.size = pt(r["size"])
        f.bold = bool(r["bold"])
        f.color.rgb = rgb(r["color"])
        # Hebrew runs need the complex-script font set too, or PowerPoint
        # substitutes its own theme face for the Hebrew glyphs.
        rPr = run._r.get_or_add_rPr()
        # schema order inside <a:rPr> is latin, ea, cs — emit it in that order or
        # strict readers (LibreOffice, and PowerPoint's repair prompt) reject the file
        for tag in ("a:ea", "a:cs"):
            el = rPr.find(qn(tag))
            if el is None:
                el = rPr.makeelement(qn(tag), {})
                rPr.append(el)
            el.set("typeface", face)
    return box


def add_image(slide, it: dict):
    src = it["src"]
    if src.startswith("data:"):
        raw = base64.b64decode(src.split(",", 1)[1])
        stream = io.BytesIO(raw)
    else:
        path = Path(re.sub(r"^file://", "", src))
        if not path.exists():
            return None
        stream = io.BytesIO(path.read_bytes())
    return slide.shapes.add_picture(stream, px(it["x"]), px(it["y"]), px(it["w"]), px(it["h"]))


def add_table(slide, it: dict):
    rows = it["rows"]
    n_rows, n_cols = len(rows), max(len(r) for r in rows)
    gfx = slide.shapes.add_table(n_rows, n_cols, px(it["x"]), px(it["y"]), px(it["w"]), px(it["h"]))
    table = gfx.table
    for ri, row in enumerate(rows):
        for ci, cell_data in enumerate(row):
            cell = table.cell(ri, ci)
            cell.text = cell_data["text"]
            cell.margin_left = cell.margin_right = Emu(45720)
            para = cell.text_frame.paragraphs[0]
            para.alignment = ALIGN.get(cell_data.get("align"), PP_ALIGN.RIGHT)
            set_rtl(para, True)
            strip_autofit(cell.text_frame)
            for run in para.runs:
                run.font.name = FONT_TEXT
                run.font.size = pt(cell_data["size"])
                run.font.bold = bool(cell_data["bold"])
                run.font.color.rgb = rgb(cell_data["color"])
    return gfx


def main() -> int:
    if not EXTRACT.exists():
        print(f"ERROR: {EXTRACT} missing — run `node qa/extract.js` first.", file=sys.stderr)
        return 1

    data = json.loads(EXTRACT.read_text(encoding="utf-8"))
    cw, ch = data["canvas"]["w"], data["canvas"]["h"]

    prs = Presentation()
    prs.slide_width = px(cw)
    prs.slide_height = px(ch)
    blank = prs.slide_layouts[6]  # blank layout: no placeholders to fight with

    counts = {"rect": 0, "text": 0, "image": 0, "table": 0}
    for s in data["slides"]:
        slide = prs.slides.add_slide(blank)

        # slide background: paint it on the slide itself rather than as a shape,
        # so nothing sits behind the content in the z-order
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb("#F9FAFB")

        for it in s["items"]:
            kind = it["kind"]
            if kind == "rect":
                add_rect(slide, it)
            elif kind == "text":
                add_text(slide, it)
            elif kind == "image":
                add_image(slide, it)
            elif kind == "table":
                add_table(slide, it)
            counts[kind] = counts.get(kind, 0) + 1

    prs.save(OUT)

    # belt and braces: assert no autofit survived anywhere in the saved package
    import zipfile

    leftover = 0
    with zipfile.ZipFile(OUT) as z:
        for name in z.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                xml = z.read(name).decode("utf-8")
                leftover += xml.count("<a:normAutofit") + xml.count("<a:spAutoFit")

    print(f"pptx -> {OUT.relative_to(ROOT)}")
    print(f"  slides    : {len(data['slides'])}")
    print(f"  shapes    : " + "  ".join(f"{k}={v}" for k, v in counts.items() if v))
    print(f"  canvas    : {cw}x{ch}px -> {prs.slide_width.inches:.3f}x{prs.slide_height.inches:.3f}in")
    print(f"  autofit remaining in saved package: {leftover}")
    return 0 if leftover == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
