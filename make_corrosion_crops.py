#!/usr/bin/env python3
"""
make_corrosion_crops.py — chart-row verification images.   v1.0, 2026-10-12

Post-pass over the Schweitzer scans AFTER extract_corrosion_tables.py has
built corrosion_master.csv. For every RATED row in the master (anything
that is not ND), re-measures the page with the same pixel engine (no API,
no cost) and crops the strip a human would check with a straightedge:
label + rating letter + temperature bar.

Alignment is the same invariant the extractor enforced at extraction
time: rated materials in CSV order == rated bands top-to-bottom. Pages
where the counts disagree (e.g. master rows from an older extractor
version) are skipped and logged — never guessed.

Usage:
  python make_corrosion_crops.py --input-dir "C:\\chemical_compatibility"
      --master C:\\corrosion-out\\corrosion_master.csv
      --out C:\\corrosion-crops [--dpi 300] [--limit N]

Outputs:
  <out>\\crops\\<chemical>__<category>__<material>.png
  <out>\\crops_index.csv   (chemical, category, material, crop_file,
                            source_file, pdf_page)  — bulk-load this
  <out>\\crops_review.csv  (pages skipped and why)
  <out>\\crops_state.json  (resume; rerun the same command any time)

Keep the output internal: the strips are crops of a copyrighted book
(Schweitzer, 5th ed.) — verification aids for Titan's purchased copy.
Place this script NEXT TO extract_corrosion_tables.py (it imports the
pixel engine from it).
"""
import argparse
import csv
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fitz  # PyMuPDF
from PIL import Image

import extract_corrosion_tables as X

log = logging.getLogger("crops")

INDEX_HEADER = ["chemical", "category", "material", "crop_file",
                "source_file", "pdf_page"]


def slug(s, maxlen=60):
    s = re.sub(r"[^A-Za-z0-9]+", "-", s.strip()).strip("-")
    return (s[:maxlen].rstrip("-") or "x").lower()


def rated_sequence(rows):
    """Master-CSV rows for one page -> rated (chemical, category,
    material) in first-appearance order. Consecutive duplicate materials
    (multi-segment transitions) collapse to one entry."""
    seq = []
    for r in rows:
        if r["rating"] == "ND":
            continue
        key = (r["chemical"], r["category"], r["material"])
        if not seq or seq[-1] != key:
            seq.append(key)
    return seq


def crop_band(img, pix, band):
    x_left = max(0, int(pix["x80"] - 16 * pix["pitch"]))
    x_right = min(img.shape[1] - 1,
                  int(pix["x80"] + (pix["n_cols"] - 0.5) * pix["pitch"] + 6))
    y0 = max(0, band[0] - 3)
    y1 = min(img.shape[0], band[1] + 3)
    return img[y0:y1, x_left:x_right]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--master", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--limit", type=int, default=0, help="max pages this run")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    out_dir = Path(args.out)
    crops_dir = out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "crops_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}

    # master rows grouped by (source_file, pdf_page), CSV order preserved
    pages = defaultdict(list)
    with open(args.master, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pages[(r["source_file"], int(r["pdf_page"]))].append(r)

    index_path = out_dir / "crops_index.csv"
    new_index = not index_path.exists()
    idx_f = open(index_path, "a", newline="", encoding="utf-8")
    idx_w = csv.writer(idx_f)
    if new_index:
        idx_w.writerow(INDEX_HEADER)

    rev_path = out_dir / "crops_review.csv"
    docs = {}
    done = 0
    n_crops = 0
    for (src, pno1), rows in sorted(pages.items()):
        key = f"{src}#{pno1}"
        if state.get(key) == "done":
            continue
        seq = rated_sequence(rows)
        if not seq:
            state[key] = "done"          # ND-only page: nothing to crop
            continue
        if src not in docs:
            pdf_path = Path(args.input_dir) / src
            if not pdf_path.exists():
                log.warning("missing PDF %s — skipped", src)
                continue
            docs[src] = fitz.open(pdf_path)
        img = X.render(docs[src], pno1 - 1, args.dpi)
        pix = X.pixel_pass(img)
        if pix is None:
            state[key] = "review"
            with open(rev_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([src, pno1, "no chart found"])
            continue
        bands = [r["band"] for r in pix["rows"] if r["has_letter"]]
        if len(bands) != len(seq):
            state[key] = "review"
            with open(rev_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(
                    [src, pno1, f"rated bands {len(bands)} vs master "
                     f"materials {len(seq)} — page skipped"])
            log.warning("%s p.%d: band/material count mismatch "
                        "(%d vs %d) — skipped", src, pno1,
                        len(bands), len(seq))
            continue
        for band, (chem, cat, mat) in zip(bands, seq):
            name = f"{slug(chem)}__{slug(cat, 20)}__{slug(mat)}.png"
            target = crops_dir / name
            n = 2
            while target.exists():
                target = crops_dir / name.replace(".png", f"_{n}.png")
                n += 1
            Image.fromarray(crop_band(img, pix, band)).save(target)
            idx_w.writerow([chem, cat, mat, target.name, src, pno1])
            n_crops += 1
        state[key] = "done"
        done += 1
        if done % 10 == 0:
            idx_f.flush()
            state_path.write_text(json.dumps(state, indent=0))
            log.info("%d pages cropped (%d strips)", done, n_crops)
        if args.limit and done >= args.limit:
            log.info("limit reached")
            break
    idx_f.close()
    state_path.write_text(json.dumps(state, indent=0))
    log.info("DONE: %d pages, %d crops -> %s", done, n_crops, crops_dir)


if __name__ == "__main__":
    main()
