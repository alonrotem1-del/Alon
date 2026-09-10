#!/usr/bin/env node
/**
 * qa/extract.js — walks the rendered deck and emits geometric primitives for the
 * PowerPoint build. Text stays text, tables stay tables, shapes stay shapes:
 * nothing here rasterises a slide.
 *
 * Writes dist/deck_extract.json.
 *
 * The HTML is set in Frank Ruhl Libre + Assistant, neither of which the
 * recipient is guaranteed to have. The PPTX is therefore written in Times New
 * Roman + Arial, which do carry Hebrew on both Windows and macOS. Every block is
 * measured here against Liberation Serif / Liberation Sans — metric stand-ins for
 * those two — so build_pptx.py can size each text frame for the face it names.
 */

const path = require('path');
const fs = require('fs');
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const ROOT = path.resolve(__dirname, '..');
const DECK = path.join(ROOT, 'dist', 'deck.html');
const OUT = path.join(ROOT, 'dist', 'deck_extract.json');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto('file://' + DECK + '?flat=1', { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(200);

  const data = await page.evaluate(() => {
    const BLOCKISH = ['block', 'flex', 'grid', 'list-item', 'table', 'flow-root'];

    const hex = (c) => {
      if (!c) return null;
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(',').map((v) => parseFloat(v));
      if (p.length > 3 && p[3] === 0) return null; // fully transparent
      return '#' + p.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('').toUpperCase();
    };

    /* hidden probe used to re-measure a text block in Arial metrics */
    const probe = document.createElement('div');
    probe.style.cssText =
      'position:absolute;left:-99999px;top:0;visibility:hidden;white-space:normal;';
    document.body.appendChild(probe);

    /* Which of the two faces is this element set in? The stack's FIRST family is
       the one in use; testing the whole string would match the "sans-serif"
       fallback and mark every run as serif. */
    const isSerifFace = (cs) => {
      const first = (cs.fontFamily || '').split(',')[0].replace(/["']/g, '').trim().toLowerCase();
      return /frank ruhl|times|georgia/.test(first);
    };

    const nowrap = document.createElement('div');
    nowrap.style.cssText =
      'position:absolute;left:-99999px;top:0;visibility:hidden;white-space:nowrap;display:inline-block;';
    document.body.appendChild(nowrap);

    /* width this block needs to stay on a single line, in Arial metrics */
    const arialNowrapW = (el) => {
      const cs = getComputedStyle(el);
      var fam = isSerifFace(cs)
        ? "'Liberation Serif', 'Times New Roman', serif" : "'Liberation Sans', Arial, sans-serif";
      nowrap.style.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize}/${cs.lineHeight} ${fam}`;
      nowrap.style.letterSpacing = cs.letterSpacing;
      nowrap.style.direction = cs.direction;
      nowrap.innerHTML = el.innerHTML;
      return nowrap.getBoundingClientRect().width;
    };

    const arialHeight = (el, widthPx) => {
      const cs = getComputedStyle(el);
      probe.style.width = widthPx + 'px';
      var fam2 = isSerifFace(cs)
        ? "'Liberation Serif', 'Times New Roman', serif" : "'Liberation Sans', Arial, sans-serif";
      probe.style.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize}/${cs.lineHeight} ${fam2}`;
      probe.style.letterSpacing = cs.letterSpacing;
      probe.style.direction = cs.direction;
      probe.style.textAlign = cs.textAlign;
      probe.innerHTML = el.innerHTML;
      return probe.getBoundingClientRect().height;
    };

    const isInline = (el) => !BLOCKISH.includes(getComputedStyle(el).display);

    /* a text block owns text and has no block-level children */
    const isTextBlock = (el) => {
      if (!el.textContent.trim()) return false;
      for (const c of el.children) if (!isInline(c)) return false;
      return true;
    };

    /* flatten inline content into styled runs, preserving order */
    const runsOf = (el) => {
      const out = [];
      const walk = (node, styleEl) => {
        for (const n of node.childNodes) {
          if (n.nodeType === 3) {
            const t = n.textContent.replace(/\s+/g, ' ');
            if (!t.trim()) {
              if (out.length && t === ' ') out.push({ t: ' ', style: styleEl });
              continue;
            }
            out.push({ t, style: styleEl });
          } else if (n.nodeType === 1) {
            walk(n, n);
          }
        }
      };
      walk(el, el);
      return out
        .map((r) => {
          const cs = getComputedStyle(r.style);
          return {
            t: r.t,
            size: parseFloat(cs.fontSize),
            bold: parseInt(cs.fontWeight, 10) >= 600,
            color: hex(cs.color) || '#000000',
            // Frank Ruhl Libre -> Times New Roman, Assistant -> Arial in the PPTX
            serif: isSerifFace(cs),
            // mirrors unicode-bidi:isolate on .ltr / .num — the PPTX writer
            // re-applies it with Unicode isolate marks, so a numeric range is
            // never reordered into "13,000 - 9,000" inside an RTL paragraph
            ltr: cs.direction === 'ltr',
          };
        })
        .filter((r) => r.t.length);
    };

    const slides = [...document.querySelectorAll('section.slide')];

    return {
      canvas: { w: 1920, h: 1080 },
      slides: slides.map((slide, i) => {
        const sr = slide.getBoundingClientRect();
        const items = [];
        /* Once a block is emitted as text, its inline descendants are already
           carried as runs. Emitting them again stacks a second text box on top
           of the first — which is how "9,000 - 13,000" ended up drawn twice,
           overlapping, in the PowerPoint. */
        const emittedText = new Set();
        const insideEmittedText = (el) => {
          for (let p = el.parentElement; p && p !== slide; p = p.parentElement) {
            if (emittedText.has(p)) return true;
          }
          return false;
        };
        const rel = (r) => ({
          x: r.left - sr.left,
          y: r.top - sr.top,
          w: r.width,
          h: r.height,
        });

        /* DOM order == PowerPoint z-order, so ancestors (backgrounds) land first */
        for (const el of slide.querySelectorAll('*')) {
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden') continue;
          const r = el.getBoundingClientRect();
          if (r.width < 0.5 || r.height < 0.5) continue;
          const g = rel(r);

          if (el.tagName === 'IMG') {
            items.push({ kind: 'image', ...g, src: el.currentSrc || el.src });
            continue;
          }

          if (el.tagName === 'TABLE') {
            const rows = [...el.rows].map((tr) =>
              [...tr.cells].map((td) => ({
                text: td.innerText.trim(),
                bold: parseInt(getComputedStyle(td).fontWeight, 10) >= 600,
                size: parseFloat(getComputedStyle(td).fontSize),
                color: hex(getComputedStyle(td).color) || '#000000',
                align: getComputedStyle(td).textAlign,
              }))
            );
            items.push({ kind: 'table', ...g, rows });
            continue;
          }

          /* shape: a visible fill and/or a visible border */
          const fill = hex(cs.backgroundColor);
          const bw = parseFloat(cs.borderTopWidth) || 0;
          const bc = hex(cs.borderTopColor);
          const uniformBorder =
            bw > 0 &&
            cs.borderTopWidth === cs.borderRightWidth &&
            cs.borderTopWidth === cs.borderBottomWidth &&
            cs.borderTopWidth === cs.borderLeftWidth &&
            cs.borderTopStyle !== 'none';

          if (fill || uniformBorder) {
            items.push({
              kind: 'rect',
              ...g,
              fill,
              stroke: uniformBorder ? { color: bc, width: bw } : null,
              radius: parseFloat(cs.borderTopLeftRadius) || 0,
            });
          }

          /* a border on one edge only (rules/dividers) becomes its own thin bar */
          const edges = [
            ['Top', 'borderTopWidth', 'borderTopColor'],
            ['Bottom', 'borderBottomWidth', 'borderBottomColor'],
            ['Left', 'borderLeftWidth', 'borderLeftColor'],
            ['Right', 'borderRightWidth', 'borderRightColor'],
          ];
          if (!uniformBorder) {
            for (const [side, wProp, cProp] of edges) {
              const w = parseFloat(cs[wProp]) || 0;
              if (w <= 0 || cs['border' + side + 'Style'] === 'none') continue;
              const col = hex(cs[cProp]);
              if (!col) continue;
              const bar =
                side === 'Top' ? { x: g.x, y: g.y, w: g.w, h: w }
                : side === 'Bottom' ? { x: g.x, y: g.y + g.h - w, w: g.w, h: w }
                : side === 'Left' ? { x: g.x, y: g.y, w: w, h: g.h }
                : { x: g.x + g.w - w, y: g.y, w: w, h: g.h };
              items.push({ kind: 'rect', ...bar, fill: col, stroke: null, radius: 0 });
            }
          }

          /* text */
          if (isTextBlock(el) && !insideEmittedText(el)) {
            const runs = runsOf(el);
            if (!runs.length) continue;
            const pl = parseFloat(cs.paddingLeft) || 0;
            const pr = parseFloat(cs.paddingRight) || 0;
            const pt = parseFloat(cs.paddingTop) || 0;
            const bl = parseFloat(cs.borderLeftWidth) || 0;
            const br = parseFloat(cs.borderRightWidth) || 0;
            const bt = parseFloat(cs.borderTopWidth) || 0;
            const innerW = g.w - pl - pr - bl - br;
            const innerX = g.x + bl + pl;
            const innerY = g.y + bt + pt;
            const innerH = g.h - bt - pt - (parseFloat(cs.paddingBottom) || 0) - (parseFloat(cs.borderBottomWidth) || 0);

            let align = cs.textAlign;
            if (align === 'start' || align === 'justify') align = cs.direction === 'rtl' ? 'right' : 'left';
            if (align === 'end') align = cs.direction === 'rtl' ? 'left' : 'right';

            /* inner width of the nearest ancestor that is actually drawn */
            let containerW = 1920 - 176; // slide content width as the fallback
            for (let a = el; a && a !== slide; a = a.parentElement) {
              const acs = getComputedStyle(a);
              const hasFill = hex(acs.backgroundColor);
              const hasBorder = (parseFloat(acs.borderTopWidth) || 0) > 0 && acs.borderTopStyle !== 'none';
              if (a !== el && (hasFill || hasBorder)) {
                const ar = a.getBoundingClientRect();
                containerW = ar.width
                  - (parseFloat(acs.paddingLeft) || 0) - (parseFloat(acs.paddingRight) || 0)
                  - (parseFloat(acs.borderLeftWidth) || 0) - (parseFloat(acs.borderRightWidth) || 0);
                break;
              }
            }

            let lh = parseFloat(cs.lineHeight);
            if (!isFinite(lh)) lh = parseFloat(cs.fontSize) * 1.2;

            items.push({
              kind: 'text',
              x: innerX, y: innerY, w: innerW, h: innerH,
              align,
              rtl: cs.direction === 'rtl',
              lineHeight: lh,
              runs,
              arialH: arialHeight(el, innerW),
              nowrapW: arialNowrapW(el),
              containerW,
            });
            emittedText.add(el);
          }
        }

        // the slide's own fill is never emitted as a shape (the walk starts at
        // its children), so carry it out for build_pptx.py to paint
        return { n: i + 1, id: slide.id, title: slide.dataset.title || '',
                 bg: hex(getComputedStyle(slide).backgroundColor) || '#FFFFFF', items };
      }),
    };
  });

  await browser.close();
  fs.writeFileSync(OUT, JSON.stringify(data, null, 1));

  const counts = {};
  const tight = [];
  for (const s of data.slides) {
    for (const it of s.items) {
      counts[it.kind] = (counts[it.kind] || 0) + 1;
      if (it.kind !== 'text') continue;
      const lines = it.lineHeight > 0 ? Math.round(it.h / it.lineHeight) : 1;
      // A single-line block with almost no spare width is one metric nudge away
      // from wrapping on the recipient's machine, where the real Arial lives.
      // build_pptx.py widens a single-line box to fit, so the question is not
      // whether the box is tight but whether the text would spill out of the
      // container it is drawn on once the recipient's real Arial is used.
      if (lines <= 1 && it.nowrapW > 0 && it.containerW > 0) {
        const headroom = (it.containerW - it.nowrapW) / it.nowrapW;
        if (headroom < 0.04) {
          tight.push({ slide: s.n, headroom, text: it.runs.map((r) => r.t).join('').slice(0, 46) });
        }
      }
    }
  }
  console.log(`extract -> ${path.relative(ROOT, OUT)}`);
  console.log(`  slides: ${data.slides.length}`);
  console.log(`  items : ${Object.entries(counts).map(([k, v]) => `${k}=${v}`).join('  ')}`);
  console.log(`  single-line blocks with <4% spare width inside their container: ${tight.length}`);
  for (const t of tight) {
    console.log(`    slide ${t.slide}  headroom ${(t.headroom * 100).toFixed(1)}%  "${t.text}"`);
  }

  /* Negative headroom means the line is already wider than its container in
     Arial. build_pptx.py caps the box at the container so the text wraps
     instead of overprinting its neighbour — but a line that wraps in the PPTX
     and not in the PDF is a difference between the two deliverables, so it
     fails the build rather than being noted and forgotten. */
  const spill = tight.filter((t) => t.headroom < 0);
  if (spill.length) {
    console.error(`\nFAIL: ${spill.length} single-line block(s) do not fit their container in Arial;`);
    console.error('      they would wrap in the PPTX but not in the PDF. Shorten the string or');
    console.error('      step the size down one stop in the type scale.');
    process.exit(1);
  }
})().catch((e) => { console.error(e); process.exit(2); });
