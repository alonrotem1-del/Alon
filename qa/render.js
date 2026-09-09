#!/usr/bin/env node
/**
 * qa/render.js — the QA gate. Runs on every build.
 *
 * Flags, per slide:
 *   1. content overflowing its slide
 *   2. elements escaping their container
 *   3. clipped text (scroll size exceeds client size)
 *   4. any font below the floor (24px substantive / 20px meta+footnote)
 *   5. footer collisions
 *   6. block-level siblings that overlap each other
 *
 * Also writes screenshots/slide-N.png and dist/deck.pdf.
 * Exits non-zero when any issue is found, so it can gate a build.
 */

const path = require('path');
const fs = require('fs');
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const ROOT = path.resolve(__dirname, '..');
const DECK = path.join(ROOT, 'dist', 'deck.html');
const SHOTS = path.join(ROOT, 'screenshots');
const PDF = path.join(ROOT, 'dist', 'deck.pdf');

/* Type floor. Only genuinely secondary text may sit in the 20-23px band:
   page furniture, the VAT footnote, and the small English glosses.
   Everything else — all substantive text — must be >= 24px (12pt). */
const FLOOR_SUBSTANTIVE = 24;
const FLOOR_META = 20;
const META_CLASSES = ['foot-txt', 'foot-pg', 'fee-vat', 'alt-t-en', 'phase-t-en'];

const TOL = 1.0; // px; sub-pixel layout rounding

