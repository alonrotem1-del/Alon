#!/usr/bin/env bash
# make.sh — the whole pipeline, in order. Any stage failing stops the build.
#
#   1. build.py           deck_template.html + deck_data.json -> dist/deck.html
#                         (+ dist/deck_web.html, the hosted-page variant)
#   2. qa/render.js       QA gate (slide overflow, container escapes, clipped
#                         text, font floor, footer collisions, sibling overlap,
#                         chart overflow, shared-edge alignment)
#                         + screenshots/slide-N.png + dist/deck.pdf
#   3. verify_figures.py  every rendered number reconciled against source data
#   4. qa/extract.js      rendered DOM -> geometric primitives
#   5. qa/build_pptx.py   dist/deck.pptx — real editable PowerPoint
#   6. qa/render_pptx.sh  renders the PPTX so it can be inspected separately
set -euo pipefail
cd "$(dirname "$0")"

echo "── 1/6  build ─────────────────────────────────────────────────────────"
python3 build.py
echo; echo "── 2/6  QA gate ───────────────────────────────────────────────────────"
node qa/render.js
echo; echo "── 3/6  figure verification ───────────────────────────────────────────"
python3 verify_figures.py
echo; echo "── 4/6  extract ───────────────────────────────────────────────────────"
node qa/extract.js
echo; echo "── 5/6  pptx ──────────────────────────────────────────────────────────"
python3 qa/build_pptx.py
echo; echo "── 6/6  pptx render ───────────────────────────────────────────────────"
bash qa/render_pptx.sh
echo; echo "ALL STAGES PASSED"
