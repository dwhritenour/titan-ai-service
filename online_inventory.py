"""
online_inventory.py — live dealer-site inventory from the CSVs that
back titanfci.co's inventory pages (v1.4, added 2026-08-11).

The website's per-product-line inventory tables are rendered from CSV
files under wp-content/uploads/inventory/ (one per line, refreshed on
the site's own schedule — the Updated column shows the stamp). Fetching
the CSV directly at question time beats the weekly page crawl on both
completeness (the crawled page only holds the rows in the initial
render — the filters hide the rest) and freshness.

One tool: get_online_inventory(product_line, search?, size?,
warehouse?, in_stock_only?). Rows are filtered server-side so the
model never wades through 500 raw rows; a 15-minute in-memory cache
keeps repeat questions cheap.

House rule (also in the system prompt): this is what DEALERS see on
the website. For internal Titan warehouse stock, Nexus is
authoritative; the online inventory matters for "what does the site
show" and consignment-site questions.
"""

import csv
import io
import json
import logging
import time

log = logging.getLogger("titan_ai")

# Product lines -> CSV file names (…/wp-content/uploads/inventory/<x>.csv).
# Derived from the dealer inventory pages on titanfci.co. Aliases let the
# model pass friendly names.
PRODUCT_LINES = {
    "ystrainer": "ystrainer.csv",
    "bstrainer": "bstrainer.csv",
    "dstrainer": "dstrainer.csv",
    "checkvalve": "checkvalve.csv",
    "butterflyvalve": "butterflyvalve.csv",
    "ballvalve": "ballvalve.csv",
    "pumpproduct": "pumpproduct.csv",
    "otherproduct": "otherproduct.csv",
    "slob": "slob.csv",
}
ALIASES = {
    "y strainer": "ystrainer", "y-strainer": "ystrainer",
    "y strainers": "ystrainer", "ystrainers": "ystrainer",
    "basket strainer": "bstrainer", "basket strainers": "bstrainer",
    "basket": "bstrainer",
    "duplex strainer": "dstrainer", "duplex strainers": "dstrainer",
    "duplex": "dstrainer",
    "check valve": "checkvalve", "check valves": "checkvalve",
    "butterfly valve": "butterflyvalve", "butterfly valves": "butterflyvalve",
    "butterfly": "butterflyvalve",
    "ball valve": "ballvalve", "ball valves": "ballvalve",
    "pump product": "pumpproduct", "pump products": "pumpproduct",
    "pump": "pumpproduct",
    "other product": "otherproduct", "other products": "otherproduct",
    "other": "otherproduct",
}

CACHE_TTL_SECONDS = 15 * 60
MAX_ROWS_RETURNED = 200

INVENTORY_TOOL_NAMES = {"get_online_inventory"}


def inventory_tools_for_anthropic():
    lines = ", ".join(sorted(PRODUCT_LINES))
    return [
        {
            "name": "get_online_inventory",
            "description": (
                "Live inventory as shown on titanfci.co's dealer site, "
                "fetched from the CSV behind each product-line page "
                "(complete and current — better than the crawled page "
                "text, which only holds the first filter view). Use for "
                "questions about ONLINE/WEBSITE/DEALER-visible inventory "
                "and CONSIGNMENT-site stock. For internal Titan warehouse "
                "stock, Nexus is the authoritative source — use the Nexus "
                f"tools instead. Product lines: {lines}. "
                "Columns include model, part_code, size, body material, "
                "ASME class, end connections, warehouse (cost_ctr), "
                "on-hand / committed / available, list prices, and the "
                "site's Updated timestamp."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_line": {
                        "type": "string",
                        "description": f"One of: {lines} (friendly names "
                                       "like 'y strainer' also work)",
                    },
                    "search": {
                        "type": "string",
                        "description": "Substring match on model / "
                                       "part_code / series (e.g. 'YS61')",
                    },
                    "size": {
                        "type": "string",
                        "description": "Exact size filter, e.g. '2' for "
                                       "2 inch, '0.25' for 1/4 inch",
                    },
                    "warehouse": {
                        "type": "string",
                        "description": "Substring match on the "
                                       "warehouse/cost-center column "
                                       "(e.g. 'Spokane', 'NC Main')",
                    },
                    "in_stock_only": {
                        "type": "boolean",
                        "description": "Only rows with available > 0",
                    },
                },
                "required": ["product_line"],
            },
        }
    ]


class OnlineInventory:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/") + "/"
        self._cache = {}          # line -> (fetched_monotonic, rows)

    # ── fetching ─────────────────────────────────────────────────────
    def _rows(self, line):
        cached = self._cache.get(line)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        import requests
        url = self.base_url + PRODUCT_LINES[line]
        r = requests.get(url, timeout=30, headers={
            "User-Agent": "TitanAI-internal-crawler/1.0"})
        r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.text)))
        self._cache[line] = (time.monotonic(), rows)
        log.info("Online inventory fetched: %s (%s rows)", url, len(rows))
        return rows

    # ── tool dispatch ────────────────────────────────────────────────
    def call(self, name, tool_input):
        if name != "get_online_inventory":
            return json.dumps({"error": f"Unknown tool {name}"})

        raw_line = (tool_input.get("product_line") or "").strip().lower()
        line = ALIASES.get(raw_line, raw_line)
        if line not in PRODUCT_LINES:
            return json.dumps({
                "error": f"Unknown product_line '{raw_line}'",
                "valid_product_lines": sorted(PRODUCT_LINES),
            })

        try:
            rows = self._rows(line)
        except Exception as exc:
            return json.dumps({"error": f"Could not fetch the online "
                                        f"inventory CSV: {exc}"})

        search = (tool_input.get("search") or "").strip().lower()
        size = (tool_input.get("size") or "").strip()
        warehouse = (tool_input.get("warehouse") or "").strip().lower()
        in_stock = bool(tool_input.get("in_stock_only"))

        def _num(v):
            try:
                return float(str(v).replace(",", ""))
            except (TypeError, ValueError):
                return 0.0

        matched = []
        for row in rows:
            if search and not any(
                    search in (row.get(k) or "").lower()
                    for k in ("model", "part_code", "series")):
                continue
            if size and str(row.get("size", "")).strip().strip('"') != size:
                continue
            if warehouse and warehouse not in \
                    (row.get("cost_ctr") or "").lower():
                continue
            if in_stock and _num(row.get("available")) <= 0:
                continue
            matched.append(row)

        updated = matched[0].get("Updated") if matched else (
            rows[0].get("Updated") if rows else None)
        shown = matched[:MAX_ROWS_RETURNED]
        result = {
            "product_line": line,
            "total_rows_in_file": len(rows),
            "matched_rows": len(matched),
            "shown_rows": len(shown),
            "site_updated_stamp": updated,
            "note": ("Data as displayed to dealers on titanfci.co. For "
                     "internal Titan warehouse stock, Nexus is "
                     "authoritative."),
            "rows": shown,
        }
        if len(matched) > MAX_ROWS_RETURNED:
            result["truncated"] = (f"Showing first {MAX_ROWS_RETURNED} of "
                                   f"{len(matched)} matches — narrow with "
                                   "search/size/warehouse filters.")
        return json.dumps(result)


_instance = None


def get_library(config):
    global _instance
    if _instance is None:
        _instance = OnlineInventory(config.ONLINE_INVENTORY_URL_BASE)
    return _instance
