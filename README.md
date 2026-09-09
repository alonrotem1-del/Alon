# מצגת פתיחה — בחינת היתכנות אסטרטגית וכלכלית

Executive deck (Hebrew, RTL, 8 slides) for the kickoff between Alon Rotem and
the founders of a vertical CRM / client portal for the DJ & events industry.

The design surface is HTML and CSS. Deliverables in `dist/`: **deck.html**
(one self-contained file) and **deck.pdf** (one page per slide), plus
`screenshots/slide-N.png`.

## Build

```bash
bash make.sh
```

| # | stage | what it does |
|---|-------|--------------|
| 1 | `build.py` | `deck_template.html` + `data/deck_data.json` → `dist/deck.html`; substitutes every figure from JSON, **computes** derived figures (ratios, chart scales, bar widths), inlines fonts and the photo as data URIs, auto-numbers the pages |
| 2 | `qa/render.js` | the QA gate; also writes the screenshots, `dist/deck.pdf` and `dist/deck_text.json` |
| 3 | `verify_figures.py` | reconciles every number visible on a slide against the source data |

`node qa/probe.js <slide> <selector>...` prints measured top/bottom/height for
any block. Every layout decision in this deck was made from those numbers.

## Canvas and print

Each slide is a `<section class="slide">` fixed at 1920 × 1080 px. The PDF is
printed at exactly 1920 × 1080 px per page with zero margin, so it is
pixel-identical to the screen (verified: 1440 × 810 pt = 1920 × 1080 CSS px,
all pages the same size, text selectable).

## Layout discipline

Blocks are positioned absolutely from shared constants, so every slide shares a
side margin, a header baseline, a content band and a footer:

```
--m:120px  --w:1680px   --kick-y:92  --head-y:136  --sub-y:298
--band-y:392  --band-h:508  --rule-y:946  --foot-y:964
```

Inside a block, layout is flex or grid with `gap` — never a stack of
per-element margins. The harness enforces the shared edge: every header, band
and footer element must begin at x = 1800 (1920 − 120), to within half a pixel.

## Type

**Frank Ruhl Libre** (Hebrew serif) carries headlines and oversized numerals;
**Assistant** (Hebrew sans) carries body, tables, chart labels and every figure.
Both are loaded from Google Fonts, inlined as base64, with real fallback stacks.

Eleven scale steps, all of them used, and **no raw `font-size` anywhere outside
the scale definition**. Floors: substantive text ≥ 24px (12pt); captions,
sources, axis text and short labels ≥ 20px (10pt). The caption class is an
explicit list in the harness, so nothing slips under the floor by being quietly
relabelled.

## Colour

One primary (`--p-900 #0B2233`), one accent spent sparingly (`--accent #BF4B22`),
and a neutral ramp carrying a slight blue bias toward the primary. Semantic
tokens (`--pos`, `--cau`, `--neg`) are defined separately from the accent.
No logo, no company branding.

## Component vocabulary

Table (header band in the primary, white hairline separators, no grid) · tile
with a single accent edge · big-number tile · small multiples · chip · numbered
rows separated by a hairline rather than boxed. Border, fill and radius are
spent by role — the discussion rows and the credential rows are deliberately
*not* cards.

## Charts

Pure HTML and CSS, no library. Bars are divs whose widths `build.py` computes
from the source data; grid lines are absolutely positioned rules; value labels
sit in a reserved 196px gutter so they can never overflow the plot. The plot
runs `direction:ltr` so values ascend left to right even though the deck is
RTL — but Hebrew series labels get their own `direction:rtl` back, or their
geresh lands on the wrong side.

## What the QA gate checks

Per slide, to zero issues: content past the slide edge, elements outside their
containing block (using the *offset parent* for absolutely positioned
elements), clipped text, any font below the floor, footer collisions,
block-level siblings overlapping, chart marks outside their plot area, and
blocks that should share a starting edge but do not.

## Source of truth

`deck_template.html` is the only hand-authored layout file. `dist/*` is
generated. Every figure comes from `data/deck_data.json`, whose `_provenance`
block records where each fact came from and which conflicts are deliberately
left unreconciled. `verify_figures.py` fails the build if a number appears on a
slide that cannot be derived from that file, or if a source figure never
reaches a slide.

## Not in the build

`qa/extract.js` and `qa/build_pptx.py` export a real editable PowerPoint. They
still run, but they are no longer part of `make.sh`: the design surface is HTML
and CSS, and a PPTX cannot reproduce this layout without compromising it.
