"""
excel_export.py — Excel export tool for the Titan AI agent (v2, 2026-09-16).

v1 required the model to emit every row as JSON inside the tool call.
That silently capped exports at what fits in the model's output-token
budget (TITAN_AI_MAX_TOKENS, default 2500) — a 334-row export could
never fit, which is why large exports failed while 4-row ones worked.

v2 adds the fix: the model passes a single SELECT statement instead,
and THIS module runs it through the read-only nexus_chat_ro login and
streams every row straight into the .xlsx. No rows travel through the
model, so file size is bounded only by MAX_ROWS. The old columns+rows
mode remains for small model-composed tables (projections, analysis
summaries) that never came from a single query.

The file is stored in dbo.tai_chat_files and a role='file' message row
becomes the download chip in the Anvil app — the database is the
transport, same as everything else in Titan AI.
"""

import datetime
import decimal
import io
import json
import logging
import re
import uuid

import config

log = logging.getLogger("titan-ai.export")

EXPORT_TOOL_NAMES = {"export_excel"}

MAX_ROWS = 20000
MAX_COMPOSED_ROWS = 1000     # cap for the legacy columns+rows mode
MAX_COLS = 40
MAX_SHEET_NAME = 31          # Excel's hard limit

# Statements that have no business in a read-only export query. The
# nexus_chat_ro login already has DENY on writes — this guard just
# fails fast with a clear message instead of a SQL permission error.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|"
    r"revoke|exec|execute|sp_\w+|xp_\w+|into|waitfor|shutdown|backup|"
    r"restore|dbcc|openrowset|opendatasource|bulk)\b", re.IGNORECASE)


def export_tools_for_anthropic():
    return [
        {
            "name": "export_excel",
            "description": (
                "Create a downloadable Excel (.xlsx) file and attach it to "
                "this chat. Use when the user asks to export, download, or "
                "get data as a spreadsheet/Excel/file.\n\n"
                "PREFERRED — `sql` mode: pass ONE complete SELECT statement. "
                "It runs on the read-only Nexus login and EVERY matching row "
                "is written to the file server-side (up to 20,000), so you "
                "do NOT need to have fetched the data in chat first and the "
                "file is never cut short. Write the query to return exactly "
                "the columns the user wants, with clear aliases — the "
                "aliases become the column headers.\n\n"
                "`columns`+`rows` mode is ONLY for small tables you composed "
                "yourself (projections, comparisons, analysis summaries — "
                "max 1,000 rows) where no single query produced the data.\n\n"
                "Pass exactly one of sql OR rows."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": ("Base filename, e.g. 'below_min_starlite'. "
                                        ".xlsx is appended automatically."),
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "Worksheet tab name (default 'Data').",
                    },
                    "sql": {
                        "type": "string",
                        "description": ("A single SELECT (or WITH…SELECT) statement. "
                                        "Read-only; no semicolons; column aliases "
                                        "become the Excel headers."),
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "rows mode only: column headers, in order.",
                    },
                    "rows": {
                        "type": "array",
                        "items": {"type": "array"},
                        "description": ("rows mode only: data rows matching columns. "
                                        "Strings, numbers, or null. Max 1,000."),
                    },
                },
                "required": ["filename"],
            },
        }
    ]


def _safe_filename(name):
    name = re.sub(r"[^A-Za-z0-9 _\-\.]", "", (name or "export")).strip() or "export"
    if name.lower().endswith(".xlsx"):
        name = name[:-5]
    return (name[:150] + ".xlsx")


def _validate_sql(sql):
    """Return (clean_sql, None) or (None, error_message)."""
    if not sql or not sql.strip():
        return None, "sql is empty."
    # Strip comments so keywords can't hide in them, then re-check.
    clean = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    clean = re.sub(r"--[^\n]*", " ", clean)
    clean = clean.strip().rstrip(";").strip()
    if ";" in clean:
        return None, "Only a single statement is allowed (no semicolons)."
    if not re.match(r"^(select|with)\b", clean, re.IGNORECASE):
        return None, "Only SELECT (or WITH…SELECT) statements are allowed."
    hit = _FORBIDDEN.search(clean)
    if hit:
        return None, (f"Forbidden keyword '{hit.group(0)}' — the export "
                      "query must be a plain read-only SELECT.")
    return clean, None


