#!/usr/bin/env python3
"""
build.py — renders deck_template.html + data/deck_data.json into dist/deck.html.

  * substitutes {{dotted.path}} tokens from the JSON, so no figure is ever typed
    by hand into the markup;
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
# Portrait lookup order. `headshot.*` wins over `portrait.*` so a newly supplied
# photo is picked up whatever its extension, without having to match or delete
# the file already in the repo. First match in this list is used.
PORTRAIT_CANDIDATES = (
    "headshot.jpg", "headshot.jpeg", "headshot.png", "headshot.webp",
    "portrait.jpg", "portrait.jpeg", "portrait.png", "portrait.webp",
)

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# A Latin run inside Hebrew — "iPlan", "M.B.A", "BDO", "Scope", "ICP", "DJs".
# Isolating it with a real dir attribute stops the neutral characters around it
# (hyphens, commas, brackets, the shekel sign) from being reordered by the bidi
# algorithm, in the browser and, via the extractor, in PowerPoint.
LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9.+]*(?:['’\-][A-Za-z0-9.+]+)*")


def bidi(s) -> str:
    """Escape, then wrap every Latin run in dir="ltr".

    Each segment is escaped separately so the wrapper can never land inside an
    entity such as &amp;.
    """
    s = str(s)
    out, last = [], 0
    for m in LATIN_RUN.finditer(s):
        out.append(esc(s[last:m.start()]))
        out.append(f'<span dir="ltr">{esc(m.group(0))}</span>')
        last = m.end()
    out.append(esc(s[last:]))
    return "".join(out)


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
# block builders — every string below comes from data/deck_data.json
# --------------------------------------------------------------------------- #
def block_arc(d: dict) -> str:
    """רעיון -> בחינה -> החלטה, as three segments of one rail. The third turns
    teal: it is an outcome, not another step."""
    cells = "".join(
        f'<div class="arc-c arc-{i + 1}"><div class="arc-bar"></div>'
        f'<div class="arc-k">{bidi(c["k"])}</div>'
        f'<div class="arc-t">{bidi(c["t"])}</div>'
        f'<div class="arc-d">{bidi(c["d"])}</div></div>'
        for i, c in enumerate(d["cover"]["arc"])
    )
    return f'<div class="arc"><div class="arc-cells">{cells}</div></div>'


def block_about(d: dict) -> str:
    """A CV, not a bio paragraph: portrait and name in a stone side panel, then
    experience, education and sample engagements under solid section blocks."""
    bio = d["bio"]
    photo = ""
    for name in PORTRAIT_CANDIDATES:
        if (ROOT / "assets" / name).exists():
            photo = (f'<div class="ab-photo"><img src="assets/{name}" '
                     f'alt="{esc(bio["name_he"])}"></div>')
            break
    # No photograph supplied: leave the frame empty rather than invent a face.
    if not photo:
        photo = '<div class="ab-photo"></div>'

    exp = "".join(
        f'<div class="ab-i"><div class="ab-b"></div>'
        f'<div class="ab-t">{bidi(t)}</div></div>'
        for t in bio["exp_he"]
    )
    edu = "".join(f"<span>{bidi(t)}</span>" for t in bio["edu_he"])
    # One curated line, not seven tags: the names read as a client list.
    proj = bidi(" · ".join(bio["proj_he"]))

    return (
        '<div class="ab">'
        '<div class="ab-side">' + photo
        + f'<div class="ab-name">{bidi(bio["name_he"])}</div>'
        + '<div class="ab-role">'
        + "".join(f"<span>{bidi(part.strip())}</span>"
                  for part in bio["role_he"].split("·"))
        + "</div></div>"
        '<div class="ab-col">'
        f'<div class="ab-sec ab-sec-a"><div class="ab-lab">{bidi(bio["exp_label_he"])}</div>'
        f'<div class="ab-lead">{bidi(bio["exp_lead_he"])}</div>'
        f'<div class="ab-grid">{exp}</div></div>'
        f'<div class="ab-sec ab-sec-b"><div class="ab-lab">{bidi(bio["edu_label_he"])}</div>'
        f'<div class="ab-edu">{edu}</div></div>'
        f'<div class="ab-sec ab-sec-c"><div class="ab-lab">{bidi(bio["proj_label_he"])}</div>'
        f'<div class="ab-proj">{proj}</div></div>'
        "</div></div>"
    )


def block_proof(d: dict) -> str:
    """Five banded rows. The numeral block is terracotta for 1-3 (is there an
    opportunity) and teal for 4-5 (can it be captured)."""
    rows = "".join(
        f'<div class="pf-r pf-{i}{" pf-alt" if i % 2 else ""}">'
        f'<div class="pf-n" dir="ltr">{esc(b["n"])}</div>'
        f'<div class="pf-t">{bidi(b["t"])}</div>'
        f'<div class="pf-q">' + "".join(f"<span>{bidi(q)}</span>" for q in b["q"]) +
        "</div></div>"
        for i, b in enumerate(d["proof"], 1)
    )
    return f'<div class="pf">{rows}</div>'


def block_flow(d: dict) -> str:
    """Five stage tiles, each opening with a circular numbered badge. A stage
    may carry `sub` — one line under the title, visually subordinate to it,
    used on stage 4 to mark it as a translation of 2-3's findings rather than
    a second research phase."""
    tiles = []
    for i, st in enumerate(d["stages"], 1):
        items = "".join(f"<span>{bidi(x)}</span>" for x in st["items"])
        note = f'<div class="st-note">{bidi(st["note"])}</div>' if st.get("note") else ""
        sub = f'<div class="st-sub">{bidi(st["sub"])}</div>' if st.get("sub") else ""
        tiles.append(
            f'<div class="st st-{i}">'
            '<div class="st-head">'
            f'<div class="st-badge"><div class="st-n" dir="ltr">{esc(st["n"])}</div></div>'
            f'<div class="st-k">{bidi(st["tag"])}</div>'
            f'<div class="st-t">{bidi(st["t"])}</div>{sub}'
            "</div>"
            f'<div class="st-body"><div class="st-l">{items}</div>{note}</div>'
            "</div>"
        )
    return f'<div class="flow">{"".join(tiles)}</div>'


def block_flowfoot(d: dict) -> str:
    """Two filled zones under the stage row, matching the tiles above them: the
    loop under stages 1-3, the decision gates under 4-5."""
    gates = "".join(
        f'<span class="gate gate-{i}" dir="ltr">{esc(g)}</span>'
        for i, g in enumerate(d["gates_he"], 1)
    )
    return (
        '<div class="fl-foot">'
        '<div class="loop"><div class="loop-a" dir="ltr">&#8646;</div>'
        f'<div class="loop-t">{bidi(d["loop_he"])}</div></div>'
        f'<div class="gates"><div class="gate-row">{gates}</div>'
        f'<div class="gates-c">{bidi(d["gates_cap_he"])}</div></div>'
        "</div>"
    )


def block_options(d: dict) -> str:
    """Two ways of running the same work, equal in weight and different in hue.
    No commercial figure lives here — the rate and the indicative hours are on
    the engagement-frame slide."""
    cards = []
    for o in d["options"]:
        note = (f'<div class="op-note">{bidi(o["note_he"])}</div>'
                if o.get("note_he") else "")
        cards.append(
            f'<div class="op op-{o["id"]}">'
            f'<div class="op-h">חלופה {bidi(o["letter_he"])} — {bidi(o["name_he"])}</div>'
            '<div class="op-body">'
            f'<div class="op-d">{bidi(o["desc_he"])}</div>'
            '<div class="op-rows">'
            f'<div class="op-row"><div class="op-k">{bidi(o["alon_label_he"])}</div>'
            f'<div class="op-v">{bidi(o["alon_he"])}</div></div>'
            f'<div class="op-row"><div class="op-k">{bidi(o["founders_label_he"])}</div>'
            f'<div class="op-v">{bidi(o["founders_he"])}</div></div>'
            "</div>"
            f"{note}"
            '<div class="op-eval">'
            '<div class="ev ev-pro">'
            f'<div class="ev-k">{bidi(o["pro_label_he"])}</div>'
            f'<div class="ev-t">{bidi(o["pro_he"])}</div></div>'
            '<div class="ev ev-con">'
            f'<div class="ev-k">{bidi(o["con_label_he"])}</div>'
            f'<div class="ev-t">{bidi(o["con_he"])}</div></div>'
            "</div></div></div>"
        )
    return f'<div class="opts">{"".join(cards)}</div>'


def block_questions(d: dict) -> str:
    """The last question is the one whose answer decides what the work is for,
    so it is the one carrying the accent."""
    rows = []
    last = len(d["discussion"])
    for i, q in enumerate(d["discussion"], 1):
        hi = " q-hi" if i == last else ""
        rows.append(
            f'<div class="q-r{hi}"><div class="q-n" dir="ltr">{esc(q["n"])}</div>'
            f'<div class="q-t">{bidi(q["q"])}</div></div>'
        )
    return f'<div class="qs">{"".join(rows)}</div>'


def block_commercial(d: dict) -> str:
    """The only slide carrying a price. One rate at display size, then what each
    track means for scope — an indicative hour range where one exists, and an
    explicit "set after the mapping meeting" where none does.

    The rate runs as flex items rather than as one bidi string: in an RTL row
    the first item sits rightmost, so 450 / ₪ / + מע"מ can never reorder."""
    c, r = d["commercial"], d["rate"]
    by_id = {o["id"]: o for o in d["options"]}

    cards = []
    for t in c["tracks"]:
        o = by_id[t["option_id"]]
        if "hours_min" in t:
            value = (f'<div class="trk-v">כ־{rng(t["hours_min"], t["hours_max"])} '
                     f'{bidi(t["unit_he"])}</div>')
        else:
            value = f'<div class="trk-v">{bidi(t["value_he"])}</div>'
        cards.append(
            f'<div class="trk trk-{t["option_id"]}">'
            f'<div class="trk-k">חלופה {bidi(o["letter_he"])} — {bidi(o["name_he"])}</div>'
            f'<div class="trk-l">{bidi(t["label_he"])}</div>'
            f"{value}"
            f'<div class="trk-n">{bidi(t["note_he"])}</div>'
            "</div>"
        )

    return (
        '<div class="cm">'
        '<div class="rate">'
        f'<div class="rate-k">{bidi(c["rate_label_he"])}</div>'
        '<div class="rate-fig">'
        f'<div class="rate-v" dir="ltr">{esc(r["amount"])}</div>'
        f'<div class="rate-c">{esc(r["currency"])}</div>'
        f'<div class="rate-x">{esc(r["vat_he"])}</div>'
        "</div>"
        f'<div class="rate-u">{bidi(r["unit_he"])}</div>'
        "</div>"
        f'<div class="trks">{"".join(cards)}</div>'
        f'<div class="cm-note">{bidi(c["bottom_he"])}</div>'
        "</div>"
    )