function fmt(n) { return Math.round(n * 10) / 10; }

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
    ({ FLOOR_SUBSTANTIVE, FLOOR_META, META_CLASSES, TOL }) => {
      const slides = [...document.querySelectorAll('section.slide')];

      const area = (r) => Math.max(0, r.width) * Math.max(0, r.height);
      const overlap = (a, b) => {
        const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        return w > 0 && h > 0 ? w * h : 0;
      };
      const rectOf = (el) => {
        const r = el.getBoundingClientRect();
        return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
      };
      const ownText = (el) =>
        [...el.childNodes]
          .filter((n) => n.nodeType === 3)
          .map((n) => n.textContent)
          .join('')
          .trim();
      const desc = (el) => {
        const cls = el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '';
        return el.tagName.toLowerCase() + cls;
      };

      return slides.map((slide, i) => {
        const issues = [];
        const sr = rectOf(slide);
        const all = [...slide.querySelectorAll('*')];
        const foot = slide.querySelector('.foot');
        const footRect = foot ? rectOf(foot) : null;

        for (const el of all) {
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden') continue;
          const r = rectOf(el);
          if (r.width <= 0 && r.height <= 0) continue;

          const isAbs = cs.position === 'absolute' || cs.position === 'fixed';

          /* 1. content overflowing its slide */
          if (
            r.left < sr.left - TOL || r.right > sr.right + TOL ||
            r.top < sr.top - TOL || r.bottom > sr.bottom + TOL
          ) {
            issues.push({
              kind: 'slide-overflow',
              el: desc(el),
              detail: `rect [${Math.round(r.left - sr.left)},${Math.round(r.top - sr.top)} → ${Math.round(r.right - sr.left)},${Math.round(r.bottom - sr.top)}] escapes 0,0 → 1920,1080`,
            });
          }

          /* 2. elements escaping their container */
          const parent = el.parentElement;
          if (parent && parent !== slide && !isAbs) {
            const pcs = getComputedStyle(parent);
            const isBlockish = ['block', 'flex', 'grid', 'list-item'].includes(pcs.display);
            if (isBlockish) {
              const pr = rectOf(parent);
              if (
                r.left < pr.left - TOL || r.right > pr.right + TOL ||
                r.top < pr.top - TOL || r.bottom > pr.bottom + TOL
              ) {
                issues.push({
                  kind: 'container-escape',
                  el: desc(el),
                  detail: `escapes ${desc(parent)} by ` +
                    `L${Math.round(Math.max(0, pr.left - r.left))} ` +
                    `R${Math.round(Math.max(0, r.right - pr.right))} ` +
                    `T${Math.round(Math.max(0, pr.top - r.top))} ` +
                    `B${Math.round(Math.max(0, r.bottom - pr.bottom))}`,
                });
              }
            }
          }

          /* 3. clipped text */
          const txt = ownText(el);
          if (txt) {
            if (el.scrollWidth > el.clientWidth + TOL && el.clientWidth > 0) {
              issues.push({
                kind: 'text-clipped',
                el: desc(el),
                detail: `scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth} — "${txt.slice(0, 40)}"`,
              });
            }
            if (el.scrollHeight > el.clientHeight + TOL && el.clientHeight > 0 && cs.overflow !== 'visible') {
              issues.push({
                kind: 'text-clipped',
                el: desc(el),
                detail: `scrollHeight ${el.scrollHeight} > clientHeight ${el.clientHeight} — "${txt.slice(0, 40)}"`,
              });
            }

            /* 4. font floor */
            const fs = parseFloat(cs.fontSize);
            // meta status is inherited: a <span> inside .foot-pg is page furniture too
            const isMeta = !!el.closest(META_CLASSES.map((c) => '.' + c).join(','));
            const floor = isMeta ? FLOOR_META : FLOOR_SUBSTANTIVE;
            if (fs < floor - 0.01) {
              issues.push({
                kind: 'font-below-floor',
                el: desc(el),
                detail: `${fs}px < ${floor}px floor (${isMeta ? 'meta/footnote' : 'substantive'}) — "${txt.slice(0, 40)}"`,
              });
            }
          }

          /* 5. footer collision */
          if (footRect && foot !== el && !foot.contains(el) && !el.contains(foot)) {
            const ov = overlap(r, footRect);
            if (ov > 4 && area(r) > 0) {
              issues.push({
                kind: 'footer-collision',
                el: desc(el),
                detail: `overlaps footer by ${Math.round(ov)}px²`,
              });
            }
          }
        }

        /* 6. overlapping block siblings */
        const seen = new Set();
        const containers = [slide, ...all];
        for (const c of containers) {
          const kids = [...c.children].filter((k) => {
            const cs = getComputedStyle(k);
            if (cs.display === 'none' || cs.visibility === 'hidden') return false;
            if (cs.position === 'absolute' || cs.position === 'fixed') return false;
            return ['block', 'flex', 'grid', 'list-item'].includes(cs.display);
          });
          for (let a = 0; a < kids.length; a++) {
            for (let b = a + 1; b < kids.length; b++) {
              const ra = rectOf(kids[a]), rb = rectOf(kids[b]);
              const ov = overlap(ra, rb);
              if (ov > 4) {
                const key = desc(kids[a]) + '|' + desc(kids[b]);
                if (seen.has(key)) continue;
                seen.add(key);
                issues.push({
                  kind: 'sibling-overlap',
                  el: desc(kids[a]),
                  detail: `overlaps sibling ${desc(kids[b])} by ${Math.round(ov)}px²`,
                });
              }
            }
          }
        }

        /* 7. rows that are meant to be compared side by side must share a baseline */
        const groups = {};
        for (const el of all) {
          const g = el.dataset.row;
          if (g) (groups[g] ||= []).push(el);
        }
        for (const [g, els] of Object.entries(groups)) {
          if (els.length < 2) continue;
          const tops = els.map((e) => rectOf(e).top);
          const spread = Math.max(...tops) - Math.min(...tops);
          if (spread > TOL) {
            issues.push({
              kind: 'row-misalignment',
              el: `[data-row="${g}"]`,
              detail: `tops differ by ${Math.round(spread * 10) / 10}px across ${els.length} cards`,
            });
          }
        }

        return {
          n: i + 1,
          id: slide.id,
          title: slide.dataset.title || '',
          rect: { top: sr.top, height: sr.height },
          issues,
        };
      });
    },
    { FLOOR_SUBSTANTIVE, FLOOR_META, META_CLASSES, TOL }
  );

  /* screenshots */
  for (const s of report) {
    await page.locator(`#${s.id}`).screenshot({
      path: path.join(SHOTS, `slide-${s.n}.png`),
    });
  }

  /* Print to PDF at the same physical size as the PowerPoint: 13.333 x 7.5in,
     the standard 16:9 slide. Chromium lays out at 96 CSS px per inch, so a
     13.333in page is 1280px wide and the 1920px canvas is scaled by 1280/1920.
     It stays vector, and the two deliverables print at identical scale. */
  const PDF_SCALE = 1280 / 1920;
  await page.pdf({
    path: PDF,
    width: '13.333in',
    height: '7.5in',
    scale: PDF_SCALE,
    printBackground: true,
    pageRanges: `1-${report.length}`,
    margin: { top: '0', right: '0', bottom: '0', left: '0' },
  });

  await browser.close();

  /* ---- report ---- */
  let total = 0;
  console.log('\n=== QA HARNESS ===');
  for (const s of report) {
    total += s.issues.length;
    const mark = s.issues.length === 0 ? 'OK  ' : 'FAIL';
    console.log(`\n[${mark}] slide ${s.n} (${s.id}) "${s.title}" — ${s.issues.length} issue(s)`);
    const byKind = {};
    for (const it of s.issues) (byKind[it.kind] ||= []).push(it);
    for (const [kind, list] of Object.entries(byKind)) {
      console.log(`   ${kind}: ${list.length}`);
      for (const it of list.slice(0, 12)) console.log(`     - ${it.el}: ${it.detail}`);
      if (list.length > 12) console.log(`     ... and ${list.length - 12} more`);
    }
  }
  console.log(`\nscreenshots -> screenshots/slide-1..${report.length}.png`);
  console.log(`pdf         -> dist/deck.pdf`);
  console.log(`\nTOTAL ISSUES: ${total}`);
  process.exit(total === 0 ? 0 : 1);
})().catch((e) => {
  console.error(e);
  process.exit(2);
});
