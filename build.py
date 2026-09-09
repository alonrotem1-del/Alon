#!/usr/bin/env python3
"""
build.py — renders deck_template.html + data/deck_data.json into dist/deck.html.

  * substitutes {{dotted.path}} tokens from the JSON, so no figure is ever typed
    by hand into the markup;
  * computes {{derived.*}} values (ratios, chart scales, bar geometry) rather
    than letting a headline or a bar length drift away from the source;
  * expands {{BLOCK:name}} regions;
  * inlines fonts and images as base64 data URIs — dist/deck.html is one
    self-contained file;
  * auto-numbers the pages, injecting the footer rule, caption and page number
    into every <section class="slide">.

deck_template.html is the only hand-authored file. dist/deck.html is generated
and must never be edited.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "deck_template.html"
DATA = ROOT / "data" / "deck_data.json"
DIST = ROOT / "dist"
OUT = DIST / "deck.html"
PORTRAIT_CANDIDATES = ("portrait.jpg", "portrait.jpeg", "portrait.png", "portrait.webp")

# width reserved at the end of every chart track for its value label, matching
# .sr-track / .mc-grid { right: 196px } in the stylesheet
LABEL_GUTTER_PX = 196


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def num(n) -> str:
    return f"{int(n):,}"


def ltr(s) -> str:
    """A Latin/numeric run inside Hebrew, isolated with a real dir attribute."""
    return f'<span dir="ltr">{s}</span>'


def rng(lo, hi) -> str:
    return ltr(f"{lo}–{hi}")


def dotted(data: dict, path: str):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"token {{{{{path}}}}} not found in deck_data.json")
        cur = cur[part]
    return cur


def data_uri(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if path.suffix == ".woff2":
        mime = "font/woff2"
    return f"data:{mime or 'application/octet-stream'};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


# --------------------------------------------------------------------------- #
# derived values — computed from source, never asserted
# --------------------------------------------------------------------------- #
def derive(d: dict) -> dict:
    a, b = d["alternatives"]

    def ratio(lo_k, hi_k):
        return b[lo_k] / a[lo_k], b[hi_k] / a[hi_k]

    h_lo, h_hi = ratio("hours_min", "hours_max")
    f_lo, f_hi = ratio("fee_min", "fee_max")

    def fmt(x):
        return f"{x:.0f}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"

    hours_word = f"פי {fmt(h_lo)}" if abs(h_lo - h_hi) < 0.05 else f"פי {fmt(h_lo)}–{fmt(h_hi)}"
    fee_word = f"פי {fmt(f_lo)}" if abs(f_lo - f_hi) < 0.05 else f"פי {fmt(f_lo)} עד {fmt(f_hi)}"

    return {
        "hours_ratio": hours_word,
        "fee_ratio": fee_word,
        # the finding, stated at exactly the precision the data supports
        "scale_headline": f"חלופה ב' מכפילה את שעות העבודה {hours_word}, ואת ההשקעה {fee_word}",
    }


# --------------------------------------------------------------------------- #
# block builders
# --------------------------------------------------------------------------- #
def block_about(d: dict) -> str:
    bio = d["bio"]

    photo = ""
    for name in PORTRAIT_CANDIDATES:
        if (ROOT / "assets" / name).exists():
            photo = (
                f'<div class="ab-photo"><img src="assets/{name}" '
                f'alt="{esc(bio["name_he"])}"></div>'
            )
            break
    if not photo:
        # No photograph supplied. We do not substitute a stock or generated face.
        photo = '<div class="ab-photo"></div>'

    creds = "".join(
        f'<div class="cr"><div class="cr-k">{esc(c["label_he"])}</div>'
        f'<div class="cr-v">{esc(c["value_he"])}</div></div>'
        for c in bio["credentials"]
    )

    sectors = "".join(
        f'<span class="chip">{esc(s.strip())}</span>'
        for s in bio["sectors_he"].split("·")
    )

    return (
        '<div class="ab">'
        f'<div>{photo}<div class="ab-cap">{esc(bio["photo_cap_he"])}</div>'
        f'<div class="bn" style="margin-top:24px">'
        f'<div class="bn-v" dir="ltr">{d["experience_years_min"]}+</div>'
        f'<div class="bn-k">{esc(bio["practice_he"])}</div></div></div>'
        f'<div class="ab-rows">{creds}'
        f'<div><div class="ab-lab">{esc(bio["sectors_label_he"])}</div>'
        f'<div class="ab-chips">{sectors}</div></div></div>'
        "</div>"
    )


def block_phases(d: dict) -> str:
    out = []
    for i, ph in enumerate(d["phases"]):
        bullets = "".join(
            f'<div class="ph-b"><div class="ph-dot"></div><div>'
            f'<div class="ph-h">{esc(b["head_he"])}</div>'
            f'<div class="ph-d">{esc(b["body_he"])}</div></div></div>'
            for b in ph["bullets"]
        )
        out.append(
            f'<div class="ph{" ph-2" if i else ""}">'
            f'<div class="ph-top">'
            f'<div class="tile-k">{esc(ph["letter_he"])} · {esc(ph["title_en"])}</div>'
            f'<div class="tile-h">{esc(ph["title_he"])}</div></div>'
            f'<div class="ph-list">{bullets}</div></div>'
        )
    return '<div class="ph-row">' + "".join(out) + "</div>"


def block_table(d: dict) -> str:
    a, b = d["alternatives"]

    def scope(alt):
        chips = []
        if "sessions_min" in alt:
            chips.append(f'<span class="chip">{rng(alt["sessions_min"], alt["sessions_max"])} מפגשים</span>')
        chips.append(f'<span class="chip">{rng(alt["hours_min"], alt["hours_max"])} שעות</span>')
        chips.append(f'<span class="chip">{rng(alt["weeks_min"], alt["weeks_max"])} שבועות</span>')
        return f'<div class="ab-chips">{"".join(chips)}</div>'

    def deliverables(alt):
        return "<br>".join(esc(t) for t in alt["deliverables_he"])

    def fee(alt):
        return (
            f'<div class="fee">{ltr(num(alt["fee_min"]) + " – " + num(alt["fee_max"]))} '
            f'{esc(alt["currency"])}</div>'
            f'<div class="fee-vat">{esc(alt["vat_he"])}</div>'
        )

    def head(alt, cls=""):
        return (
            f'<th class="{cls}">חלופה {esc(alt["letter_he"])} — {esc(alt["name_he"])}</th>'
        )

    rows = [
        ("מטרה", esc(a["goal_he"]), esc(b["goal_he"])),
        ("היקף", scope(a), (f'<div style="margin-bottom:12px">{esc(b["scope_extra_he"])}</div>' + scope(b))),
        ("תוצרים", deliverables(a), deliverables(b)),
        ("השקעה", fee(a), fee(b)),
    ]
    body = "".join(
        f'<tr><td class="k">{esc(k)}</td><td>{va}</td><td>{vb}</td></tr>'
        for k, va, vb in rows
    )
    return (
        '<table class="tbl"><thead><tr><th style="width:196px"></th>'
        + head(a, "th-a") + head(b) +
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def block_charts(d: dict) -> str:
    """Three small multiples. Bar geometry is computed here, not eyeballed."""
    a, b = d["alternatives"]
    specs = [
        ("שעות עבודה", "שעות", "hours_min", "hours_max", lambda v: f"{v:g}"),
        ("משך", "שבועות", "weeks_min", "weeks_max", lambda v: f"{v:g}"),
        ("השקעה", 'שקלים, לפני מע"מ', "fee_min", "fee_max", lambda v: f"{v:,.0f}"),
    ]

    charts = []
    for title, unit, lo_k, hi_k, fmt in specs:
        # scale to the largest value in the pair; the label gutter guarantees the
        # value text still has room even when a bar reaches 100%
        scale = max(a[hi_k], b[hi_k])

        series = []
        for alt, cls in ((a, "sr-a"), (b, "sr-b")):
            lo, hi = alt[lo_k], alt[hi_k]
            lo_pct = lo / scale * 100
            hi_pct = hi / scale * 100
            series.append(
                f'<div class="sr {cls}">'
                f'<div class="sr-lab">חלופה {esc(alt["letter_he"])}</div>'
                f'<div class="sr-track">'
                f'<div class="bar-min" style="width:{lo_pct:.3f}%"></div>'
                f'<div class="bar-rng" style="left:{lo_pct:.3f}%;width:{hi_pct - lo_pct:.3f}%"></div>'
                f'<div class="sr-v" style="left:calc({hi_pct:.3f}% + 14px)">'
                f'{ltr(fmt(lo) + "–" + fmt(hi))}</div>'
                f"</div></div>"
            )

        grid = "".join(
            f'<div class="gl{" gl-0" if p == 0 else ""}" style="left:{p}%"></div>'
            for p in (0, 25, 50, 75, 100)
        )
        axis = (
            f'<div class="gl-t" style="left:0">{ltr("0")}</div>'
            f'<div class="gl-t" style="left:100%">{ltr(fmt(scale))}</div>'
        )
        charts.append(
            '<figure class="mc"><figcaption>'
            f'<div class="mc-t">{esc(title)}</div>'
            f'<div class="mc-u">{esc(unit)}</div></figcaption>'
            f'<div class="mc-plot"><div class="mc-grid">{grid}{axis}</div>'
            f'<div class="mc-series">{"".join(series)}</div></div></figure>'
        )
    return '<div class="mc-row">' + "".join(charts) + "</div>"


def block_questions(d: dict) -> str:
    rows = "".join(
        f'<div class="q-row"><div class="q-n" dir="ltr">{esc(q["index"])}</div>'
        f'<div><div class="q-k">{esc(q["tag_he"])}</div>'
        f'<div class="q-t">{esc(q["q_he"])}</div></div></div>'
        for q in d["discussion"]
    )
    return f'<div class="q-list">{rows}</div>'


def block_next(d: dict) -> str:
    text = d["next_step_he"]
    prefix = "הצעד הבא:"
    if text.startswith(prefix):
        text = text[len(prefix):].strip()
    return (
        '<div class="next"><div class="next-k">הצעד הבא</div>'
        f'<div class="next-t">{esc(text)}</div></div>'
    )


BLOCKS = {
    "about": block_about,
    "phases": block_phases,
    "table": block_table,
    "charts": block_charts,
    "questions": block_questions,
    "next": block_next,
}


# --------------------------------------------------------------------------- #
# pipeline
# --------------------------------------------------------------------------- #
def expand_blocks(html: str, d: dict) -> str:
    def sub(m):
        name = m.group(1)
        if name not in BLOCKS:
            raise KeyError(f"unknown {{{{BLOCK:{name}}}}}")
        return BLOCKS[name](d)

    return re.sub(r"\{\{BLOCK:([a-z_]+)\}\}", sub, html)


def expand_tokens(html: str, d: dict) -> str:
    return re.sub(
        r"\{\{([a-z_]+(?:\.[a-z0-9_]+)*)\}\}",
        lambda m: esc(dotted(d, m.group(1))),
        html,
        flags=re.IGNORECASE,
    )


def inline_assets(html: str) -> tuple[str, int]:
    count = 0

    def repl(m):
        nonlocal count
        p = ROOT / m.group("path")
        if not p.exists():
            raise FileNotFoundError(f"asset referenced but missing: {m.group('path')}")
        count += 1
        return f"{m.group('pre')}{m.group('q')}{data_uri(p)}{m.group('q')}"

    html = re.sub(r"(?P<pre>url\()(?P<q>['\"])(?P<path>assets/[^'\"]+)(?P=q)", repl, html)
    html = re.sub(r'(?P<pre>src=)(?P<q>")(?P<path>assets/[^"]+)(?P=q)', repl, html)
    return html, count


def number_pages(html: str) -> tuple[str, int]:
    """Inject the footer — hairline rule, caption, page number — into each slide."""
    meta = re.findall(r'<section class="slide[^"]*"[^>]*data-cap="([^"]*)"', html)
    total = len(meta)

    parts = re.split(r"(</section>)", html)
    out, n = [], 0
    for chunk in parts:
        if chunk == "</section>" and n < total:
            out.append(
                '  <div class="f-rule"></div>'
                f'<div class="f-cap">{meta[n]}</div>'
                f'<div class="f-pg"><span dir="ltr">{n + 1:02d} / {total:02d}</span></div>\n'
            )
            n += 1
        out.append(chunk)
    return "".join(out), total


def main() -> int:
    d = json.loads(DATA.read_text(encoding="utf-8"))
    d["derived"] = derive(d)

    html = TEMPLATE.read_text(encoding="utf-8")
    html = expand_blocks(html, d)
    html = expand_tokens(html, d)

    leftovers = re.findall(r"\{\{[^}]+\}\}", html)
    if leftovers:
        print(f"ERROR: unsubstituted tokens remain: {leftovers}", file=sys.stderr)
        return 1

    html, n_assets = inline_assets(html)
    html, n_pages = number_pages(html)

    DIST.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")

    print(f"build: {n_pages} slides, {n_assets} assets inlined, "
          f"{len(html.encode('utf-8')) / 1024:.0f} KB -> {OUT.relative_to(ROOT)}")
    for k, v in d["derived"].items():
        print(f"       derived {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
