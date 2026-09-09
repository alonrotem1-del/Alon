# מצגת פתיחה — בחינת היתכנות אסטרטגית וכלכלית

Executive deck (Hebrew, RTL, 5 slides) for the kickoff between Alon Rotem and
the founders of a vertical CRM / client portal for the DJ & events industry.

Deliverables live in `dist/`: **deck.pptx** (real editable PowerPoint),
**deck.pdf**, and **deck.html** (a single self-contained file).

## Build

```bash
bash make.sh
```

Six stages, any failure stops the build:

| # | stage | what it does |
|---|-------|--------------|
| 1 | `build.py` | `deck_template.html` + `data/deck_data.json` → `dist/deck.html`; substitutes every figure from JSON, inlines images as base64, auto-numbers the pages |
| 2 | `qa/render.js` | the QA gate; also writes `screenshots/slide-N.png` and `dist/deck.pdf` |
| 3 | `qa/extract.js` | walks the rendered DOM → `dist/deck_extract.json` (text runs, shapes, tables, images with absolute geometry) |
| 4 | `verify_figures.py` | reconciles every number painted on a slide against the source data |
| 5 | `qa/build_pptx.py` | `dist/deck.pptx` — text stays text, shapes stay shapes, no slide images |
| 6 | `qa/render_pptx.sh` | renders the PPTX via LibreOffice so it can be inspected separately from the HTML |

`node qa/probe.js <slide> <selector>...` prints measured top/bottom/height for
any block — layout changes are made from measured numbers, not guesses.

## Source of truth

`deck_template.html` is the only hand-authored layout file. `dist/*` is
generated and must never be hand-edited. Every figure and every string that
appears on a slide comes from `data/deck_data.json`, whose `_provenance` block
records where each fact came from and which conflicts are deliberately left
unreconciled.

Drop a photo at `assets/portrait.jpg` and `build.py` inlines it automatically;
with no photo present the slide falls back to a monogram rather than a stock face.

## What the QA gate checks

Per slide, to zero issues: content overflowing the slide, elements escaping
their container, clipped text, any font below the floor, footer collisions,
block-level siblings overlapping, and — for the side-by-side comparison — rows
that are supposed to share a baseline drifting apart.

**Type floor.** Substantive text ≥ 24px (12pt). Only page furniture, the VAT
footnote and the small English glosses sit in the 20–23px band, and the harness
enforces exactly that list rather than trusting the design.

## Geometry

1920 × 1080 px canvas. 1920px = 13.333in → **6350 EMU per pixel**, **1px =
0.5pt**. The PDF is printed at the same 13.333 × 7.5in as the PPTX, so both
deliverables are the same physical size. All autofit is stripped from the saved
PowerPoint package so it never silently rescales the type.

## Typeface

The whole deck is set in **Arial**. It is the only sans face guaranteed to carry
Hebrew on both Windows and macOS, so the PowerPoint renders correctly on the
recipient's machine. Setting the HTML in the same face keeps `deck.html`,
`deck.pdf` and `deck.pptx` metrically consistent — a nicer webfont would have
made the PDF roughly 14% narrower than the PowerPoint the client actually opens.
