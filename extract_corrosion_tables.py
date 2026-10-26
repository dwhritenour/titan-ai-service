#!/usr/bin/env python3
"""
extract_corrosion_tables.py — Schweitzer Corrosion Resistance Tables
(5th ed.) scanned-page extractor for Titan AI.   v1.7, 2026-10-09
  v1.6: letter detector requires a glyph SHAPE (span + stem) — kills
        stripe-bleed false positives; queued-whole pages get state
        "review" so a rerun retries them.
  v1.7: header detection rewritten — the rotated temperature digits
        and the F/C mini-header (whose '60' reads as a letter glyph)
        are recognized by STRONG ink clusters at >=75% of column
        centers measured at a fixed threshold, so gray-stripe bleed
        on light pages can no longer hide them. Wrapped-label prompt
        rule tightened (rule lines separate rows).
  v1.8: rule-grid healing — scanner banding washed out row rules on
        some light pages, leaving holes whose rows were silently
        dropped (found when vision correctly saw a letter pixel had
        lost). Rules are re-detected at higher thresholds (safe: the
        label zone has no gray stripes) when the grid has holes,
        guarded by a constant-row-pitch check.
  v1.9: stacked-letter split — a washed-out rule between two RATED
        rows merges them into one double-height band (a 2x gap that
        healing rightly leaves alone, since wrapped labels look the
        same). The letter window disambiguates: two stacked glyphs =
        two rows, split at the inter-glyph gap; a wrapped label has
        at most one glyph and is never split.
  v2.0: whole FILES scanned lighter (4, 6, 8, back half of 1) have
        faint 1px rules that vanish below ink~230 — grids came back
        implausibly sparse-but-regular, so v1.8's hole detector never
        fired, and sub-5-row pages were mislabeled "no-chart" (126
        pages). Healing now also triggers on sparse or wrong-pitch
        grids, candidates escalate to 230/245, and acceptance uses an
        absolute row-pitch guard (holes are NOT disqualifying — real
        section breaks look like holes). --retry-no-chart flag added
        for the recovery rerun.
  v2.1: rule ladder extended to near-paper (248/250/252) for the
        faintest scans; merge SALVAGE — when vision and pixel agree
        on the total row count but not the rated count, rows pair by
        position and only the disputed rows queue (single-row review
        entries) while the rest of the page extracts. Whole-page
        queueing now only happens when even the row totals disagree.

  v2.2: tuned for the production scanner's 600-dpi scans (2026-10).
        Header-band detection discriminates by glyph HEIGHT at the
        column centers (crisp scans defeat run-length tests both
        ways); solid title-bar bands are filtered by dark fill;
        merge SALVAGE aligns with section-header rows INCLUDED on
        both sides — the old header-stripped zip could silently
        pair every row below a dropped dispute one row off.
        Old-scan regression: file 1 pp.35-56 match the production
        master exactly under v2.2.

  v2.3: IN-LINE transition letters. Crisp scans print the G/S/U
        letters touching the bar, so gap-based splitting finds no
        gaps (Aluminum in acetic acid read as one G bar). Bars now
        split at tall glyph clusters ALONG the bar (stroke width
        >=4px and height <=0.85 band excludes stripe-edge verticals),
        and a letter at/past the bar's end emits a terminal row:
        "U above 190F (no bar beyond)". Pixel trailing letters are
        vision-gated — dropped silently unless the model also reads
        a letter there. Validated: 304/347, 316/316L and 20 Cb 3
        match the hand-checked pilot exactly; Aluminum in acetic
        acid 10/20% reads G->S->U as printed.
        Hardening (same release): a vision-rejected trailing letter
        restores the bar's un-cut end (a phantom glyph must not
        silently shorten the bar), and positional SALVAGE is allowed
        only when every band is single-row height — a 2-line label
        and two merged blank rows are the same height, and pairing
        across the wrong reading shifts every row below it.

Turns scanned chart pages into structured rows:
  chemical, category, material, rating, temp range (F and C), notes,
  source file/page — one row per rating segment.

HYBRID DESIGN (born from the pilot with Dave, 2026-10-07/08):
  * PIXEL GEOMETRY measures everything geometric: the stripe grid,
    row rules, rating-letter presence, bar start/end, in-bar letter
    gaps. Deterministic — eyeballing bar ends (human or AI) was
    proven unreliable.
  * The VISION MODEL (Anthropic API, your key) reads only TEXT:
    the corrodent name in the header, row labels + section headers,
    which letter each row carries, which letter sits in each bar gap.
  * The two passes CROSS-CHECK each other; disagreement flags the
    row into review_queue.csv instead of guessing.

THE RULEBOOK (verified against the physical book):
  * Columns alternate white/gray. The FIRST column (60F) is WHITE and
    holds the rating letter; the first GRAY stripe is 80F.
  * Printed temps are COLUMN CENTERS; the lines between columns are
    MIDPOINT temps (book p.x). Resolution:
      - bar ENDS snap to nearest 10F (midpoints are legitimate),
      - rating TRANSITIONS snap to nearest 20F printed column
        (the book only ever quotes transitions at printed temps).
  * A letter INSIDE a bar is the rating of the segment AFTER it;
    the ink gap around it is typographic, not data. Ratings along a
    bar only degrade (E->G->S->U) — violations get flagged.
  * U with NO bar = unsatisfactory at every temperature (blank temps).
  * A letter with no bar = rated at 60F only.  Blank row = no data.
  * C values come from the book's PRINTED F<->C pairs, never computed
    (computed only for unprinted midpoint temps).
  * Metals pages: 26 columns 60-560F. Other pages: 21 columns 60-460F.
  * EVEN book pages: shifted toward the gutter, slightly skewed,
    lighter ink, and row rules run FULL WIDTH (odd pages underline
    only the label). Rules are told apart from bars by where they
    START: rules begin far left of the chart, bars never do.

USAGE (on the server, e.g. C:\\corrosion-extract):
  pip install pymupdf numpy pillow anthropic python-dotenv
  python extract_corrosion_tables.py --input-dir "D:\\scans" --out out
  python extract_corrosion_tables.py ... --pixel-only      (no API, test)
  python extract_corrosion_tables.py ... --limit 20        (first pages)
Resumable: per-page state in out/state.json; rerun continues.
API key: ANTHROPIC_API_KEY env var, or --env-file pointing at an
existing .env (e.g. C:\\titan-ai-service\\.env).
"""

