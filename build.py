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


# --------------------------------------------------------------------------- #
# web build — the same deck, as a hosted page
# --------------------------------------------------------------------------- #
WEB_OUT = DIST / "deck_web.html"

# The Artifact host supplies <!doctype>, <html>, <head> and <body>, so the web
# build is a body fragment: the deck's own <title> and <style>, its slides, and
# a shell around them. The shell honours the deck's tokens rather than inventing
# a second design system; it only adds what a hosted page needs that a printed
# one does not — a viewport-relative scale, and a theme-aware ground so a dark
# viewer is not flashbanged by the surround. The slides themselves stay in their
# printed light world, exactly as they appear in the PDF.
SHELL_CSS = """
/* ===================== WEB SHELL ===================== */
:root{
  --shell-bg:#E7ECF1; --shell-ink:#0B2233; --shell-mute:#5B6E7E;
  --shell-line:#CBD6DF; --shell-glow:rgba(11,34,51,.13);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --shell-bg:#0A1621; --shell-ink:#E9EFF4; --shell-mute:#8FA4B4;
    --shell-line:#1D3244; --shell-glow:rgba(0,0,0,.5);
  }
}
:root[data-theme="dark"]{
  --shell-bg:#0A1621; --shell-ink:#E9EFF4; --shell-mute:#8FA4B4;
  --shell-line:#1D3244; --shell-glow:rgba(0,0,0,.5);
}
html{background:var(--shell-bg)}
body{background:var(--shell-bg);color:var(--shell-ink);padding:0;
  font-family:var(--f-text);direction:rtl}

.wrap{max-width:1560px;margin:0 auto;padding:0 clamp(16px,3vw,32px) 88px}
.hd{padding:clamp(40px,6vw,72px) 0 clamp(26px,3vw,38px);
  border-bottom:1px solid var(--shell-line);margin-bottom:clamp(26px,3.4vw,44px)}
.hd-k{font-size:13px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:var(--accent)}
.hd-t{font-family:var(--f-display);font-weight:700;line-height:1.12;
  font-size:clamp(30px,4.4vw,54px);margin-top:14px;text-wrap:balance;color:var(--shell-ink)}
.hd-m{display:flex;flex-wrap:wrap;gap:8px 30px;margin-top:20px;
  font-size:clamp(14px,1.2vw,17px);color:var(--shell-mute)}
.hd-m b{font-weight:700;color:var(--shell-ink)}
.hd-h{margin-top:22px;font-size:14px;color:var(--shell-mute)}
.hd-h kbd{font-family:var(--f-text);font-weight:700;font-size:13px;color:var(--shell-ink);
  border:1px solid var(--shell-line);border-bottom-width:2px;padding:2px 7px;margin:0 2px}

.deck{display:flex;flex-direction:column;gap:clamp(22px,2.6vw,38px)}
/* Each slide keeps its exact 1920x1080 geometry and is scaled down to fit the
   column. On a narrow screen a fitted slide would render 24px type at about
   4px, so below a legibility floor the slide holds that floor and pans inside
   its OWN stage — the page body still never scrolls sideways. The sizer carries
   the scrollable width, because a transform does not change a layout box. */
.stage{position:relative;width:100%;overflow-x:auto;overflow-y:hidden;
  background:#FFFFFF;overscroll-behavior-x:contain;
  box-shadow:0 1px 2px var(--shell-glow),0 14px 38px var(--shell-glow)}
.sizer{width:calc(1920px * var(--s,1));height:calc(1080px * var(--s,1))}
.stage .slide{position:absolute;top:0;left:0;margin:0;border:0;
  transform-origin:top left;transform:scale(var(--s,1))}
.pan{display:none;margin-top:12px;font-size:14px;color:var(--shell-mute)}
.is-panning .pan{display:block}

.ft{margin-top:clamp(30px,4vw,52px);padding-top:22px;border-top:1px solid var(--shell-line);
  font-size:14px;line-height:1.6;color:var(--shell-mute);max-width:900px}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""

SHELL_JS = """
(function(){
  var deck = document.querySelector('.deck');
  var stages = Array.prototype.slice.call(document.querySelectorAll('.stage'));
  /* Slides are authored at 1920x1080. Fit them to the column, but never below
     MIN_W: under that, 24px body type falls below ~11px and stops being
     readable, so the slide holds MIN_W and pans inside its own stage instead. */
  var MIN_W = 900;
  function fit(){
    var avail = deck.clientWidth;
    var target = Math.max(avail, MIN_W);
    deck.style.setProperty('--s', target / 1920);
    document.body.classList.toggle('is-panning', target > avail + 1);
  }
  fit();
  if (window.ResizeObserver) new ResizeObserver(fit).observe(document.body);
  window.addEventListener('resize', fit);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function go(dir){
    var y = window.scrollY, best = null;
    for (var i=0;i<stages.length;i++){
      var t = stages[i].getBoundingClientRect().top + y - 24;
      if (dir > 0 ? t > y + 4 : t < y - 4) {
        if (best === null || (dir > 0 ? t < best : t > best)) best = t;
      }
    }
    if (best !== null) window.scrollTo({top: best, behavior: reduce ? 'auto' : 'smooth'});
  }
  document.addEventListener('keydown', function(e){
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' ') { e.preventDefault(); go(1); }
    else if (e.key === 'ArrowUp' || e.key === 'PageUp') { e.preventDefault(); go(-1); }
  });
})();
"""


def build_web(html: str, d: dict, n_pages: int) -> int:
    """Derive the hosted page from the very same generated deck."""
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    style = re.search(r"<style>.*?</style>", html, re.S).group(0)
    body = re.search(r"<body[^>]*>(.*?)</body>", html, re.S).group(1)
    body = re.sub(r"<script>.*?</script>", "", body, flags=re.S)   # the ?flat= toggle is moot here

    sections = re.findall(r"<section class=\"slide.*?</section>", body, re.S)
    if len(sections) != n_pages:
        print(f"ERROR: web build found {len(sections)} slides, expected {n_pages}", file=sys.stderr)
        return 1
    stages = "\n".join(
        f'<div class="stage"><div class="sizer"></div>{s}</div>' for s in sections
    )

    m = d["meeting"]
    page = (
        f"<title>{esc(d['web']['title_he'])}</title>\n"
        + style + f"<style>{SHELL_CSS}</style>\n"
        '<div class="wrap">\n'
        '  <header class="hd">\n'
        f'    <div class="hd-k">{esc(d["web"]["kicker_he"])}</div>\n'
        f'    <h1 class="hd-t">{esc(title.split("—")[0].strip())}</h1>\n'
        '    <div class="hd-m">'
        f'<span>תאריך <b>{esc(m["date_he"])}</b></span>'
        f'<span>משתתפים <b>{esc(m["participants_he"])}</b></span>'
        f'<span>שקפים <b><span dir="ltr">{n_pages}</span></b></span>'
        "</div>\n"
        '    <div class="hd-h">ניווט: <kbd>↓</kbd><kbd>↑</kbd> או גלילה רגילה.</div>\n'
        '    <div class="pan">במסך צר — החליקו את השקף לצדדים כדי לראות אותו במלואו.</div>\n'
        "  </header>\n"
        f'  <div class="deck">{stages}</div>\n'
        f'  <p class="ft">{esc(d["charts"]["source_he"])} {esc(d["web"]["note_he"])}</p>\n'
        "</div>\n"
        f"<script>{SHELL_JS}</script>\n"
    )
    WEB_OUT.write_text(page, encoding="utf-8")
    print(f"       web -> {WEB_OUT.relative_to(ROOT)} "
          f"({len(page.encode('utf-8')) / 1024:.0f} KB, {n_pages} stages)")
    return 0


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

    return build_web(html, d, n_pages)


if __name__ == "__main__":
    raise SystemExit(main())
