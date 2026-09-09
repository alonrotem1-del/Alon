#!/usr/bin/env python3
"""
verify_figures.py — reconciles every number visible on a slide against the
source data, so no figure reaches the deck by transcription.

Two passes:
  1. Sanity-check data/deck_data.json itself (row counts, distinct keys, exact
     duplicate rows, range ordering, and the shape of the commercial surface).
     If a check fails, stop — do not certify a deck built on data that has not
     been checked.
  2. Pull every numeric token out of the RENDERED text (dist/deck_text.json,
     which is what the browser actually painted) and account for each one
     against a figure independently derived from the source. Any rendered number
     that cannot be traced to a source field is a failure, and so is any source
     figure that never made it onto a slide.

Pass 2 also enforces where the two approved commercial figures may appear: on
the engagement-frame slide and nowhere else. The engagement-models slide must
carry no figure at all.

Run after build.py + qa/render.js. Exits non-zero on any discrepancy.
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

# The two slides the commercial rules are written about, by data-title.
SLIDE_COMMERCIAL = "מסגרת התקשרות"
SLIDE_MODELS = "דרכי עבודה"

# numeric tokens as painted: 20–40 / 450 / 3–5 / 2026 / 9,000–13,000 / 10+
TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?(?:–\d[\d,]*(?:\.\d+)?)?\+?")


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
        "steps": (d["steps"], "n", 4),
        "commercial.tracks": (d["commercial"]["tracks"], "option_id", 2),
        "bio.exp_he": ([{"v": x} for x in d["bio"]["exp_he"]], "v", 5),
        "bio.edu_he": ([{"v": x} for x in d["bio"]["edu_he"]], "v", 2),
        "bio.proj_he": ([{"v": x} for x in d["bio"]["proj_he"]], "v", 7),
    }
    for name, (rows, key, expected_n) in tables.items():
        n = len(rows)
        distinct = len({r[key] for r in rows})
        dupes = [k for k, c in Counter(
            json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows).items() if c > 1]
        ok = n == expected_n and distinct == n and not dupes
        print(f"  {name:<20} rows={n:<3} expected={expected_n:<3} "
              f"distinct {key}={distinct:<3} exact-dupes={len(dupes)}  {'ok' if ok else 'FAIL'}")
        if n != expected_n:
            errs.append(f"{name}: {n} rows, expected {expected_n}")
        if distinct != n:
            errs.append(f"{name}: {key} not unique")
        if dupes:
            errs.append(f"{name}: {len(dupes)} exact duplicate row(s)")

    for st in d["stages"]:
        n = len(st["items"])
        print(f"  stage {st['n']} items      n={n}  {'ok' if n == 4 else 'FAIL'}")
        if n != 4:
            errs.append(f"stage {st['n']}: {n} items, expected 4")

    print()
    # Every commercial track must point at a real engagement model, so the two
    # slides cannot drift apart.
    ids = {o["id"] for o in d["options"]}
    orphan = [t["option_id"] for t in d["commercial"]["tracks"] if t["option_id"] not in ids]
    print(f"  tracks map onto engagement models      {'ok' if not orphan else 'FAIL ' + str(orphan)}")
    if orphan:
        errs.append(f"commercial track(s) reference unknown option(s): {orphan}")

    # The commercial surface of this deck is deliberately tiny. Assert it stays so.
    a, b = d["commercial"]["tracks"]
    ok = a["hours_min"] < a["hours_max"]
    print(f"  guided track hours   {a['hours_min']} < {a['hours_max']}   {'ok' if ok else 'FAIL'}")
    if not ok:
        errs.append("guided track: hours_min not < hours_max")

    ok = "hours_min" not in b and "hours_max" not in b
    print(f"  full-research track carries NO hour estimate  {'ok' if ok else 'FAIL'}")
    if not ok:
        errs.append("full-research track must not carry an hour estimate")

    ok = a["note_he"].strip() != "" and "אינדיקטיבי" in a["note_he"]
    print(f"  guided hours are labelled indicative    {'ok' if ok else 'FAIL'}")
    if not ok:
        errs.append("guided track: the indicative-range caveat is missing")

    ok = isinstance(d["rate"]["amount"], int) and d["rate"]["amount"] > 0
    print(f"  hourly rate present  {d['rate']['amount']} {d['rate']['currency']}  "
          f"{'ok' if ok else 'FAIL'}")
    if not ok:
        errs.append("rate.amount missing or invalid")

    # Pricing was moved off the engagement-models slide. Nothing in `options`
    # may carry a figure any more.
    money = ("hours_min", "hours_max", "rate", "amount", "hours", "cost", "fee")
    hits = sorted({k for o in d["options"] for k in o if k in money})
    print(f"  engagement models carry no figures      {'ok' if not hits else 'FAIL ' + str(hits)}")
    if hits:
        errs.append(f"options must not carry commercial fields: {hits}")

    banned = ("fee_min", "fee_max", "total", "price", "market_size",
              "willingness", "dev_budget", "users", "interviews")
    blob = json.dumps(d, ensure_ascii=False)
    hits = [k for k in banned if f'"{k}"' in blob]
    print(f"  no banned commercial/market fields      {'ok' if not hits else 'FAIL ' + str(hits)}")
    if hits:
        errs.append(f"banned field(s) present in source: {hits}")

    return errs


def source_prose_figures(d: dict) -> dict[str, list[str]]:
    """Every numeric token that appears verbatim in a source string, with the
    JSON path it came from. Editorial notes and the web-page chrome are skipped:
    neither is painted onto a slide, and the notes discuss superseded numbers."""
    out: dict[str, list[str]] = {}
    SKIP_ROOTS = {"web"}

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k.startswith("_") or (not path and k in SKIP_ROOTS):
                    continue
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            for tok in TOKEN.findall(node):
                out.setdefault(tok.rstrip(",."), []).append(path)

    walk(d, "")
    return out


def expected_figures(d: dict) -> dict[str, list[str]]:
    """Independently derive every figure that should be visible, from source.

    This deck is methodological: the only commercial figures approved for
    display are the hourly rate and the indicative hour range for the guided
    track. Everything else numeric is prose already present in the data.
    """
    exp = source_prose_figures(d)

    def put(token, src: str) -> None:
        exp.setdefault(str(token), []).append(src)

    put(d["rate"]["amount"], "rate.amount (approved: hourly rate)")

    a = d["commercial"]["tracks"][0]
    put(f'{a["hours_min"]}–{a["hours_max"]}',
        "commercial.tracks[0] (approved: indicative hour range)")

    return exp


def commercial_placement(ex: dict, d: dict) -> list[str]:
    """The rate and the hour range belong on the engagement-frame slide only,
    and the engagement-models slide must carry no figure at all."""
    errs: list[str] = []
    approved = {str(d["rate"]["amount"]),
                f'{d["commercial"]["tracks"][0]["hours_min"]}–'
                f'{d["commercial"]["tracks"][0]["hours_max"]}'}

    print("\n" + "=" * 78)
    print("PASS 3 — WHERE THE COMMERCIAL FIGURES ARE ALLOWED TO APPEAR")
    print("=" * 78)

    for sl in ex["slides"]:
        toks = {t.rstrip(",.") for text in sl["texts"] for t in TOKEN.findall(text)}
        here = sorted(toks & approved)
        if sl["title"] == SLIDE_COMMERCIAL:
            missing = sorted(approved - toks)
            print(f"  slide {sl['n']} \"{sl['title']}\": carries {here or 'nothing'}  "
                  f"{'ok' if not missing else 'FAIL'}")
            if missing:
                errs.append(f"approved figure(s) {missing} missing from the engagement-frame slide")
        else:
            print(f"  slide {sl['n']} \"{sl['title']}\": {here or 'no commercial figure'}  "
                  f"{'ok' if not here else 'FAIL'}")
            if here:
                errs.append(f"commercial figure(s) {here} leaked onto slide {sl['n']} \"{sl['title']}\"")

        if sl["title"] == SLIDE_MODELS:
            stray = sorted(t for t in toks if t not in FURNITURE)
            print(f"  slide {sl['n']} \"{sl['title']}\": no figures at all  "
                  f"{'ok' if not stray else 'FAIL ' + str(stray)}")
            if stray:
                errs.append(f"engagement-models slide must carry no figures, found {stray}")

    return errs


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

    placement = commercial_placement(ex, d)
    if placement:
        print("\nCOMMERCIAL PLACEMENT:")
        for e in placement:
            fail(e)

    total_bad = len(unexplained) + len(missing) + len(placement)
    print(f"\nrendered numeric tokens : {len(seen)}")
    print(f"traced to source        : {len(matched)}")
    print(f"unexplained             : {len(unexplained)}")
    print(f"source figures unused   : {len(missing)}")
    print(f"placement violations    : {len(placement)}")
    print(f"\n{'FIGURES VERIFIED' if total_bad == 0 else 'FIGURE VERIFICATION FAILED'}")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
