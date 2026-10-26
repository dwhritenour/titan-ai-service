"""
spec_sheets.py — Titan spec-sheet library for the Titan AI agent.

Extracts text + dimension grids from the product spec-sheet PDFs in
SPEC_SHEETS_DIR (C:\\spec_sheets — same box as this service), caches
the result, and exposes three NATIVE tools the agent can call
alongside the nexus-mcp-server tools:

    list_spec_sheets()          -> every sheet: filename, model line
    get_spec_sheet(model)       -> one sheet's full extracted content
    search_spec_sheets(query)   -> ranked page hits across all sheets

Design notes (proven against samples 2026-08-06):
- Sheets are 2-page text PDFs: page 1 = features/ratings,
  page 2 = bill of materials + DIMENSIONS grid.
- The dimension grids have NO ruling lines, so pdfplumber's default
  table finder misses them. Recipe: locate the 'DIMENSION' header via
  extract_words, crop below it, extract with text-alignment strategy.
- Filenames are model families (YS12-CI, CV91-SS, BS55_65-CI) — the
  same vocabulary users ask in, so get_spec_sheet matches loosely on
  the filename.
- Extraction is cached in spec_cache.json keyed by file mtime; drop a
  new/updated PDF in the folder and the next service restart (or
  cache refresh) picks it up.
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("titan-ai.specs")

_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "snap_tolerance": 4,
    "join_tolerance": 4,
}

SPEC_TOOL_NAMES = {"list_spec_sheets", "get_spec_sheet", "search_spec_sheets"}


def spec_tools_for_anthropic():
    """Anthropic tool schemas for the three spec tools."""
    return [
        {
            "name": "list_spec_sheets",
            "description": (
                "List every document in the Titan product literature "
                "library: product spec sheets PLUS marketing/positioning "
                "documents, screen references, and other collateral. Use "
                "this when unsure which document covers a product or topic."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_spec_sheet",
            "description": (
                "Get the FULL extracted content of one Titan spec sheet: "
                "features, pressure/temperature ratings, bill of materials, "
                "and the DIMENSIONS & PERFORMANCE grid (face-to-face, "
                "center-line, weights, Cv, etc. by size). Prefer this for "
                "any question about a specific model (e.g. 'face-to-face "
                "for a 2 inch YS61-CS' -> model 'YS61-CS'). Matching is "
                "forgiving: 'YS61-CS', 'ys61', 'YS 61 CS' all work."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Model / filename to fetch, e.g. 'YS61-CS' or 'CV91-SS'",
                    }
                },
                "required": ["model"],
            },
        },
        {
            "name": "search_spec_sheets",
            "description": (
                "Keyword-search across ALL Titan product literature (spec "
                "sheets AND marketing/positioning docs) and return the "
                "best-matching pages. Use for cross-product questions "
                "('which strainers are rated 600 PSI'), application/market "
                "questions ('AI factories', 'data center cooling'), or when "
                "the model name is unknown. For a known model, prefer "
                "get_spec_sheet."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms, e.g. 'buna-n gasket class 300'",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max page hits to return (default 5)",
                    },
                },
                "required": ["query"],
            },
        },
    ]


def _grid_to_markdown(table):
    """Render an extracted table (list of rows) as a compact grid."""
    lines = []
    for row in table:
        cells = [(c or "").replace("\n", " ").strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _extract_pdf(path):
    """Extract one spec sheet. Returns dict with pages + dimension grids."""
    import pdfplumber  # imported lazily so the service runs without it if specs are disabled

    pages = []
    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""

            # Dimension grid recipe: crop below the DIMENSION header and
            # use text-alignment table detection (grids have no ruling
            # lines). Falls back silently if the header isn't on the page.
            grids = []
            try:
                words = page.extract_words()
                dim_y = next(
                    (w["top"] for w in words
                     if w["text"].upper().startswith("DIMENSION")),
                    None,
                )
                if dim_y is not None:
                    crop = page.crop(
                        (0, dim_y, page.width, page.height)
                    )
                    for table in crop.extract_tables(_TABLE_SETTINGS):
                        md = _grid_to_markdown(table)
                        if md.count("\n") >= 2:  # ignore trivial fragments
                            grids.append(md)
            except Exception as exc:  # a bad grid never sinks the page text
                log.warning("Grid extraction failed for %s p%s: %s",
                            path.name, page_num, exc)

            pages.append({"page": page_num, "text": text, "grids": grids})

    # Model line: best-effort grab for the listing. Overlapping vertical
    # text can pollute the MODEL: line ("CV 91-SS D E S S T IG..."), so
    # match just the model-code shape and stop there.
    joined = "\n".join(p["text"] for p in pages)
    m = re.search(
        r"MODEL[S]?\s*:\s*([A-Z]{2,4}\s?\d{2,4}[A-Z0-9/\-]*(?:-[A-Z]{1,3})?)",
        joined, re.IGNORECASE)
    model_line = m.group(1).strip() if m else path.stem
    return {
        "file": path.name,
        "model_line": model_line,
        "title": "",
        "pages": pages,
    }


def _norm(s):
    """Normalize a model string for matching: YS 61-CS -> ys61cs."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class SpecLibrary:
    def __init__(self, folder, cache_path):
        self.folder = Path(folder)
        self.cache_path = Path(cache_path)
        self.sheets = {}   # filename -> extracted dict
        self._mtimes = {}  # filename -> mtime used for cache validity

    # ── indexing ─────────────────────────────────────────────────────

    def refresh(self):
        """(Re)extract any new or changed PDFs; drop deleted ones."""
        if not self.folder.exists():
            log.warning("Spec sheet folder %s not found — spec tools return empty",
                        self.folder)
            self.sheets = {}
            return 0

        cached = {}
        if self.cache_path.exists():
            try:
                cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                cached = {}

        found = {}
        changed = 0
        for pdf in sorted(self.folder.glob("*.pdf")):
            mtime = pdf.stat().st_mtime
            entry = cached.get(pdf.name)
            if entry and entry.get("_mtime") == mtime:
                found[pdf.name] = entry
                continue
            try:
                data = _extract_pdf(pdf)
                data["_mtime"] = mtime
                found[pdf.name] = data
                changed += 1
                log.info("Extracted spec sheet %s (%s page(s))",
                         pdf.name, len(data["pages"]))
            except Exception as exc:
                log.error("Failed to extract %s: %s", pdf.name, exc)

        self.sheets = found
        if changed or set(found) != set(cached):
            try:
                self.cache_path.write_text(
                    json.dumps(found), encoding="utf-8")
            except Exception as exc:
                log.warning("Could not write spec cache: %s", exc)
        return len(found)

    # ── tool implementations ────────────────────────────────────────

    def list_sheets(self):
        rows = []
        for name in sorted(self.sheets):
            s = self.sheets[name]
            rows.append({
                "file": name,
                "model": s.get("model_line") or name.replace(".pdf", ""),
            })
        return {"count": len(rows), "spec_sheets": rows}

    def get_sheet(self, model):
        if not self.sheets:
            return {"error": "No spec sheets are loaded on the server."}
        want = _norm(model)
        # score filenames + model lines for the closest match
        best, best_score = None, 0
        for name, s in self.sheets.items():
            candidates = [_norm(name.replace(".pdf", "")),
                          _norm(s.get("model_line", ""))]
            for c in candidates:
                if not c:
                    continue
                if want == c:
                    score = 100
                elif want in c or c in want:
                    score = 50 + min(len(want), len(c))
                else:
                    continue
                if score > best_score:
                    best, best_score = name, score
        if best is None:
            available = ", ".join(sorted(n.replace(".pdf", "") for n in self.sheets))
            return {"error": f"No spec sheet matches '{model}'. "
                             f"Available: {available}"}
        s = self.sheets[best]
        out = [f"SPEC SHEET: {best}  (model line: {s.get('model_line','')})"]
        for p in s["pages"]:
            out.append(f"\n===== PAGE {p['page']} =====\n{p['text']}")
            for i, g in enumerate(p["grids"], start=1):
                out.append(
                    f"\n----- PAGE {p['page']} DIMENSION GRID {i} "
                    f"(columns are sizes; read row labels carefully) -----\n{g}")
        return {"file": best, "content": "\n".join(out)}

    def search(self, query, max_results=5):
        if not self.sheets:
            return {"error": "No spec sheets are loaded on the server."}
        terms = [t for t in re.split(r"[^a-z0-9/\.\"]+", (query or "").lower()) if t]
        if not terms:
            return {"error": "Empty query."}
        hits = []
        for name, s in self.sheets.items():
            for p in s["pages"]:
                hay = (p["text"] + "\n" + "\n".join(p["grids"])).lower()
                score = sum(hay.count(t) for t in terms)
                # small bonus when the filename itself matches a term
                score += sum(5 for t in terms if t in _norm(name))
                if score > 0:
                    hits.append((score, name, p))
        hits.sort(key=lambda h: -h[0])
        results = []
        for score, name, p in hits[: max_results or 5]:
            preview = p["text"][:600]
            results.append({
                "file": name, "page": p["page"], "score": score,
                "preview": preview,
                "has_dimension_grid": bool(p["grids"]),
            })
        return {
            "query": query,
            "result_count": len(results),
            "results": results,
            "tip": "Use get_spec_sheet(model) for the full sheet incl. dimension grids.",
        }

    # ── dispatcher ──────────────────────────────────────────────────

    def call(self, name, args):
        """Route a spec tool call; returns a JSON string like MCP tools do."""
        args = args or {}
        if name == "list_spec_sheets":
            result = self.list_sheets()
        elif name == "get_spec_sheet":
            result = self.get_sheet(args.get("model", ""))
        elif name == "search_spec_sheets":
            result = self.search(args.get("query", ""),
                                 args.get("max_results", 5))
        else:
            result = {"error": f"Unknown spec tool '{name}'"}
        return json.dumps(result)


_library = None


def get_library(folder, cache_path):
    """Singleton; worker calls .refresh() on it at startup."""
    global _library
    if _library is None:
        _library = SpecLibrary(folder, cache_path)
    return _library
