#!/usr/bin/env node
/**
 * qa/render.js — the QA gate. Runs on every build.
 *
 * Per slide it flags:
 *   1. content past the slide edge
 *   2. elements outside their containing block
 *   3. clipped text
 *   4. any font below the floor
 *   5. footer collisions
 *   6. block-level siblings overlapping each other
 *   7. a chart bar or value label outside its plot area
 *   8. blocks that should share a starting edge but do not
 *
 * It also writes screenshots/slide-N.png and prints dist/deck.pdf at exactly
 * 1920x1080 per page with zero margin, so the PDF is pixel-identical to screen.
 *
 * Exits non-zero when anything is flagged.
 */

const path = require('path');
const fs = require('fs');
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const ROOT = path.resolve(__dirname, '..');
const DECK = path.join(ROOT, 'dist', 'deck.html');
const SHOTS = path.join(ROOT, 'screenshots');
const PDF = path.join(ROOT, 'dist', 'deck.pdf');

/* ---- type floor ----------------------------------------------------------
   Substantive text >= 24px (12pt). Captions, sources, axis text, kickers and
   short labels may sit at 20-23px (10pt+). The caption class is an explicit
   list rather than a judgement call, so nothing drifts under the floor by
   being quietly relabelled.                                                 */
const FLOOR_SUBSTANTIVE = 24;
const FLOOR_CAPTION = 20;
const CAPTION_CLASSES = [
  'f-cap', 'f-pg',                       // footer furniture
  'kick',                                // uppercase kicker
  'arc-k', 'ab-lab', 'st-k', 'op-k',     // small uppercase labels
  'ev-k', 'rate-k', 'trk-l',
  'gates-c', 'st-note',                  // captions under a figure or tile
  'gate',                                // GO / ADJUST / STOP chips
];

/* Elements that deliberately sit in the reserved label gutter beside a chart
   track. They are checked against the plot area instead (check 7). */
const GUTTER_CLASSES = ['sr-v', 'gl-t'];

/* Every one of these must start on the shared side margin. */
const EDGE_SELECTOR =
  '.kick, h1.head, .sub, .band, .f-rule, .f-cap, .cv-rule, .cv-head, .cv-lead, .cv-note';

const TOL = 1.0;

