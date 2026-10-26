"""
rep_locator.py — "Who is our rep for zip X?" from the live wpDataTables
endpoint behind titanfci.co/where-to-buy/rep-locator/ (v1.5, 2026-08-11).

The Rep Locator page is a wpDataTables server-side table (table_id 73,
~34k rows — one row per US zip code mapping to the servicing rep). The
page fetches rows from admin-ajax.php?action=get_wdtable&table_id=73
with a DataTables-style POST; a per-request nonce is embedded in the
page HTML (wdtNonceFrontendServerSide_73). No login is required.

Recipe (verified in-browser 2026-08-11):
  1. GET the rep-locator page, pull the nonce from the hidden input.
  2. POST the full DataTables columns[] block — global search returns
     no rows; the PER-COLUMN search on the zip column ("5zip") is what
     the page itself uses and is what works.
  3. Rows come back as HTML fragments — strip tags, keep the href for
     the rep's website.

Nonces expire (~12-24h), so on an empty/invalid response we refresh
the nonce once and retry.
"""

import html
import json
import logging
import re
import time

log = logging.getLogger("titan_ai")

REP_TOOL_NAMES = {"find_titan_rep"}

COLUMNS = ["5zip", "territory", "region", "name", "address",
           "phone", "email", "web"]
NONCE_TTL_SECONDS = 6 * 3600
MAX_ROWS = 25


def rep_tools_for_anthropic():
    return [
        {
            "name": "find_titan_rep",
            "description": (
                "Find the Titan sales rep serving a US zip code, from the "
                "live Rep Locator on titanfci.co (one row per zip — "
                "~34,000 zips mapped). Returns the rep firm, contact "
                "person, address, phone/fax, email, and website. Use for "
                "'who is our rep in/for/near …' questions — if the user "
                "gives a city or state instead of a zip, ask for (or "
                "infer) a zip code in that area and look it up. Can also "
                "search by rep company name to list a firm's territory."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "zip": {
                        "type": "string",
                        "description": "5-digit US zip code, e.g. '28601'",
                    },
                    "company": {
                        "type": "string",
                        "description": "Alternative: search the rep firm "
                                       "name (e.g. 'International Valve') "
                                       "— returns a sample of that firm's "
                                       "zips plus contact info",
                    },
                },
            },
        }
    ]


def _strip(cell):
    """HTML fragment -> clean text, preserving any href."""
    s = str(cell)
    hrefs = re.findall(r'href="([^"]+)"', s)
    text = re.sub(r"<br\s*/?>", ", ", s)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip(" ,")
    href = next((h for h in hrefs if not h.startswith("mailto:")), None)
    return text, href


class RepLocator:
    def __init__(self, page_url, ajax_url, table_id):
        self.page_url = page_url
        self.ajax_url = ajax_url
        self.table_id = table_id
        self._session = None
        self._nonce = None
        self._nonce_at = 0.0

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers["User-Agent"] = \
                "TitanAI-internal-crawler/1.0"
        return self._session

    def _get_nonce(self, force=False):
        if (not force and self._nonce
                and time.monotonic() - self._nonce_at < NONCE_TTL_SECONDS):
            return self._nonce
        s = self._get_session()
        r = s.get(self.page_url, timeout=30)
        r.raise_for_status()
        m = re.search(
            r'wdtNonceFrontendServerSide_%s"[^>]*value="([^"]+)"'
            % self.table_id, r.text)
        if not m:
            m = re.search(r'name="wdtNonce[^"]*"[^>]*value="([^"]+)"',
                          r.text)
        if not m:
            raise RuntimeError("Could not find the wpDataTables nonce on "
                               f"{self.page_url} — page layout changed?")
        self._nonce, self._nonce_at = m.group(1), time.monotonic()
        log.info("Rep locator nonce refreshed")
        return self._nonce

    def _query(self, column_searches, length=MAX_ROWS, retry=True):
        """POST a DataTables request; column_searches = {col_index: text}."""
        body = {"draw": "1", "start": "0", "length": str(length),
                "search[value]": "", "search[regex]": "false",
                "wdtNonce": self._get_nonce()}
        for i, name in enumerate(COLUMNS):
            body[f"columns[{i}][data]"] = str(i)
            body[f"columns[{i}][name]"] = name
            body[f"columns[{i}][searchable]"] = "true"
            body[f"columns[{i}][orderable]"] = "true"
            body[f"columns[{i}][search][value]"] = \
                column_searches.get(i, "")
            body[f"columns[{i}][search][regex]"] = "false"
        s = self._get_session()
        r = s.post(f"{self.ajax_url}?action=get_wdtable"
                   f"&table_id={self.table_id}", data=body, timeout=30)
        r.raise_for_status()
        try:
            payload = r.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or "data" not in payload:
            if retry:                      # stale nonce → refresh once
                self._get_nonce(force=True)
                return self._query(column_searches, length, retry=False)
            raise RuntimeError(f"Unexpected rep-locator response: "
                               f"{r.text[:200]}")
        return payload

    @staticmethod
    def _row_to_rep(row):
        zip_code, _ = _strip(row[0])
        territory, _ = _strip(row[1])
        region, _ = _strip(row[2])
        name, _ = _strip(row[3])
        address, _ = _strip(row[4])
        phone, _ = _strip(row[5])
        email, _ = _strip(row[6])
        _, website = _strip(row[7])
        return {"zip": zip_code, "territory_code": territory,
                "region": region, "rep": name, "address": address,
                "phone": phone, "email": email, "website": website}

    def call(self, name, tool_input):
        if name != "find_titan_rep":
            return json.dumps({"error": f"Unknown tool {name}"})
        zip_raw = (tool_input.get("zip") or "").strip()
        company = (tool_input.get("company") or "").strip()

        try:
            if zip_raw:
                m = re.search(r"\d{5}", zip_raw)
                if not m:
                    return json.dumps({"error": f"'{zip_raw}' is not a "
                                                "5-digit US zip code"})
                zip5 = m.group(0)
                payload = self._query({0: zip5})
                rows = [self._row_to_rep(r) for r in payload["data"]]
                if not rows:
                    return json.dumps({
                        "zip": zip5, "matches": 0,
                        "note": "No rep mapped to this zip in the Rep "
                                "Locator — it may be outside covered "
                                "territories; suggest contacting Titan "
                                "directly."})
                return json.dumps({"zip": zip5,
                                   "matches": int(payload.get(
                                       "recordsFiltered", len(rows))),
                                   "reps": rows,
                                   "source": self.page_url})
            if company:
                payload = self._query({3: company})
                rows = [self._row_to_rep(r) for r in payload["data"]]
                total = int(payload.get("recordsFiltered", len(rows)))
                out = {"company_search": company,
                       "zips_mapped_to_matches": total,
                       "sample_rows": rows[:10],
                       "source": self.page_url}
                if rows:
                    out["rep_contact"] = {k: rows[0][k] for k in
                                          ("rep", "address", "phone",
                                           "email", "website")}
                return json.dumps(out)
            return json.dumps({"error": "Provide either zip or company"})
        except Exception as exc:
            return json.dumps({"error": f"Rep locator lookup failed: "
                                        f"{exc}"})


_instance = None


def get_library(config):
    global _instance
    if _instance is None:
        _instance = RepLocator(config.REP_LOCATOR_PAGE_URL,
                               config.REP_LOCATOR_AJAX_URL,
                               config.REP_LOCATOR_TABLE_ID)
    return _instance
