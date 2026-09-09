#!/usr/bin/env bash
# qa/render_pptx.sh — renders dist/deck.pptx the way a recipient would see it.
#
# CSS features such as box-shadow and ::before borders do not survive the export,
# and PowerPoint's z-order follows DOM order rather than CSS stacking, so the
# PPTX has to be looked at separately from the HTML. LibreOffice Impress opens
# the real package and prints it; the result is rasterised for inspection.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/screenshots/pptx}"

rm -rf "$OUT"; mkdir -p "$OUT"
soffice --headless --norestore --convert-to pdf --outdir "$OUT" "$ROOT/dist/deck.pptx" >/dev/null 2>&1

python3 - "$OUT" <<'PY'
import sys, pathlib, pymupdf
out = pathlib.Path(sys.argv[1])
doc = pymupdf.open(out / 'deck.pdf')
w, h = doc[0].rect[2], doc[0].rect[3]
for i, page in enumerate(doc):
    page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(out / f'pptx-slide-{i+1}.png')
print(f'pptx render: {doc.page_count} pages at {w:.0f}x{h:.0f}pt '
      f'({w/72:.3f}x{h/72:.3f}in) -> {out}/pptx-slide-N.png')
PY