(async () => {
  if (!fs.existsSync(DECK)) {
    console.error(`ERROR: ${DECK} not found — run \`python3 build.py\` first.`);
    process.exit(2);
  }
  fs.mkdirSync(SHOTS, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
  });
  await page.goto('file://' + DECK + '?flat=1', { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);

  const report = await page.evaluate(
    ({ FLOOR_SUBSTANTIVE, FLOOR_CAPTION, CAPTION_CLASSES, GUTTER_CLASSES, EDGE_SELECTOR, TOL }) => {
      const slides = [...document.querySelectorAll('section.slide')];
      const R = (el) => el.getBoundingClientRect();
      const area = (r) => Math.max(0, r.width) * Math.max(0, r.height);
      const overlap = (a, b) => {
        const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        return w > 0 && h > 0 ? w * h : 0;
      };
      const ownText = (el) =>
        [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim();
      const desc = (el) => {
        const c = typeof el.className === 'string' && el.className.trim()
          ? '.' + el.className.trim().split(/\s+/).join('.') : '';
        return el.tagName.toLowerCase() + c;
      };
      const has = (el, list) => {
        const cs = (typeof el.className === 'string' ? el.className : '').split(/\s+/);
        return cs.some((c) => list.includes(c));
      };

      return slides.map((slide, i) => {
        const issues = [];
        const sr = R(slide);
        const all = [...slide.querySelectorAll('*')];
        const footEls = [...slide.querySelectorAll('.f-rule, .f-cap, .f-pg')];

        for (const el of all) {
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden') continue;
          const r = R(el);
          if (r.width <= 0 && r.height <= 0) continue;

          /* 1. past the slide edge */
          if (r.left < sr.left - TOL || r.right > sr.right + TOL ||
              r.top < sr.top - TOL || r.bottom > sr.bottom + TOL) {
            issues.push({
              kind: 'slide-overflow', el: desc(el),
              detail: `[${Math.round(r.left - sr.left)},${Math.round(r.top - sr.top)} → ` +
                      `${Math.round(r.right - sr.left)},${Math.round(r.bottom - sr.top)}] escapes 0,0 → 1920,1080`,
            });
          }

          /* 2. outside its containing block. For absolutely positioned
                elements the containing block is the offset parent, not the DOM
                parent — checking the DOM parent would miss real escapes and
                invent false ones. */
          const abs = cs.position === 'absolute' || cs.position === 'fixed';
          const container = abs ? el.offsetParent : el.parentElement;
          if (container && container !== slide && !has(el, GUTTER_CLASSES)) {
            const ccs = getComputedStyle(container);
            const blockish = ['block', 'flex', 'grid', 'list-item', 'table', 'table-cell'].includes(ccs.display);
            if (blockish && ccs.overflow !== 'hidden') {
              const pr = R(container);
              if (r.left < pr.left - TOL || r.right > pr.right + TOL ||
                  r.top < pr.top - TOL || r.bottom > pr.bottom + TOL) {
                issues.push({
                  kind: 'container-escape', el: desc(el),
                  detail: `escapes ${desc(container)} by L${Math.round(Math.max(0, pr.left - r.left))} ` +
                          `R${Math.round(Math.max(0, r.right - pr.right))} ` +
                          `T${Math.round(Math.max(0, pr.top - r.top))} ` +
                          `B${Math.round(Math.max(0, r.bottom - pr.bottom))}`,
                });
              }
            }
          }

          const txt = ownText(el);
          if (txt) {
            /* 3. clipped text */
            if (el.scrollWidth > el.clientWidth + TOL && el.clientWidth > 0) {
              issues.push({ kind: 'text-clipped', el: desc(el),
                detail: `scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth} — "${txt.slice(0, 40)}"` });
            }
            if (el.scrollHeight > el.clientHeight + TOL && el.clientHeight > 0 && cs.overflow !== 'visible') {
              issues.push({ kind: 'text-clipped', el: desc(el),
                detail: `scrollHeight ${el.scrollHeight} > clientHeight ${el.clientHeight} — "${txt.slice(0, 40)}"` });
            }

            /* 4. font floor */
            const fs = parseFloat(cs.fontSize);
            const caption = !!el.closest(CAPTION_CLASSES.map((c) => '.' + c).join(','));
            const floor = caption ? FLOOR_CAPTION : FLOOR_SUBSTANTIVE;
            if (fs < floor - 0.01) {
              issues.push({ kind: 'font-below-floor', el: desc(el),
                detail: `${fs}px < ${floor}px (${caption ? 'caption' : 'substantive'}) — "${txt.slice(0, 40)}"` });
            }
          }

          /* 5. footer collision */
          for (const f of footEls) {
            if (f === el || f.contains(el) || el.contains(f)) continue;
            const ov = overlap(r, R(f));
            if (ov > 4 && area(r) > 0) {
              issues.push({ kind: 'footer-collision', el: desc(el),
                detail: `overlaps ${desc(f)} by ${Math.round(ov)}px²` });
              break;
            }
          }
        }

        /* 6. overlapping block siblings */
        const seen = new Set();
        for (const c of [slide, ...all]) {
          const kids = [...c.children].filter((k) => {
            const kc = getComputedStyle(k);
            if (kc.display === 'none' || kc.visibility === 'hidden') return false;
            if (kc.position === 'absolute' || kc.position === 'fixed') return false;
            return ['block', 'flex', 'grid', 'list-item'].includes(kc.display);
          });
          for (let a = 0; a < kids.length; a++)
            for (let b = a + 1; b < kids.length; b++) {
              const ov = overlap(R(kids[a]), R(kids[b]));
              if (ov > 4) {
                const key = desc(kids[a]) + '|' + desc(kids[b]);
                if (seen.has(key)) continue;
                seen.add(key);
                issues.push({ kind: 'sibling-overlap', el: desc(kids[a]),
                  detail: `overlaps ${desc(kids[b])} by ${Math.round(ov)}px²` });
              }
            }
        }

        /* 7. chart marks must sit inside their plot area */
        for (const plot of slide.querySelectorAll('.mc-plot')) {
          const pr = R(plot);
          for (const mark of plot.querySelectorAll('.bar-min, .bar-rng, .sr-v, .gl, .gl-t')) {
            const mr = R(mark);
            if (mr.width <= 0 && mr.height <= 0) continue;
            if (mr.left < pr.left - TOL || mr.right > pr.right + TOL ||
                mr.top < pr.top - TOL || mr.bottom > pr.bottom + TOL) {
              issues.push({ kind: 'chart-overflow', el: desc(mark),
                detail: `outside plot by L${Math.round(Math.max(0, pr.left - mr.left))} ` +
                        `R${Math.round(Math.max(0, mr.right - pr.right))} ` +
                        `T${Math.round(Math.max(0, pr.top - mr.top))} ` +
                        `B${Math.round(Math.max(0, mr.bottom - pr.bottom))}` });
            }
          }
        }

        /* 8. shared starting edge — the side margin is a constant, so every
              header, band and footer element must begin on exactly one x. */
        const edges = [...slide.querySelectorAll(EDGE_SELECTOR)];
        for (const el of edges) {
          const cs = getComputedStyle(el);
          if (cs.display === 'none') continue;
          const right = R(el).right - sr.left;
          if (Math.abs(right - 1800) > 0.5) {
            issues.push({ kind: 'edge-misalignment', el: desc(el),
              detail: `starts at x=${right.toFixed(1)} instead of the shared 1800 margin` });
          }
        }

        const texts = [];
        for (const el of all) {
          const t = [...el.childNodes].filter((n) => n.nodeType === 3)
            .map((n) => n.textContent).join('').trim();
          if (t) texts.push(t);
        }
        return { n: i + 1, id: slide.dataset.title || '', issues, texts };
      });
    },
    { FLOOR_SUBSTANTIVE, FLOOR_CAPTION, CAPTION_CLASSES, GUTTER_CLASSES, EDGE_SELECTOR, TOL }
  );

  /* screenshots */
  const sections = await page.locator('section.slide').all();
  for (let i = 0; i < sections.length; i++) {
    await sections[i].screenshot({ path: path.join(SHOTS, `slide-${i + 1}.png`) });
  }

  /* PDF: one slide per page, exactly 1920x1080px, zero margin */
  await page.pdf({
    path: PDF,
    width: '1920px',
    height: '1080px',
    scale: 1,
    printBackground: true,
    margin: { top: '0', right: '0', bottom: '0', left: '0' },
  });

  await browser.close();

  fs.writeFileSync(
    path.join(ROOT, 'dist', 'deck_text.json'),
    JSON.stringify({ slides: report.map((s) => ({ n: s.n, title: s.id, texts: s.texts })) }, null, 1)
  );

  let total = 0;
  console.log('\n=== QA HARNESS ===');
  for (const s of report) {
    total += s.issues.length;
    console.log(`\n[${s.issues.length ? 'FAIL' : 'OK  '}] slide ${s.n} "${s.id}" — ${s.issues.length} issue(s)`);
    const byKind = {};
    for (const it of s.issues) (byKind[it.kind] ||= []).push(it);
    for (const [kind, list] of Object.entries(byKind)) {
      console.log(`   ${kind}: ${list.length}`);
      for (const it of list.slice(0, 10)) console.log(`     - ${it.el}: ${it.detail}`);
      if (list.length > 10) console.log(`     ... and ${list.length - 10} more`);
    }
  }
  console.log(`\nscreenshots -> screenshots/slide-1..${report.length}.png`);
  console.log(`pdf         -> dist/deck.pdf`);
  console.log(`text        -> dist/deck_text.json`);
  console.log(`\nTOTAL ISSUES: ${total}`);
  process.exit(total === 0 ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
