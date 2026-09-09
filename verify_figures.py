#!/usr/bin/env python3
"""
verify_figures.py — reconciles every number visible on a slide against the
source data, so no figure reaches the deck by transcription.

Two passes:
  1. Sanity-check data/deck_data.json itself (row counts, distinct keys, exact
     duplicate rows, range ordering). If a check fails, stop — do not certify a
     deck built on data that has not been checked.
  2. Pull every numeric token out of the RENDERED text (dist/deck_extract.json,
     which is what the browser actually painted) and account for each one
     against a figure independently derived from the source. Any rendered number
     that cannot be traced to a source field is a failure, and so is any source
     figure that never made it onto a slide.

Run after build.py + qa/extract.js. Exits non-zero on any discrepancy.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "deck_data.json"
RENDERED = ROOT / "dist" / "deck_text.json"

# Digits that are page furniture (page numbers, section and item indices)
# rather than analytical figures.
FURNITURE = {f"{i:02d}" for i in range(0, 21)}


def fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


def sanity_checks(d: dict) -> list[str]:
    """Structural checks on the source data. Returns a list of failures."""
    errs: list[str] = []
    print("=" * 78)
    print("PASS 1 — SOURCE DATA SANITY CHECKS  (data/deck_data.json)")
    print("=" * 78)

    tables = {
        "alternatives": (d["alternatives"], "id", 2),
        "phases": (d["phases"], "index", 2),
        "discussion": (d["discussion"], "index", 3),
        "bio.credentials": (d["bio"]["credentials"], "label_he", 3),
    }
    for name, (rows, key, expected_n) in tables.items():
        n = len(rows)
        keys = [r[key] for r in rows]
        distinct = len(set(keys))
        dupes = [k for k, c in Counter(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows).items() if c > 1]
        ok = n == expected_n and distinct == n and not dupes
        print(f"  {name:<20} rows={n:<3} expected={expected_n:<3} distinct {key}={distinct:<3} exact-dupes={len(dupes)}  {'ok' if ok else 'FAIL'}")
        if n != expected_n:
            errs.append(f"{name}: {n} rows, expected {expected_n}")
        if distinct != n:
            errs.append(f"{name}: {key} not unique ({distinct} distinct of {n})")
        if dupes:
            errs.append(f"{name}: {len(dupes)} exact duplicate row(s)")

    for ph in d["phases"]:
        n = len(ph["bullets"])
        print(f"  phase {ph['index']} bullets  n={n}  {'ok' if n == 3 else 'FAIL'}")
        if n != 3:
            errs.append(f"phase {ph['index']}: {n} bullets, expected 3")

    print()
    for alt in d["alternatives"]:
        for lo_k, hi_k in (("fee_min", "fee_max"), ("hours_min", "hours_max"),
                           ("weeks_min", "weeks_max"), ("sessions_min", "sessions_max")):
            if lo_k not in alt:
                continue
            lo, hi = alt[lo_k], alt[hi_k]
            ok = lo < hi
            print(f"  alt {alt['id']}  {lo_k.split('_')[0]:<9} {lo:>7,} < {hi:>7,}   {'ok' if ok else 'FAIL'}")
            if not ok:
                errs.append(f"alt {alt['id']}: {lo_k}={lo} not < {hi_k}={hi}")

    a, b = d["alternatives"]
    for k in ("hours_min", "hours_max", "fee_min", "fee_max"):
        ok = b[k] > a[k]
        print(f"  alt b {k:<10} {b[k]:>7,} > alt a {a[k]:>7,}   {'ok' if ok else 'FAIL'}")
        if not ok:
            errs.append(f"alternative b {k} ({b[k]}) is not greater than alternative a ({a[k]})")

    mvp = d["mvp"]
    ok = mvp["features_min"] < mvp["features_max"]
    print(f"  mvp features   {mvp['features_min']} < {mvp['features_max']}   {'ok' if ok else 'FAIL'}")
    if not ok:
        errs.append("mvp: features_min not < features_max")

    return errs


def expected_figures(d: dict) -> dict[str, list[str]]:
    """Independently derive every figure that should be visible, from source.

    A token can legitimately have more than one source — "2-3" is both the MVP
    feature count and alternative A's duration in weeks — so provenance is a
    list. Collapsing it to one string would quietly hide the second meaning.
    """
    exp: dict[str, list[str]] = {}

    def put(token: str, src: str) -> None:
        exp.setdefault(str(token), []).append(src)

    put(d["roster"]["dj_count"], "roster.dj_count")
    put(d["gtm"]["first_users"], "gtm.first_users")
    put(f'{d["experience_years_min"]}+', "experience_years_min")
    put(f'{d["mvp"]["features_min"]}–{d["mvp"]["features_max"]}', "mvp.features_min/max")

    for alt in d["alternatives"]:
        i = alt["id"]
        if "sessions_min" in alt:
            put(f'{alt["sessions_min"]}–{alt["sessions_max"]}', f"alternatives[{i}].sessions")
        put(f'{alt["hours_min"]}–{alt["hours_max"]}', f"alternatives[{i}].hours")
        put(f'{alt["weeks_min"]}–{alt["weeks_max"]}', f"alternatives[{i}].weeks")
        # thousands separators are produced here, exactly as build.py produces them
        put(f'{alt["fee_min"]:,}', f"alternatives[{i}].fee_min")
        put(f'{alt["fee_max"]:,}', f"alternatives[{i}].fee_max")
        # the chart value label prints the pair as a single range token
        put(f'{alt["fee_min"]:,}–{alt["fee_max"]:,}', f"alternatives[{i}].fee range")

    # the slide-7 headline states ratios; re-derive them here independently
    a, b = d["alternatives"]
    def fmt(x):
        return f"{x:.0f}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"
    for lo_k, hi_k, name in (("hours_min", "hours_max", "hours"), ("fee_min", "fee_max", "fee")):
        put(fmt(b[lo_k] / a[lo_k]), f"derived ratio b/a {name} (min)")
        put(fmt(b[hi_k] / a[hi_k]), f"derived ratio b/a {name} (max)")
    # chart axis maxima are the larger of the pair, printed on the axis
    for hi_k, f in (("hours_max", lambda v: f"{v:g}"), ("weeks_max", lambda v: f"{v:g}"),
                    ("fee_max", lambda v: f"{v:,.0f}")):
        put(f(max(a[hi_k], b[hi_k])), f"chart axis max ({hi_k})")
    put("0", "chart axis zero")

    m = re.search(r"(\d+)\s+\S+\s+(\d{4})", d["meeting"]["date_he"])
    if m:
        put(m.group(1), "meeting.date_he (day)")
        put(m.group(2), "meeting.date_he (year)")

    return exp


def main() -> int:
    d = json.loads(DATA.read_text(encoding="utf-8"))
    errs = sanity_checks(d)
    if errs:
        print(f"\nSTOPPED: {len(errs)} sanity check(s) failed on {DATA.relative_to(ROOT)}:")
        for e in errs:
            print(f"  - {e}")
        print("Not certifying figures against unverified data.")
        return 1

    if not RENDERED.exists():
        print(f"\nERROR: {RENDERED} missing — run `node qa/render.js` first.")
        return 1

    ex = json.loads(RENDERED.read_text(encoding="utf-8"))
    exp = expected_figures(d)

    print("\n" + "=" * 78)
    print("PASS 2 — EVERY RENDERED NUMBER TRACED TO ITS SOURCE FIELD")
    print("=" * 78)

    # numeric tokens as painted: 9,000-13,000 / 15-20 / 10+ / 2.8 / 16 ...
    TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?(?:–\d[\d,]*(?:\.\d+)?)?\+?")
    seen: dict[str, list[int]] = {}
    for sl in ex["slides"]:
        for text in sl["texts"]:
            for tok in TOKEN.findall(text):
                tok = tok.rstrip(",.")   # sentence punctuation, not part of the figure
                if tok:
                    seen.setdefault(tok, []).append(sl["n"])

    pages = {f"{i}" for i in range(1, len(ex["slides"]) + 1)}
    unexplained, matched = [], []
    for tok, slides in sorted(seen.items()):
        where = ",".join(str(x) for x in sorted(set(slides)))
        if tok in exp:
            matched.append((tok, ' + '.join(exp[tok]), where))
        elif tok in FURNITURE or tok in pages:
            matched.append((tok, "page furniture (index / page number)", where))
        else:
            unexplained.append((tok, where))

    print(f"{'rendered':<14}{'slides':<9}source")
    print("-" * 78)
    for tok, src, where in matched:
        print(f"{tok:<14}{where:<9}{src}")

    missing = [(t, s) for t, s in exp.items() if t not in seen]

    print()
    if unexplained:
        print("UNEXPLAINED NUMBERS ON SLIDES (not derivable from deck_data.json):")
        for tok, where in unexplained:
            fail(f"'{tok}' on slide(s) {where}")
    if missing:
        print("SOURCE FIGURES THAT NEVER REACHED A SLIDE:")
        for tok, srcs in missing:
            fail(f"'{tok}' from {' + '.join(srcs)}")

    total_bad = len(unexplained) + len(missing)
    print(f"\nrendered numeric tokens : {len(seen)}")
    print(f"traced to source        : {len(matched)}")
    print(f"unexplained             : {len(unexplained)}")
    print(f"source figures unused   : {len(missing)}")
    print(f"\n{'FIGURES VERIFIED' if total_bad == 0 else 'FIGURE VERIFICATION FAILED'}")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