import argparse
import base64
import csv
import io
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("corrosion")

# ── book constants ───────────────────────────────────────────────────
F_TO_C = {60: 15, 80: 26, 100: 38, 120: 49, 140: 60, 160: 71, 180: 82,
          200: 93, 220: 104, 240: 116, 260: 127, 280: 138, 300: 149,
          320: 160, 340: 171, 360: 182, 380: 193, 400: 204, 420: 216,
          440: 227, 460: 238, 480: 249, 500: 260, 520: 271, 540: 282,
          560: 293}
RATING_MEANING = {
    "E": "excellent, <2 mils penetration/yr",
    "G": "good, <20 mils penetration/yr",
    "S": "satisfactory, <50 mils penetration/yr",
    "U": "unsatisfactory",
    "R": "resistant (nonmetallics)",
    "ND": "no data available",
}
RANK = {"E": 0, "R": 0, "G": 1, "S": 2, "U": 3}     # degradation order
SOURCE = "Corrosion Resistance Tables, 5th ed. (Schweitzer)"


def c_of(f):
    return F_TO_C.get(int(f), round((int(f) - 32) * 5 / 9))


# ── rendering ────────────────────────────────────────────────────────
def render(doc, page_index, dpi=300):
    import fitz
    pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72),
                                     colorspace=fitz.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height,
                                                              pix.width)


def page_png(img, max_width=1100):
    """Downscaled PNG bytes for the vision pass."""
    from PIL import Image
    im = Image.fromarray(img)
    if im.width > max_width:
        im = im.resize((max_width, int(im.height * max_width / im.width)))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ── deskew ───────────────────────────────────────────────────────────
