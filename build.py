#!/usr/bin/env python3
"""
build.py — renders deck_template.html + data/deck_data.json into dist/deck.html.

What it does, and why:
  * substitutes {{dotted.path}} tokens from the JSON, so no figure is ever typed
    by hand into the markup;
  * expands {{BLOCK:name}} regions from the JSON (phases, alternatives, ...);
  * inlines fonts and images as base64 data URIs, so dist/deck.html is a single
    self-contained file that renders identically anywhere;
  * auto-numbers the pages by injecting a footer into every <section class="slide">.

deck_template.html is the only file authored by hand. dist/deck.html is generated
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


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def num(n: int) -> str:
    """Thousands-separated integer, derived from the JSON value (never typed)."""
    return f"{int(n):,}"


def rng(lo, hi) -> str:
    """An LTR-isolated numeric range, so bidi never reorders it inside Hebrew."""
    return f'<span class="ltr">{lo}–{hi}</span>'


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
    mime = mime or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


# --------------------------------------------------------------------------- #
# block builders — every figure below comes from deck_data.json
# --------------------------------------------------------------------------- #
def block_portrait(d: dict) -> str:
    for name in PORTRAIT_CANDIDATES:
        p = ROOT / "assets" / name
        if p.exists():
            # real photograph supplied by Alon; build.py inlines it
            return (
                f'<div class="portrait"><img src="assets/{name}" '
                f'alt="{esc(d["bio"]["name_he"])}"></div>'
            )
    # No photograph supplied. We do not substitute a stock or generated face —
    # a monogram stands in until a real portrait is dropped into assets/.
    initials = "".join(w[0] for w in d["bio"]["name_he"].split()[:2])
    return f'<div class="portrait"><div class="mono">{esc(initials)}</div></div>'


def block_creds(d: dict) -> str:
    out = []
    for i, c in enumerate(d["bio"]["credentials"]):
        first = " first" if i == 0 else ""
        out.append(
            f'<div class="cred{first}">'
            f'<div class="cred-k">{esc(c["label_he"])}</div>'
            f'<div class="cred-v">{esc(c["value_he"])}</div>'
            f"</div>"
        )
    return '<div class="creds">' + "".join(out) + "</div>"


def block_callout(d: dict) -> str:
    """Emphasise the key phrase without duplicating the sentence in the markup."""
    text = d["bio"]["callout_he"]
    key = "Devil's Advocate חיובי"
    if key in text:
        head, tail = text.split(key, 1)
        return f"{esc(head)}<b>{esc(key)}</b>{esc(tail)}"
    return esc(text)


def block_phases(d: dict) -> str:
    cards = []
    for i, ph in enumerate(d["phases"]):
        bullets = []
        for j, b in enumerate(ph["bullets"]):
            last = " last" if j == len(ph["bullets"]) - 1 else ""
            bullets.append(
                f'<div class="bul{last}">'
                f'<div class="bul-dot"></div>'
                f"<div>"
                f'<div class="bul-h">{esc(b["head_he"])}</div>'
                f'<div class="bul-b">{esc(b["body_he"])}</div>'
                f"</div></div>"
            )
        hi = " phase-1" if i == 0 else ""
        cards.append(
            f'<div class="phase{hi}">'
            f'<div class="phase-top">'
            f'<div class="phase-num num">{esc(ph["index"])}</div>'
            f'<div class="phase-titles">'
            f'<div class="phase-chip">{esc(ph["letter_he"])}</div>'
            f'<div class="phase-t">{esc(ph["title_he"])}</div>'
            f'<div class="phase-t-en">{esc(ph["title_en"])}</div>'
            f"</div></div>"
            f'<div class="phase-sep"></div>'
            + "".join(bullets)
            + "</div>"
        )
    # first phase sits on the right in RTL reading order; the arrow points from
    # phase 01 to phase 02 so the sequence is unambiguous either way.
    arrow = '<div class="flow"><div class="flow-arrow">&#10229;</div></div>'
    return cards[0] + arrow + cards[1]


def block_alts(d: dict) -> str:
    cards = []
    for alt in d["alternatives"]:
        hi = alt.get("highlighted", False)

        chips = []
        if "sessions_min" in alt:
            chips.append(f'<span class="chip">{rng(alt["sessions_min"], alt["sessions_max"])} מפגשי עבודה</span>')
        chips.append(f'<span class="chip">{rng(alt["hours_min"], alt["hours_max"])} שעות עבודה</span>')
        chips.append(f'<span class="chip">{rng(alt["weeks_min"], alt["weeks_max"])} שבועות</span>')

        scope_extra = ""
        if alt.get("scope_extra_he"):
            scope_extra = f'<div class="row-v" style="margin-bottom:12px">{esc(alt["scope_extra_he"])}</div>'

        dls = []
        for j, t in enumerate(alt["deliverables_he"]):
            first = " first" if j == 0 else ""
            dls.append(
                f'<div class="dl{first}"><div class="dl-dot"></div>'
                f'<div class="dl-t">{esc(t)}</div></div>'
            )

        fee_txt = f'{num(alt["fee_min"])} – {num(alt["fee_max"])}'
        cards.append(
            f'<div class="alt{" alt-hi" if hi else ""}">'
            f'<div class="alt-band{" alt-band-hi" if hi else ""}" data-row="band">'
            f'<div class="alt-num num">{esc(alt["index"])}</div>'
            f'<div class="alt-titles">'
            f'<div class="alt-t">\u05d7\u05dc\u05d5\u05e4\u05d4 {esc(alt["letter_he"])} \u2014 {esc(alt["name_he"])}</div>'
            f'<div class="alt-t-en">{esc(alt["name_en"])}</div>'
            f"</div></div>"
            f'<div class="row" data-row="goal"><div class="row-k">\u05de\u05d8\u05e8\u05d4</div>'
            f'<div class="row-v">{esc(alt["goal_he"])}</div></div>'
            f'<div class="row" data-row="scope"><div class="row-k">\u05d4\u05d9\u05e7\u05e3</div>'
            f'{scope_extra}<div class="chips">{"".join(chips)}</div></div>'
            f'<div class="row row-last" data-row="deliverables">'
            f'<div class="row-k">\u05ea\u05d5\u05e6\u05e8\u05d9\u05dd</div>{"".join(dls)}</div>'
            f'<div class="fee{" fee-hi" if hi else ""}" data-row="fee">'
            f'<div class="fee-k">\u05d4\u05e9\u05e7\u05e2\u05d4</div>'
            f'<div class="fee-right">'
            f'<div class="fee-num"><span class="ltr">{fee_txt}</span> {esc(alt["currency"])}</div>'
            f'<div class="fee-vat">{esc(alt["vat_he"])}</div>'
            f"</div></div></div>"
        )
    return "".join(cards)


def block_questions(d: dict) -> str:
    out = []
    for q in d["discussion"]:
        out.append(
            f'<div class="q">'
            f'<div class="q-num num">{esc(q["index"])}</div>'
            f'<div class="q-tag">{esc(q["tag_he"])}</div>'
            f'<div class="q-sep"></div>'
            f'<div class="q-txt">{esc(q["q_he"])}</div>'
            f"</div>"
        )
    return "".join(out)


def block_next(d: dict) -> str:
    """The banner chip already reads 'הצעד הבא', so drop the duplicate prefix."""
    text = d["next_step_he"]
    prefix = "הצעד הבא:"
    if text.startswith(prefix):
        text = text[len(prefix):].strip()
    return esc(text)


BLOCKS = {
    "portrait": block_portrait,
    "creds": block_creds,
    "callout": block_callout,
    "phases": block_phases,
    "alts": block_alts,
    "questions": block_questions,
    "next": block_next,
}


# --------------------------------------------------------------------------- #
# pipeline stages
# --------------------------------------------------------------------------- #
def expand_blocks(html: str, d: dict) -> str:
    def sub(m):
        name = m.group(1)
        if name not in BLOCKS:
            raise KeyError(f"unknown {{{{BLOCK:{name}}}}}")
        return BLOCKS[name](d)

    return re.sub(r"\{\{BLOCK:([a-z_]+)\}\}", sub, html)


def expand_tokens(html: str, d: dict) -> str:
    def sub(m):
        return esc(dotted(d, m.group(1)))

    return re.sub(r"\{\{([a-z_]+(?:\.[a-z0-9_]+)*)\}\}", sub, html, flags=re.IGNORECASE)


def inline_assets(html: str) -> tuple[str, int]:
    """Replace url('assets/...') and src="assets/..." with base64 data URIs."""
    count = 0

    def repl(m):
        nonlocal count
        quote, rel = m.group("q"), m.group("path")
        p = ROOT / rel
        if not p.exists():
            raise FileNotFoundError(f"asset referenced but missing: {rel}")
        count += 1
        return f"{m.group('pre')}{quote}{data_uri(p)}{quote}"

    html = re.sub(
        r"(?P<pre>url\()(?P<q>['\"])(?P<path>assets/[^'\"]+)(?P=q)",
        repl,
        html,
    )
    html = re.sub(
        r'(?P<pre>src=)(?P<q>")(?P<path>assets/[^"]+)(?P=q)',
        repl,
        html,
    )
    return html, count


def number_pages(html: str) -> tuple[str, int]:
    """Inject the auto-numbered footer just before each slide's </section>."""
    titles = re.findall(r'<section class="slide"[^>]*data-title="([^"]*)"', html)
    total = len(titles)

    parts = re.split(r"(</section>)", html)
    out, n = [], 0
    for chunk in parts:
        if chunk == "</section>" and n < total:
            out.append(
                '  <div class="foot">'
                f'<div class="foot-txt">{esc(titles[n])}</div>'
                '<div class="foot-line"></div>'
                f'<div class="foot-pg num">{n + 1} / {total}</div>'
                "</div>\n"
            )
            n += 1
        out.append(chunk)
    return "".join(out), total


def main() -> int:
    if not TEMPLATE.exists():
        print(f"ERROR: missing {TEMPLATE}", file=sys.stderr)
        return 1

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

    kb = len(html.encode("utf-8")) / 1024
    print(f"build: {n_pages} slides, {n_assets} assets inlined, {kb:.0f} KB -> {OUT.relative_to(ROOT)}")
    print("       open with ?flat=1 for automation (exact 1920x1080 blocks, no page chrome)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