def _run_ro_query(sql):
    """Execute on the read-only login; returns (columns, rows, truncated)."""
    import pymssql
    conn = pymssql.connect(
        server=config.NEXUS_SERVER,
        user=config.RO_USERNAME,           # nexus_chat_ro: db_datareader,
        password=config.RO_PASSWORD,       # explicit DENY on all writes
        database=config.NEXUS_DATABASE,
        port="1433",
        as_dict=False,                     # keep column ORDER
        autocommit=True,
    )
    try:
        cur = conn.cursor()
        cur.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        return columns, list(rows[:MAX_ROWS]), truncated
    finally:
        conn.close()


def _excel_value(val):
    if val is None or isinstance(val, (int, float, str, bool,
                                       datetime.datetime, datetime.date,
                                       datetime.time)):
        return val
    if isinstance(val, decimal.Decimal):
        return float(val)
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, (bytes, bytearray)):
        return f"<binary {len(val)} bytes>"
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return str(val)


def _build_xlsx(sheet_name, columns, rows):
    """Return xlsx bytes. openpyxl imported lazily (service still runs
    without it if the export tool is never used/installed)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_name or "Data")[:MAX_SHEET_NAME] or "Data"

    header_font = Font(bold=True)
    for c, name in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=c, value=str(name))
        cell.font = header_font
    ws.freeze_panes = "A2"

    for r, row in enumerate(rows, start=2):
        for c in range(len(columns)):
            val = row[c] if c < len(row) else None
            ws.cell(row=r, column=c + 1, value=_excel_value(val))

    # Rough column autosize from header + first 50 rows.
    for c, name in enumerate(columns, start=1):
        width = len(str(name))
        for row in rows[:50]:
            if c - 1 < len(row) and row[c - 1] is not None:
                width = max(width, len(str(row[c - 1])))
        ws.column_dimensions[get_column_letter(c)].width = min(max(width + 2, 8), 50)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def handle(db_module, session_id, args):
    """Execute the export_excel tool. Returns a JSON string for the model."""
    args = args or {}
    sql = (args.get("sql") or "").strip()
    columns = args.get("columns") or []
    rows = args.get("rows") or []
    truncated = False

    if sql and rows:
        return json.dumps({"error": "Pass either sql OR columns+rows, not both."})

    if sql:
        clean, err = _validate_sql(sql)
        if err:
            return json.dumps({"error": err})
        try:
            columns, rows, truncated = _run_ro_query(clean)
        except Exception as exc:
            log.exception("export query failed")
            return json.dumps({"error": f"Export query failed: {exc}. "
                                        "Fix the SQL and call export_excel again."})
        if not columns:
            return json.dumps({"error": "The query returned no result set."})
    else:
        if not columns:
            return json.dumps({"error": "Pass sql (preferred) or columns+rows."})
        if len(rows) > MAX_COMPOSED_ROWS:
            return json.dumps({"error": f"rows mode is capped at {MAX_COMPOSED_ROWS} "
                                        "rows — use sql mode for query-backed data."})

    if len(columns) > MAX_COLS:
        return json.dumps({"error": f"Too many columns ({len(columns)}; max {MAX_COLS})."})

    filename = _safe_filename(args.get("filename"))
    try:
        blob = _build_xlsx(args.get("sheet_name"), columns, rows)
    except Exception as exc:
        log.exception("xlsx build failed")
        return json.dumps({"error": f"Could not build the Excel file: {exc}"})

    file_id = db_module.insert_export_file(session_id, filename, blob)
    db_module.insert_file_message(session_id, file_id, filename)
    log.info("Export %s: %s rows, %s bytes (file_id %s, mode %s)",
             filename, len(rows), len(blob), file_id, "sql" if sql else "rows")
    result = {
        "success": True,
        "file_id": file_id,
        "filename": filename,
        "row_count": len(rows),
        "columns": columns,
        "note": ("The download chip is already attached to the chat. In your "
                 "answer, confirm the export and summarize what the file "
                 "contains (row count, columns) — do NOT repeat the table."),
    }
    if truncated:
        result["truncated"] = (f"Result exceeded {MAX_ROWS} rows; the file has "
                               f"the first {MAX_ROWS}. Tell the user and offer "
                               "a narrower query.")
    return json.dumps(result)