def deskew(img):
    """Estimate skew from long horizontal rules; rotate if needed."""
    dark = img < 120
    H, W = img.shape
    angles = []
    for y0 in range(int(H * 0.2), int(H * 0.85), max(1, H // 40)):
        band = dark[y0:y0 + 14, :]
        colhit = band.any(axis=0)
        # a long rule crosses most of some wide span
        runs = _runs(colhit, min_len=int(W * 0.35))
        for s, e in runs:
            xs = np.linspace(s + 10, e - 10, 24).astype(int)
            ys = []
            for x in xs:
                col = np.where(band[:, x])[0]
                ys.append(col.mean() if len(col) else np.nan)
            ys = np.array(ys)
            ok = ~np.isnan(ys)
            if ok.sum() > 12:
                slope = np.polyfit(xs[ok], ys[ok], 1)[0]
                angles.append(np.degrees(np.arctan(slope)))
    if not angles:
        return img, 0.0
    ang = float(np.median(angles))
    if abs(ang) < 0.08:
        return img, ang
    from PIL import Image
    im = Image.fromarray(img).rotate(ang, resample=Image.BILINEAR,
                                     fillcolor=255)
    return np.asarray(im), ang


def _runs(mask, min_len):
    d = np.diff(np.concatenate(([0], mask.view(np.int8), [0])))
    return [(int(s), int(e)) for s, e in
            zip(np.where(d == 1)[0], np.where(d == -1)[0]) if e - s >= min_len]


# ── stripe calibration ───────────────────────────────────────────────
def calibrate(img):
    """Gray stripes -> (x80, px_per_20F, n_stripes). None if no chart."""
    grayish = (img >= 140) & (img <= 246)
    H = img.shape[0]
    body = grayish[int(H * 0.18):int(H * 0.82), :]
    colfrac = body.mean(axis=0)
    for thresh in (0.30, 0.22, 0.15):
        runs = _runs(colfrac > thresh, min_len=20)
        runs = [(a, b) for a, b in runs if 25 < b - a < 90]
        if len(runs) < 8:
            continue
        centers = np.array([(a + b) / 2 for a, b in runs])
        d = np.diff(centers)
        med = np.median(d)
        if med <= 0 or np.std(d) > 0.10 * med:
            # try trimming outlier runs at the ends
            good = [c for c in centers]
            continue
        return float(centers[0]), float(med) / 2.0, len(runs)
    return None


def temp_at(x, x80, pitch):
    return 80.0 + 20.0 * (x - x80) / pitch


def snap_end(t):          # bar ends: 10F resolution
    return int(round(t / 10.0) * 10)


def snap_transition(t):   # transitions: printed 20F columns only
    return int(round((t - 60) / 20.0) * 20 + 60)


# ── horizontal structure: rules vs bars ──────────────────────────────
def rule_ys(img, x80, pitch, dark_thresh):
    """Row separators via windowed dark-fraction over the LABEL zone —
    tolerant of thin/broken scan lines; works for both the odd-page
    (label underline) and even-page (full-width rule) styles."""
    dark = img < dark_thresh
    H = img.shape[0]
    chart_left = int(x80 - 1.6 * pitch)
    body = dark[int(H * 0.12):int(H * 0.92), :chart_left]
    colhits = body.sum(axis=0)
    nz = np.where(colhits > body.shape[0] * 0.02)[0]
    if len(nz) == 0:
        return []
    x0 = int(nz[0]) + 5
    x1 = chart_left - 30
    if x1 - x0 < 6 * pitch:
        return []
    ys = [y for y in range(int(H * 0.10), int(H * 0.92))
          if dark[y, x0:x1].mean() > 0.5]
    return _group_scalar(ys, gap=3)


def pitch_clean(rules):
    """Drop rules implausibly close to their predecessor (false doubles
    from text baselines); keeps 2-line label rows (wider gaps are fine)."""
    if len(rules) < 4:
        return rules
    d = np.diff(rules)
    med = float(np.median(d))
    out = [rules[0]]
    for r in rules[1:]:
        if r - out[-1] >= 0.55 * med:
            out.append(r)
    return out


def horizontal_features(img, x80, pitch, dark_thresh, rules):
    """Chart BARS only: dark runs in the chart zone, away from rule
    rows, with bar-like thickness (digits in the temp header are ~30px
    tall and get rejected)."""
    dark = img < dark_thresh
    H, W = img.shape
    chart_left = x80 - 1.6 * pitch
    chart_right = min(W - 10, x80 + 24.8 * pitch)
    rule_set = set()
    for r in rules:
        rule_set.update(range(r - 4, r + 5))
    raw_bars = []
    for y in range(int(H * 0.10), int(H * 0.92)):
        if y in rule_set:
            continue
        row = dark[y, :int(chart_right)]
        for s, e in _runs(row, min_len=12):
            if e > x80 - 8 and s >= chart_left - 6:
                raw_bars.append((y, s, e))
    merged = []
    for y, s, e in sorted(raw_bars):
        for b in merged:
            if abs(b["y2"] - y) <= 2 and not (e < b["s"] - 8 or s > b["e"] + 8):
                b["y2"] = y; b["s"] = min(b["s"], s); b["e"] = max(b["e"], e)
                b["n"] += 1
                break
        else:
            merged.append({"y1": y, "y2": y, "s": s, "e": e, "n": 1})
    merged = [b for b in merged
              if 3 <= b["n"] <= 20 and b["e"] - b["s"] >= 0.45 * pitch]
    bars = {}
    for b in merged:
        yc = (b["y1"] + b["y2"]) // 2
        key = next((k for k in bars if abs(k - yc) <= 8), None)
        if key is None:
            bars[yc] = []; key = yc
        bars[key].append((b["s"], b["e"]))
    return {k: sorted(v) for k, v in bars.items()}


def _group_scalar(values, gap):
    out, cur = [], []
    for v in sorted(values):
        if cur and v - cur[-1] > gap:
            out.append(int(np.mean(cur))); cur = []
        cur.append(v)
    if cur:
        out.append(int(np.mean(cur)))
    return out


def row_grid(rules):
    """Row separators -> row bands [(top, bottom), ...]."""
    if len(rules) < 3:
        return []
    med = np.median(np.diff(rules))
    bands = []
    prev = rules[0] - med
    for r in rules:
        bands.append((int(prev), int(r)))
        prev = r
    return [b for b in bands if 20 < b[1] - b[0] < med * 2.4]


def split_stacked_letters(img, x80, pitch, bands, dark_thresh):
    """A washed-out rule between two RATED rows merges them into one
    tall band whose letter window shows TWO stacked glyphs (seen live:
    Nordel + Polybutadiene, both R). A wrapped two-line label has at
    most ONE glyph, so bands are split only on clear two-glyph
    evidence, at the inter-glyph gap."""
    if not bands:
        return bands
    med = float(np.median([b[1] - b[0] for b in bands]))
    lo, hi = int(x80 - 1.5 * pitch), int(x80 - 0.45 * pitch)
    out = []
    for b in bands:
        if b[1] - b[0] >= 1.6 * med:
            win = (img[b[0]:b[1], lo:hi] < dark_thresh)
            full = win.mean(axis=0) > 0.85
            win = win & ~full[None, :]
            rp = (win.sum(axis=1) >= 3)
            blocks = [(s, e) for s, e in _runs(rp, 1) if e - s >= 15]
            if len(blocks) == 2 and blocks[1][0] - blocks[0][1] >= 8:
                cut = b[0] + (blocks[0][1] + blocks[1][0]) // 2
                out.append((b[0], cut))
                out.append((cut, b[1]))
                continue
        out.append(b)
    return out


# ── letters ──────────────────────────────────────────────────────────
def letter_info(img, x80, pitch, band, dark_thresh):
    """Letter presence in the white 60F column for one row band.
    Returns (pixel count, glyph span, glyph stem).

    A real rating glyph (E/G/S/U/R) at 300 DPI is a CONTIGUOUS block of
    ~20-35 occupied columns (span) containing a vertical stroke ~30px
    tall (stem). The false positives seen in the wild are nothing like
    that: broken border-rule fragments are 1-3 columns wide, and
    stripe-bleed smears are wide but only 2-3px tall. Only full-height
    border rules are excluded (>0.85), so a letter's own stroke can
    never be eaten by the border filter."""
    lo, hi = int(x80 - 1.5 * pitch), int(x80 - 0.45 * pitch)
    win = (img[band[0]:band[1], lo:hi] < dark_thresh)
    if win.size == 0:
        return 0, 0, 0
    full = win.mean(axis=0) > 0.85       # full-height border rules only
    win = win & ~full[None, :]
    px = int(win.sum())
    col = win.sum(axis=0)
    occ = col >= 3
    best_len = best_stem = cur = start = 0
    for i, o in enumerate(occ):
        if o:
            if cur == 0:
                start = i
            cur += 1
            if cur > best_len:
                best_len = cur
                best_stem = int(col[start:i + 1].max())
        else:
            cur = 0
    return px, best_len, best_stem


def gap_regions(segs, pitch):
    """Gaps between consecutive bar segments wide enough for a letter."""
    gaps = []
    for (s1, e1), (s2, e2) in zip(segs, segs[1:]):
        if 0.4 * pitch < s2 - e1 < 2.5 * pitch:
            gaps.append((e1, s2))
    return gaps


def union_intervals(segs, max_gap):
    """Merge overlapping/nearly-touching x-intervals; keep real gaps."""
    out = []
    for s, e in sorted(segs):
        if out and s - out[-1][1] <= max_gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def is_header_band(img, band, x80, pitch, n_cols, dark_thresh):
    """Temperature-header bands (rotated column digits, or the F/C
    mini-header whose '60' lands in the letter window).

    Header signature, measured at a FIXED ink threshold (gray stripes
    bleed into the page threshold on light pages): a STRONG dark
    cluster (>=40 px — full digits, not descender bleed) at >=75% of
    column centers, with no contiguous run longer than ~3.5 columns.
    Data rows can't fake it: letter-only rows have one strong center;
    a bar strong at 75% of centers is a long contiguous run (rule
    wobble inside a band also makes a long run, never short strong
    clusters at every center)."""
    strip = img[band[0]:band[1], :] < min(dark_thresh, 130)
    strong = 0
    for k in range(n_cols):
        xc = int(x80 + (k - 1) * pitch)
        if 0 <= xc - 8 and xc + 8 < strip.shape[1] and \
                strip[:, xc - 8:xc + 8].sum() >= 40:
            strong += 1
    if strong < 0.75 * n_cols:
        return False
    # Discriminate on glyph HEIGHT at the column centers: rotated axis
    # digits are TALL (span most of the band) at nearly every column;
    # a bar is a thin streak (~20% of band height) and a rule thinner
    # still, so neither can fake tallness across half the columns.
    # (Run-length tests fail both ways on crisp scans: digit columns
    # merge into long projected runs, and the axis rule inside the
    # band gives long single-scanline runs.)
    core = strip[6:-6] if strip.shape[0] > 18 else strip
    h = core.shape[0]
    tall = 0
    for k in range(n_cols):
        xc = int(x80 + (k - 1) * pitch)
        if xc - 8 < 0 or xc + 8 >= core.shape[1]:
            continue
        ys = np.where(core[:, xc - 8:xc + 8].any(axis=1))[0]
        if len(ys) and ys[-1] - ys[0] >= 0.5 * h:
            tall += 1
    return tall >= 0.5 * n_cols


# ── per-page pixel pass ──────────────────────────────────────────────
def pixel_pass(img, dpi_scale=1.0):
    """Full geometric read of one page. Returns dict or None (no chart)."""
    img, angle = deskew(img)
    cal = calibrate(img)
    if cal is None:
        return None
    x80, pitch, n_stripes = cal
    n_cols = 26 if n_stripes >= 12 else 21
    t_max = 560 if n_cols == 26 else 460
    # adaptive ink threshold: even pages are lighter
    cands = []
    for dt in (100, 130, 155, 175):
        r = pitch_clean(rule_ys(img, x80, pitch, dt))
        cands.append((dt, r))
    # a crisp low threshold that already finds a full grid wins;
    # escalate only when no threshold reaches a plausible row count
    full = next(((dt, r) for dt, r in cands if len(r) >= 30), None)
    if full:
        dark_thresh, rules = full
    else:
        best_n = max(len(r) for _, r in cands)
        dark_thresh, rules = next((dt, r) for dt, r in cands
                                  if len(r) >= best_n - 1)
    # rule-grid healing: scanner banding can wash out a few row rules
    # at the bar threshold, leaving 2-3-row holes whose rows would be
    # silently LOST (row_grid drops oversize bands). Rules live in the
    # label zone, which the gray stripes never reach, so rules alone
    # may be re-detected at a higher threshold; bars and letters keep
    # the stripe-safe threshold. Guard: the healed grid must keep the
    # same row pitch (median gap) — otherwise text lines were picked
    # up as rules and the healed set is rejected.
    def _holes(rs):
        if len(rs) < 3:
            return True
        g = np.diff(rs)
        return bool((g > 2.5 * np.median(g)).any())

    def _med(rs):
        return float(np.median(np.diff(rs))) if len(rs) >= 3 else 0.0

    # row pitch is ~1.2-1.5x the stripe pitch; outside [1.0, 1.9]x the
    # grid is implausible (missed rules, or text lines faking rules)
    def _plausible(rs):
        m = _med(rs)
        return 1.0 * pitch <= m <= 1.9 * pitch

    # Heal when the grid has holes, is implausibly SPARSE (washed-out
    # scans: faint 1px rules vanish below dt~230 — seen on whole files
    # scanned lighter), or has the wrong pitch. Candidates escalate
    # well past the bar threshold: rules live in the label zone where
    # gray stripes never reach, so high dt is safe for rules only.
    if _holes(rules) or len(rules) < 22 or not _plausible(rules):
        med0 = _med(rules)
        base_ok = _plausible(rules) and len(rules) >= 22

        def _subgaps(rs):
            g = np.diff(rs)
            return int((g < 0.85 * np.median(g)).sum())

        # NOTE: _holes is NOT an acceptance criterion — legitimate
        # section breaks (blank rows between table blocks) read as
        # "holes". Candidates must be plausible, and when the base
        # grid is healthy they must keep its pitch (near-paper
        # thresholds add phantom rules that shrink the median).
        # Score: more rules good (missing rules merge rows), sub-pitch
        # gaps bad at double weight (phantom rules split rows); lowest
        # threshold wins ties.
        scored = []
        if base_ok:
            scored.append((len(rules) - 2 * _subgaps(rules), 0, rules))
        for i, dt2 in enumerate((200, 215, 230, 245, 248, 250, 252), 1):
            r2 = pitch_clean(rule_ys(img, x80, pitch, dt2))
            if len(r2) < 22 or not _plausible(r2):
                continue
            if base_ok and not (0.95 * med0 <= _med(r2) <= 1.10 * med0):
                continue
            scored.append((len(r2) - 2 * _subgaps(r2), -i, r2))
        if scored:
            scored.sort(key=lambda t: (-t[0], -t[1]))
            rules = scored[0][2]
    bars = horizontal_features(img, x80, pitch, dark_thresh, rules)
    bands = row_grid(rules)
    bands = split_stacked_letters(img, x80, pitch, bands, dark_thresh)
    rows = []
    for band in bands:
        letter_px, glyph_span, glyph_stem = letter_info(
            img, x80, pitch, band, dark_thresh)
        segs = []
        for yc, ss in bars.items():
            if band[0] < yc <= band[1]:
                segs.extend(ss)
        segs = union_intervals(segs, max_gap=0.35 * pitch)
        # Split bars at IN-LINE transition letters. Crisp scans print
        # the letter touching the bar on both sides, so the dark run
        # is continuous and gap-based splitting finds nothing (seen:
        # Aluminum in acetic acid, G—S—U read as one G bar). A letter
        # is a TALL ink intrusion (~30px) on a thin bar (~10px): cut
        # the segment at every tall run and record it as a transition
        # site. Also detect a TRAILING letter just past the bar's end
        # ("U" with no bar after = unsatisfactory above that temp).
        trailing = None
        if segs:
            bstrip = img[band[0]:band[1], :] < dark_thresh
            h = band[1] - band[0]
            thr = 0.33 * min(h, 1.45 * pitch)
            def _tall_runs(x0, x1):
                """Glyph clusters: columns of tall ink (a letter stroke
                is ~2.5x the bar's thickness), strokes closed into one
                cluster per letter, then width-filtered so the 1-3px
                stripe-edge verticals of crisp scans can't qualify."""
                x0, x1 = int(max(x0, 0)), int(min(x1, bstrip.shape[1]))
                if x1 - x0 < 6:
                    return []
                cols = bstrip[:, x0:x1]
                ext = np.zeros(x1 - x0, int)
                for j in range(x1 - x0):
                    ys = np.where(cols[:, j])[0]
                    if len(ys):
                        ext[j] = ys[-1] - ys[0]
                # glyph columns are tall but NOT full-band (grid /
                # stripe-edge verticals are), and a letter stroke is
                # >=4px wide (stripe edges are 1-3px): both filters,
                # or pages whose stripe edges scan dark shred every
                # bar into phantom "letters"
                tall = (ext >= thr) & (ext <= 0.85 * h)
                merged = []
                for a, b in _runs(tall, 4):
                    if merged and a - merged[-1][1] <= 0.45 * pitch:
                        merged[-1][1] = b
                    else:
                        merged.append([a, b])
                return [(x0 + a, x0 + b) for a, b in merged
                        if b - a >= 10]
            cut, last_glyph, last_union_end = [], None, None
            for s, e in segs:
                # scan THROUGH the segment end: a trailing letter whose
                # ink touches the bar is merged into the segment, so a
                # window clipped at e-4 cuts its cluster below the
                # width floor
                spots = _tall_runs(s + 4, e + 2)
                cur = s
                for a, b in spots:
                    if a - cur >= 0.25 * pitch:
                        cut.append((cur, a - 2))
                    cur = b + 2
                    last_glyph = (a, b)
                    last_union_end = e
                if e - cur >= 0.75 * pitch:
                    cut.append((cur, e))
                    last_glyph = None   # real bar continues past glyph
            if cut:
                segs = cut
            if last_glyph is not None and segs:
                # the bar ENDS at that letter: it is the rating above
                # that point, not a mid-bar transition. Keep the
                # UN-CUT end too: if vision rejects the letter as a
                # phantom, the bar must get its true end back —
                # dropping only the letter would silently shorten it.
                trailing = {"x0": segs[-1][1], "x1": last_glyph[0],
                            "union_end": last_union_end}
            else:
                # gap-style trailing letter: bar ends, small gap, then
                # a lone letter within 1.6 col-pitches
                chart_r = x80 + (n_cols - 1) * pitch + 0.5 * pitch
                e_last = segs[-1][1]
                tail = _tall_runs(e_last + 4, min(e_last + 1.6 * pitch,
                                                  chart_r))
                if tail:
                    trailing = {"x0": e_last, "x1": tail[0][0]}
        flags = []
        has_letter = (letter_px >= 55 and glyph_span >= 10
                      and glyph_stem >= 12)
        # header check for ANY candidate row: the rotated temp digits
        # also land in the letter window ("60" reads as a glyph), on
        # rows that carry no bar segments at all
        # solid chart-furniture band (the black corrodent title bar):
        # a data bar is a thin line in its band (~15-20% dark fill);
        # the title bar is a tall solid block (>45%). High-res scans
        # resolve its edges into "rules", so it can land in row_grid.
        if segs or has_letter:
            blk = img[band[0]:band[1],
                      int(x80 - pitch):int(x80 + (n_cols - 1) * pitch)]
            if blk.size and float((blk < 130).mean()) > 0.45:
                rows.append({"band": band, "letter_px": 0,
                             "has_letter": False, "segments": [],
                             "transitions": [], "n_bar_segs": 0,
                             "pixel_flags": [], "is_header": True})
                continue
        if (segs or has_letter) and \
                is_header_band(img, band, x80, pitch, n_cols, dark_thresh):
            rows.append({"band": band, "letter_px": 0, "has_letter": False,
                         "segments": [], "transitions": [], "n_bar_segs": 0,
                         "pixel_flags": [], "is_header": True})
            continue
        if len(segs) > 4:            # header junk / smudge storm
            flags.append(f"{len(segs)} segments in one row — not a data row")
            segs = []
        seg_temps, trans = [], []
        prev_e = None
        for i, (s, e) in enumerate(segs):
            t_end = min(snap_end(temp_at(e, x80, pitch)), t_max)
            if i == 0:
                t_start = 60
            else:
                t_start = snap_transition(temp_at((prev_e + s) / 2, x80, pitch))
                trans.append({"x0": prev_e, "x1": s, "temp": t_start})
            seg_temps.append([t_start, t_end])
            prev_e = e
        for i in range(len(seg_temps) - 1):
            seg_temps[i][1] = seg_temps[i + 1][0]
        bad = [st for st in seg_temps if st[1] < st[0]]
        if bad:
            flags.append(f"reversed segment(s) {bad}")
        trail_temp, trail_restore = None, None
        if trailing is not None:
            trail_temp = snap_transition(temp_at(
                (trailing["x0"] + trailing["x1"]) / 2, x80, pitch))
            if trailing.get("union_end"):
                trail_restore = min(snap_end(temp_at(
                    trailing["union_end"], x80, pitch)), t_max)
        rows.append({"band": band, "letter_px": letter_px,
                     "has_letter": has_letter,
                     "segments": seg_temps, "transitions": trans,
                     "trailing_temp": trail_temp,
                     "trailing_restore": trail_restore,
                     "n_bar_segs": len(segs), "pixel_flags": flags})
    rows = [r for r in rows if not r.get("is_header")]
    return {"x80": x80, "pitch": pitch, "n_stripes": n_stripes,
            "n_cols": n_cols, "t_max": t_max, "skew": angle,
            "dark_thresh": dark_thresh, "rows": rows, "img": img}


# ── vision pass ──────────────────────────────────────────────────────
VISION_PROMPT = """You are reading ONE scanned page of Schweitzer's \
Corrosion Resistance Tables. The page is a chart: a corrodent name in \
the black header bar, a left column of material names (some are section \
headers or blank rows), a rating letter column (E/G/S/U for metals, R/U \
for nonmetallics), and horizontal temperature bars. Some bars are \
interrupted by a letter — that letter is the rating AFTER that point.

Geometry info measured from the pixels (trust it): this page has \
{n_rows} data rows (top to bottom). Row i has a rating letter: \
{letter_flags}. Rows with in-bar transition letters (count per row): \
{gap_counts}.

Call the report_page tool with: the chemical (header name exactly as
printed, incl. concentration), the page_type, and every row — label,
section, letter (null for blank rows), gap_letters (in-bar transition
letters left-to-right, empty list if none), footnotes (digits/SAT/ELC
printed after the name, or empty).

The rows list should have about {n_rows} entries in top-to-bottom order \
(include rows whose letter is null). If your own count of the page's \
rows differs from {n_rows}, TRUST THE IMAGE and return every row you \
see — the caller reconciles counts. Every ruled line of the table is \
its own row: material names with similar beginnings separated by a \
rule line (e.g. several 'Ethylene-Propylene ...' entries) are SEPARATE \
rows. Only when a name wraps onto a second line INSIDE the same ruled \
row (no rule between the lines) do you join the lines into one label. Report via the report_page tool. A row that is a section header \
(e.g. 'Stainless Steels', 'Coatings', 'Mortars', 'Polyesters', \
'Fabrics') gets section='header' and letter=null."""


VISION_TOOL = {
    "name": "report_page",
    "description": "Report the structured contents of this chart page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "chemical": {"type": "string",
                         "description": "Header name exactly as printed, "
                                        "including concentration"},
            "page_type": {"type": "string",
                          "enum": ["metals", "nonmetallics_coatings_mortars",
                                   "plastics", "elastomers"]},
            "rows": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "section": {"type": "string",
                                "enum": ["Metals", "Nonmetallic", "Coatings",
                                         "Mortars", "Plastics", "Elastomers",
                                         "Fabrics", "header"]},
                    "letter": {"type": ["string", "null"],
                               "enum": ["E", "G", "S", "U", "R", None]},
                    "gap_letters": {"type": "array",
                                    "items": {"type": "string"}},
                    "footnotes": {"type": "string"}
                },
                "required": ["label", "section", "letter"]}}
        },
        "required": ["chemical", "page_type", "rows"]
    }
}