def block_steps(d: dict) -> str:
    """Four filled steps. The last is a destination rather than a preparation,
    so it is the one that inverts."""
    cells = "".join(
        f'<div class="sp sp-{i}"><div class="sp-n" dir="ltr">{esc(s["n"])}</div>'
        f'<div class="sp-t">{bidi(s["t"])}</div></div>'
        for i, s in enumerate(d["steps"], 1)
    )
    return f'<div class="steps">{cells}</div>'


BLOCKS = {
    "arc": block_arc,
    "about": block_about,
    "proof": block_proof,
    "flow": block_flow,
    "flowfoot": block_flowfoot,
    "options": block_options,
    "questions": block_questions,
    "commercial": block_commercial,
    "steps": block_steps,
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
        f'  <p class="ft">{esc(d["web"]["footnote_he"])} {esc(d["web"]["note_he"])}</p>\n'
        "</div>\n"
        f"<script>{SHELL_JS}</script>\n"
    )
    WEB_OUT.write_text(page, encoding="utf-8")
    print(f"       web -> {WEB_OUT.relative_to(ROOT)} "
          f"({len(page.encode('utf-8')) / 1024:.0f} KB, {n_pages} stages)")
    return 0


def main() -> int:
    d = json.loads(DATA.read_text(encoding="utf-8"))

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
    return build_web(html, d, n_pages)


if __name__ == "__main__":
    raise SystemExit(main())
