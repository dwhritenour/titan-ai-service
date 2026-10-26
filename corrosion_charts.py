"""
corrosion_charts.py — chart-row verification images (Titan AI).

Serves the strip images cut from the Schweitzer Corrosion Resistance
Tables scans by make_corrosion_crops.py: label + rating letter +
temperature bar for one material/chemical, exactly what a person would
check in the book. The image is attached to the chat as a file chip via
the same tai_chat_files path the Excel exports use.

Config (env):
  TITAN_AI_CORROSION_CROPS  folder holding crops_index.csv and crops\
                            (default C:\\corrosion-crops)

INTERNAL USE ONLY: the strips are crops of a copyrighted reference
(Schweitzer, 5th ed.) — verification aids for Titan's purchased copy.
"""
import csv
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("corrosion_charts")

CROPS_DIR = Path(os.environ.get("TITAN_AI_CORROSION_CROPS",
                                r"C:\corrosion-crops"))

CHART_TOOL_NAMES = {"get_corrosion_chart_row"}

_index = None            # list of dicts, loaded lazily


def _load_index():
    global _index
    if _index is not None:
        return _index
    path = CROPS_DIR / "crops_index.csv"
    rows = []
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    _index = rows
    log.info("corrosion crops index: %d rows from %s", len(rows), path)
    return _index


def chart_tools_for_anthropic():
    return [{
        "name": "get_corrosion_chart_row",
        "description": (
            "Attach the actual chart-row image from the Schweitzer "
            "Corrosion Resistance Tables (the book's printed bar for one "
            "material under one chemical) to the chat as a visual "
            "verification of a corrosion-compatibility answer. Use it "
            "AFTER answering a corrosion question from the database, so "
            "the user can see the book's own bar. Internal use only."),
        "input_schema": {
            "type": "object",
            "properties": {
                "chemical": {"type": "string",
                             "description": "Chemical / corrodent name as "
                             "in the corrosion data, e.g. 'ALUM AMMONIUM'"},
                "material": {"type": "string",
                             "description": "Material name, e.g. "
                             "'Stainless Type 316/316L'"},
            },
            "required": ["chemical", "material"],
        },
    }]


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _match(rows, field, query):
    q = _norm(query)
    exact = [r for r in rows if _norm(r[field]) == q]
    if exact:
        return exact, True
    sub = [r for r in rows if q in _norm(r[field]) or _norm(r[field]) in q]
    return sub, False


def handle(db_module, session_id, args):
    rows = _load_index()
    if not rows:
        return json.dumps({"error": (
            "No chart-row images are available on this server yet "
            "(crops_index.csv not found). Answer from the database and "
            "cite the source file and page instead.")})

    chem_rows, _ = _match(rows, "chemical", args.get("chemical", ""))
    if not chem_rows:
        chems = sorted({r["chemical"] for r in rows})
        near = [c for c in chems
                if _norm(args.get("chemical", ""))[:6] in _norm(c)][:10]
        return json.dumps({"error": "chemical not found in the chart index",
                           "closest_chemicals": near or chems[:10]})

    mat_rows, _ = _match(chem_rows, "material", args.get("material", ""))
    if not mat_rows:
        mats = sorted({r["material"] for r in chem_rows})
        return json.dumps({"error": "material not found for that chemical "
                           "(it may be ND — no data — rows have no bar)",
                           "chemical": chem_rows[0]["chemical"],
                           "materials_with_chart_rows": mats})

    hit = mat_rows[0]
    png = CROPS_DIR / "crops" / hit["crop_file"]
    if not png.exists():
        return json.dumps({"error": f"crop file missing: {hit['crop_file']}"})

    blob = png.read_bytes()
    nice = re.sub(r"[^A-Za-z0-9 ().,%/-]+", "",
                  f"{hit['chemical']} - {hit['material']} (book chart row)")
    filename = nice[:120] + ".png"
    file_id = db_module.insert_export_file(session_id, filename, blob)
    db_module.insert_file_message(session_id, file_id, filename)
    log.info("chart row attached: %s (%d bytes, file_id %s)",
             filename, len(blob), file_id)
    return json.dumps({
        "attached": True,
        "chemical": hit["chemical"],
        "category": hit["category"],
        "material": hit["material"],
        "source": f"Corrosion Resistance Tables 5th ed. — "
                  f"{hit['source_file']}, PDF page {hit['pdf_page']}",
        "note": ("The chart-row image is now attached to the chat as a "
                 "file chip. Tell the user it shows the book's printed "
                 "bar for this material; do not repeat the filename."),
        "others_matching": len(mat_rows) - 1,
    })