def vision_pass(client, model, png_bytes, pix):
    letter_flags = [r["has_letter"] for r in pix["rows"]]
    # a measured trailing letter counts as a gap letter for the hint,
    # but the model is told to trust the image over these counts
    gap_counts = [len(r["transitions"]) +
                  (1 if r.get("trailing_temp") else 0)
                  for r in pix["rows"]]
    prompt = VISION_PROMPT.format(n_rows=len(pix["rows"]),
                                  letter_flags=letter_flags,
                                  gap_counts=gap_counts)
    msg = client.messages.create(
        model=model, max_tokens=8000,
        tools=[VISION_TOOL],
        tool_choice={"type": "tool", "name": "report_page"},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/png",
             "data": base64.b64encode(png_bytes).decode()}},
            {"type": "text", "text": prompt}]}])
    for block in msg.content:
        if block.type == "tool_use" and block.name == "report_page":
            return block.input
    raise ValueError(f"vision pass returned no tool call "
                     f"(stop_reason={msg.stop_reason})")


# ── merge + validate ─────────────────────────────────────────────────
def merge(pix, vis, source_file, pdf_page):
    """Combine passes. Alignment anchor: RATED rows (vision letter set,
    pixel letter detected) — spacer bands, headers and blank rows don't
    need geometry, so count noise there must not sink the page."""
    out, review = [], []
    chemical = (vis.get("chemical") or "UNKNOWN").strip()
    vrows = [v for v in (vis.get("rows") or [])
             if (v.get("section") or "") != "header"
             and (v.get("label") or "").strip()]
    v_rated = [v for v in vrows if v.get("letter")]
    p_rated = [p for p in pix["rows"] if p["has_letter"]]

    if len(v_rated) != len(p_rated):
        # SALVAGE by positional alignment: when both passes agree on
        # the TOTAL row count, pair rows by position and drop only the
        # pairs whose rated-status disagrees (one side sees a letter,
        # the other doesn't) — those go to review as single rows, the
        # rest of the page extracts. Only when even the row totals
        # disagree is the page queued whole.
        # Align with section-HEADER rows included: vision reports them
        # and pixel has a band for each header line, so excluding them
        # from one list but not the other shifts the zip and silently
        # mispairs every row below the first header (seen: a dropped
        # "letter dispute" at the header's band, then labels paired to
        # the band above — rows emitted ok but one row off).
        vrows_pos = [v for v in (vis.get("rows") or [])
                     if (v.get("label") or "").strip()]
        # Salvage is positional, so it is only safe when every pixel
        # band is one visual row. A band taller than ~1.6x the median
        # is ambiguous — a 2-line label (one row) and two merged blank
        # rows (a missing rule) have the SAME height, and pairing
        # across the wrong reading silently shifts everything below
        # it (seen: p2 mortars one row off, all conf ok, when vision
        # happened to miscount to the matching total). Queue whole.
        heights = [r["band"][1] - r["band"][0] for r in pix["rows"]]
        uniform = (len(heights) >= 3 and
                   max(heights) <= 1.6 * float(np.median(heights)))
        if uniform and len(vrows_pos) == len(pix["rows"]):
            keep_v, keep_p = [], []
            for v, p in zip(vrows_pos, pix["rows"]):
                if (v.get("section") or "") == "header":
                    if p["has_letter"]:
                        # a header must pair with an unrated band;
                        # letters here mean the alignment is wrong
                        keep_v = None
                        break
                    continue             # aligned furniture — skip pair
                if bool(v.get("letter")) == bool(p["has_letter"]):
                    keep_v.append(v)
                    keep_p.append(p)
                else:
                    review.append(
                        f"{chemical} / {(v.get('label') or '?').strip()}: "
                        f"letter dispute (vision "
                        f"{v.get('letter') or 'blank'!s}, pixel "
                        f"{'letter' if p['has_letter'] else 'no letter'})"
                        " — row queued, rest of page extracted")
            if keep_v is not None:
                vrows = keep_v
                v_rated = [v for v in vrows if v.get("letter")]
                p_rated = [p for p in keep_p if p["has_letter"]]
        if len(v_rated) != len(p_rated):
            review.append(f"rated-row mismatch: vision {len(v_rated)} vs "
                          f"pixel {len(p_rated)} — page queued whole")
            return [], review

    def emit(base, rating, t0, t1, conf, note):
        out.append({**base, "rating": rating, "t0": t0, "t1": t1,
                    "confidence": conf, "note": note})

    # blank rows: vision-only, no geometry needed
    for v in vrows:
        if not v.get("letter"):
            base = dict(chemical=chemical,
                        category=(v.get("section") or "").strip(),
                        material=v["label"].strip(),
                        source_file=source_file, pdf_page=pdf_page,
                        footnotes=(v.get("footnotes") or "").strip())
            emit(base, "ND", "", "", "ok", "no data (blank row)")

    for v, p in zip(v_rated, p_rated):
        label = v["label"].strip()
        letter = v["letter"]
        gaps = v.get("gap_letters") or []
        flags = list(p.get("pixel_flags") or [])
        trail_temp = p.get("trailing_temp")
        n_tr = len(p["transitions"])
        if trail_temp and len(gaps) == n_tr:
            # vision sees no letter beyond the bar — the pixel tail is
            # noise (stripe edge, smudge). Drop it, and give the bar
            # its UN-CUT end back: the phantom glyph also cut the
            # segment, and dropping only the letter would silently
            # shorten the bar (seen: mortars Epoxy 110F read as 70F).
            trail_temp = None
            fix = p.get("trailing_restore")
            if fix and p["segments"]:
                p["segments"][-1][1] = max(p["segments"][-1][1], fix)
        if len(gaps) != n_tr + (1 if trail_temp else 0):
            flags.append(f"gap letters {len(gaps)} vs measured gaps "
                         f"{n_tr + (1 if trail_temp else 0)}")
            trail_temp = None            # counts disagree — don't guess
        seg_ratings = [letter] + list(gaps)
        known = [r for r in seg_ratings if r in RANK]
        if known != sorted(known, key=lambda r: RANK[r]):
            flags.append(f"ratings do not degrade: {seg_ratings}")
        base = dict(chemical=chemical,
                    category=(v.get("section") or "").strip(),
                    material=label, source_file=source_file,
                    pdf_page=pdf_page,
                    footnotes=(v.get("footnotes") or "").strip())
        conf = "review" if flags else "ok"
        note0 = "; ".join(flags)
        segs = p["segments"]
        if letter == "U" and not segs:
            emit(base, "U", "", "", conf,
                 ("unsatisfactory at any temperature; " + note0).strip("; "))
        elif not segs:
            emit(base, letter, 60, 60, conf,
                 ("rated at 60F only; " + note0).strip("; "))
        else:
            for i, (t0, t1) in enumerate(segs):
                r = seg_ratings[i] if i < len(seg_ratings) else "?"
                note = note0 if i == 0 else \
                    (f"rating changes to {r} at {t0}F; " + note0).strip("; ")
                c = conf
                if r == "?":
                    c = "review"
                    note = (note + "; unread gap letter").strip("; ")
                emit(base, r, t0, t1, c, note)
            # trailing letter past the bar's end: the rating ABOVE
            # that temperature, with no bar (e.g. G—S—U: U above).
            # Boundary = where the last bar segment ends, so the rows
            # tile without gap or overlap.
            if trail_temp and len(seg_ratings) == len(segs) + 1:
                r = seg_ratings[-1]
                t_edge = segs[-1][1]
                tnote = ("unsatisfactory above "
                         if r == "U" else f"rated {r} above ")
                emit(base, r, t_edge, "", conf,
                     (f"{tnote}{t_edge}F (no bar beyond); "
                      + note0).strip("; "))
        if flags:
            review.append(f"{chemical} / {label}: {'; '.join(flags)}")
    return out, review


