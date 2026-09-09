#!/usr/bin/env bash
# make.sh — the whole pipeline, in order. Any stage failing stops the build.
#
#   1. build.py           deck_template.html + deck_data.json -> dist/deck.html
#   2. qa/render.js       QA gate (slide overflow, container escapes, clipped
#                         text, font floor, footer collisions, sibling overlap,
#                         chart overflow, shared-edge alignment)
#                         + screenshots/slide-N.png + dist/deck.pdf
#   3. verify_figures.py  every rendered number reconciled against source data
#
# The PowerPoint exporter (qa/extract.js + qa/build_pptx.py) is kept in the repo
# but is no longer part of the build: the design surface is HTML and CSS, and
# the deliverables are deck.html, deck.pdf and the screenshots.
set -euo pipefail
cd "$(dirname "$0")"

echo "── 1/3  build ─────────────────────────────────────────────────────────"
python3 build.py
echo
echo "── 2/3  QA gate ───────────────────────────────────────────────────────"
node qa/render.js
echo
echo "── 3/3  figure verification ───────────────────────────────────────────"
python3 verify_figures.py
echo
echo "ALL STAGES PASSED"
