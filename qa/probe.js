#!/usr/bin/env node
/**
 * qa/probe.js — measurement probe.
 *
 * Prints the measured slide-relative top / bottom / height of selected blocks so
 * layout changes are made from real numbers instead of guesses.
 *
 *   node qa/probe.js 4 ".s-head" ".alts" ".alt" ".alt-band" ".alt-body" ".row" ".fee"
 *   node qa/probe.js 4              # defaults to every direct child of the slide
 */

const path = require('path');
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const DECK = path.join(path.resolve(__dirname, '..'), 'dist', 'deck.html');
const slideNo = parseInt(process.argv[2] || '1', 10);
const selectors = process.argv.slice(3);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto('file://' + DECK + '?flat=1', { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);

  const rows = await page.evaluate(({ slideNo, selectors }) => {
    const slide = document.querySelectorAll('section.slide')[slideNo - 1];
    if (!slide) return null;
    const sr = slide.getBoundingClientRect();
    const cs = getComputedStyle(slide);
    const padTop = parseFloat(cs.paddingTop);
    const padBottom = parseFloat(cs.paddingBottom);

    const targets = selectors.length
      ? selectors.flatMap((sel) => [...slide.querySelectorAll(sel)].map((el) => ({ sel, el })))
      : [...slide.children].map((el) => ({ sel: el.className || el.tagName, el }));

    const foot = slide.querySelector('.foot');
    const footTop = foot ? foot.getBoundingClientRect().top - sr.top : null;

    return {
      contentTop: padTop,
      contentBottom: sr.height - padBottom,
      footTop,
      rows: targets.map(({ sel, el }) => {
        const r = el.getBoundingClientRect();
        return {
          sel,
          cls: (el.className || '').toString().slice(0, 40),
          top: Math.round((r.top - sr.top) * 10) / 10,
          bottom: Math.round((r.bottom - sr.top) * 10) / 10,
          height: Math.round(r.height * 10) / 10,
          left: Math.round((r.left - sr.left) * 10) / 10,
          width: Math.round(r.width * 10) / 10,
        };
      }),
    };
  }, { slideNo, selectors });

  await browser.close();

  if (!rows) { console.error(`no slide ${slideNo}`); process.exit(1); }

  console.log(`\n=== PROBE: slide ${slideNo} (canvas 1920x1080) ===`);
  console.log(`content box: top ${rows.contentTop}  bottom ${rows.contentBottom}`);
  console.log(`footer top : ${rows.footTop}`);
  console.log('');
  console.log('selector'.padEnd(16) + 'class'.padEnd(24) + 'top'.padStart(8) + 'bottom'.padStart(9) + 'height'.padStart(9) + 'left'.padStart(8) + 'width'.padStart(8));
  console.log('-'.repeat(82));
  for (const r of rows.rows) {
    const over = r.bottom > rows.contentBottom ? '  <-- past content box' : '';
    console.log(
      String(r.sel).padEnd(16) + String(r.cls).padEnd(24) +
      String(r.top).padStart(8) + String(r.bottom).padStart(9) +
      String(r.height).padStart(9) + String(r.left).padStart(8) + String(r.width).padStart(8) + over
    );
  }
  console.log('');
})().catch((e) => { console.error(e); process.exit(2); });
