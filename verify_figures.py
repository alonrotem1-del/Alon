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
        "cover.arc": (d["cover"]["arc"], "t", 3),
        "proof": (d["proof"], "n", 5),
        "stages": (d["stages"], "n", 5),
        "options": (d["options"], "id", 2),
        "discussion": (d["discussion"], "n", 5),
        "bio.focus_he": ([{"v": x} for x in d["bio"]["focus_he"]], "v", 4),
    }
    for name, (rows, key, expected_n) in tables.items():
        n = len(rows)
        distinct = len({r[key] for r in rows})
        dupes = [k for k, c in Counter(
            json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows).items() if c > 1]
        ok = n == expected_n and distinct == n and not dupes
        print(f"  {name:<18} rows={n:<3} expected={expected_n:<3} "
              f"distinct {key}={distinct:<3} exact-dupes={len(dupes)}  {'ok' if ok else 'FAIL'}")
        if n != expected_n:
            errs.append(f"{name}: {n} rows, expected {expected_n}")
        if distinct != n:
            errs.append(f"{name}: {key} not unique")
        if dupes:
            errs.append(f"{name}: {len(dupes)} exact duplicate row(s)")

    for st in d["stages"]:
        n = len(st["items"])
        print(f"  stage {st['n']} items    n={n}  {'ok' if n == 4 else 'FAIL'}")
        if n != 4:
            errs.append(f"stage {st['n']}: {n} items, expected 4")

    print()
    # The commercial surface of this deck is deliberately tiny. Assert it stays so.
    a, b = d["options"]
    ok = a["hours_min"] < a["hours_max"]
    print(f"  option a hours     {a['hours_min']} < {a['hours_max']}   {'ok' if ok else 'FAIL'}")
    if not ok:
        errs.append("option a: hours_min not < hours_max")

    ok = "hours_min" not in b and "hours_max" not in b
    print(f"  option b carries NO hour estimate      {'ok' if ok else 'FAIL'}")
    if not ok:
        errs.append("option b must not carry an hour estimate")

    ok = a["hours_caveat_he"].strip() != ""
    print(f"  option a hours are labelled indicative {'ok' if ok else 'FAIL'}")
    if not ok:
        errs.append("option a: the indicative-range caveat is missing")

    ok = isinstance(d["rate"]["amount"], int) and d["rate"]["amount"] > 0
    print(f"  hourly rate present  {d['rate']['amount']} {d['rate']['currency']}  {'ok' if ok else 'FAIL'}")
    if not ok:
        errs.append("rate.amount missing or invalid")

    banned = ("fee_min", "fee_max", "total", "price", "market_size",
              "willingness", "dev_budget", "users", "interviews")
    blob = json.dumps(d, ensure_ascii=False)
    hits = [k for k in banned if f'"{k}"' in blob]
    print(f"  no banned commercial/market fields     {'ok' if not hits else 'FAIL ' + str(hits)}")
    if hits:
        errs.append(f"banned field(s) present in source: {hits}")

    return errs


def expected_figures(d: dict) -> dict[str, list[str]]:
    """Independently derive every figure that should be visible, from source.

    This deck is methodological: the only commercial figures approved for
    display are the hourly rate and the indicative hour range for option A.
    """
    exp: dict[str, list[str]] = {}

    def put(token, src: str) -> None:
        exp.setdefault(str(token), []).append(src)

    put(d["rate"]["amount"], "rate.amount (approved: hourly rate)")

    a = d["options"][0]
    put(f'{a["hours_min"]}–{a["hours_max"]}', "options[a].hours (approved: indicative range)")

    # structural numerals that appear as prose in the methodology slide
    put(f'{d["stages"][0]["n"].lstrip("0")}–{d["stages"][2]["n"].lstrip("0")}',
        "loop_he: the iterating stage span")
    put(d["stages"][4]["n"].lstrip("0"), "gates_cap_he: the decision stage")

    m = re.search(r"(\d{4})", d["meeting"]["date_he"])
    if m:
        put(m.group(1), "meeting.date_he (year)")

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