# ── output ───────────────────────────────────────────────────────────
CSV_HEADER = ["chemical", "category", "material", "rating",
              "rating_meaning", "temp_from_f", "temp_to_f", "temp_from_c",
              "temp_to_c", "footnotes", "confidence", "notes", "source",
              "source_file", "pdf_page"]


def write_rows(path, rows, append=True):
    new = not Path(path).exists()
    with open(path, "a" if append else "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        if new or not append:
            w.writerow(CSV_HEADER)
        for r in rows:
            t0, t1 = r["t0"], r["t1"]
            w.writerow([r["chemical"], r["category"], r["material"],
                        r["rating"], RATING_MEANING.get(r["rating"], ""),
                        t0, t1,
                        c_of(t0) if t0 != "" else "",
                        c_of(t1) if t1 != "" else "",
                        r.get("footnotes", ""), r["confidence"], r["note"],
                        SOURCE, r["source_file"], r["pdf_page"]])


def save_overlay(pix, out_path):
    """Annotated PNG for review pages: grid + measured bars."""
    from PIL import Image, ImageDraw
    img = pix["img"]
    rgb = Image.fromarray(img).convert("RGB")
    d = ImageDraw.Draw(rgb)
    x80, pitch = pix["x80"], pix["pitch"]
    for t in range(60, pix["t_max"] + 1, 20):
        x = x80 + (t - 80) / 20 * pitch
        d.line([(x, 0), (x, img.shape[0])], fill=(70, 130, 220), width=1)
    for r in pix["rows"]:
        y = (r["band"][0] + r["band"][1]) // 2
        for t0, t1 in r["segments"]:
            x0 = x80 + (t0 - 80) / 20 * pitch
            x1 = x80 + (t1 - 80) / 20 * pitch
            d.line([(x0, y), (x1, y)], fill=(210, 60, 60), width=2)
    rgb.save(out_path)


# ── main loop ────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--glob", default="*.pdf")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--retry-no-chart", action="store_true",
                    help="re-examine pages previously marked no-chart "
                         "(use after an engine fix recovers faint pages)")
    ap.add_argument("--pixel-only", action="store_true",
                    help="no API calls; geometry test mode")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N data pages (0 = all)")
    ap.add_argument("--env-file", default="",
                    help="optional .env with ANTHROPIC_API_KEY")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "overlays").mkdir(exist_ok=True)
    state_path = out_dir / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}

    client = None
    if not args.pixel_only:
        if args.env_file:
            from dotenv import load_dotenv
            load_dotenv(args.env_file)
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            sys.exit("ANTHROPIC_API_KEY not set (use --env-file or env var)")
        client = anthropic.Anthropic(api_key=key)

    import fitz
    files = sorted(Path(args.input_dir).glob(args.glob))
    log.info("%d PDF files", len(files))
    done = 0
    for pdf in files:
        doc = fitz.open(pdf)
        for pno in range(len(doc)):
            key = f"{pdf.name}#{pno}"
            skip_states = ("done",) if args.retry_no_chart \
                else ("done", "no-chart")
            if state.get(key) in skip_states:
                continue
            img = render(doc, pno, args.dpi)
            pix = pixel_pass(img)
            if pix is None or len(pix["rows"]) < 5:
                state[key] = "no-chart"
                continue
            log.info("%s p.%d: %d stripes, %d rows, skew %.2f, ink<%d",
                     pdf.name, pno + 1, pix["n_stripes"], len(pix["rows"]),
                     pix["skew"], pix["dark_thresh"])
            if args.pixel_only:
                for r in pix["rows"][:6]:
                    log.info("   row band %s letter=%s segs=%s",
                             r["band"], r["has_letter"], r["segments"])
                state[key] = "pixel-only"
            else:
                try:
                    vis = vision_pass(client, args.model,
                                      page_png(img), pix)
                    rows, review = merge(pix, vis, pdf.name, pno + 1)
                    write_rows(out_dir / "corrosion_master.csv", rows)
                    if review:
                        with open(out_dir / "review_queue.csv", "a",
                                  newline="", encoding="utf-8") as f:
                            w = csv.writer(f)
                            for item in review:
                                w.writerow([pdf.name, pno + 1, item])
                        save_overlay(pix, out_dir / "overlays" /
                                     f"{pdf.stem}_p{pno+1}.png")
                    # a page queued WHOLE wrote no data rows — leave it
                    # retryable so a rerun after a fix picks it up
                    state[key] = "review" if (not rows and review) else "done"
                    log.info("   -> %s: %d rows, %d flagged",
                             vis.get("chemical"), len(rows), len(review))
                except Exception:
                    log.exception("   page failed — queued for retry")
                    state[key] = "error"
                time.sleep(0.4)          # be gentle on the API
            state_path.write_text(json.dumps(state, indent=0))
            done += 1
            if args.limit and done >= args.limit:
                log.info("limit reached (%d pages)", done)
                return
        doc.close()
    log.info("finished: %d pages this run", done)


if __name__ == "__main__":
    main()
