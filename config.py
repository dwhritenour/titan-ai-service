"""
config.py — Titan AI agent service configuration.

All settings come from the .env file next to this script (see
.env.example). Nothing secret is hardcoded.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _req(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required setting {name} in .env")
    return val


# ── Nexus connection for the SERVICE (chat tables only) ──────────────
NEXUS_SERVER = _req("NEXUS_SERVER")
NEXUS_DATABASE = _req("NEXUS_DATABASE")
SVC_USERNAME = _req("TITAN_AI_SVC_USERNAME")          # titan_ai_svc
SVC_PASSWORD = _req("TITAN_AI_SVC_PASSWORD")

# ── Read-only login handed to the nexus-mcp-server subprocess ────────
RO_USERNAME = _req("NEXUS_RO_USERNAME")               # nexus_chat_ro
RO_PASSWORD = _req("NEXUS_RO_PASSWORD")

# ── Anthropic ────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = _req("ANTHROPIC_API_KEY")
MODEL = os.environ.get("TITAN_AI_MODEL", "claude-sonnet-5")
# 2026-09-23: the chat (agent.py) and the background agents want different
# models - chat is tool-driven and latency-bound (Sonnet), the daily plan /
# retro narratives are judgment-bound and nobody is waiting (Opus). Set
# TITAN_AI_AGENT_MODEL in .env; when absent the agents use MODEL as before.
AGENT_MODEL = os.environ.get("TITAN_AI_AGENT_MODEL", MODEL)
MAX_TOKENS = int(os.environ.get("TITAN_AI_MAX_TOKENS", "8000"))

# ── nexus-mcp-server location ────────────────────────────────────────
# Path to the compiled entry point, e.g. C:\nexus-mcp-server\dist\index.js
NEXUS_MCP_PATH = _req("NEXUS_MCP_PATH")
NODE_COMMAND = os.environ.get("NODE_COMMAND", "node")

# ── Spec sheets (v1.2) ───────────────────────────────────────────────
# Folder of Titan product spec-sheet PDFs on THIS machine. If unset or
# missing, the spec tools simply aren't offered to the model.
SPEC_SHEETS_DIR = os.environ.get("SPEC_SHEETS_DIR", r"C:\spec_sheets")
SPEC_CACHE_PATH = str(BASE_DIR / "spec_cache.json")

# ── App how-to guides (v1.1) ─────────────────────────────────────────
HOWTO_DOCS_DIR = os.environ.get("HOWTO_DOCS_DIR", r"C:\titan_ai_howto")

# ── Website crawl (v1.3) ─────────────────────────────────────────────
WEBSITE_URL = os.environ.get("WEBSITE_URL", "https://titanfci.co")  # .co is the real host; .com redirects
WEBSITE_CACHE_PATH = str(BASE_DIR / "website_cache.json")
WEBSITE_MAX_PAGES = int(os.environ.get("WEBSITE_MAX_PAGES", "300"))
WEBSITE_REFRESH_DAYS = int(os.environ.get("WEBSITE_REFRESH_DAYS", "7"))
# Secure (dealer) side — all optional; secure crawl is skipped if unset.
WEBSITE_LOGIN_URL = os.environ.get("WEBSITE_LOGIN_URL", "")
WEBSITE_USERNAME = os.environ.get("WEBSITE_USERNAME", "")
WEBSITE_PASSWORD = os.environ.get("WEBSITE_PASSWORD", "")
# Comma-separated start pages for the secure walk (consignment sites,
# solid-model listings). Do NOT list plain inventory pages — Nexus is
# the fresher source for those.
WEBSITE_SECURE_START_URLS = os.environ.get("WEBSITE_SECURE_START_URLS", "")

# ── Online inventory CSVs (v1.4) ─────────────────────────────────────
# The dealer inventory pages are backed by per-product-line CSVs in
# wp-content/uploads — fetched live at question time (complete + fresh,
# unlike the crawled page text which only holds the first filter view).
ONLINE_INVENTORY_URL_BASE = os.environ.get(
    "ONLINE_INVENTORY_URL_BASE",
    "https://titanfci.co/wp-content/uploads/inventory/")

# ── Rep locator (v1.5) ───────────────────────────────────────────────
# The public wpDataTables endpoint behind the site's Rep Locator page
# (zip -> servicing rep, ~34k rows). No credentials needed.
REP_LOCATOR_PAGE_URL = os.environ.get(
    "REP_LOCATOR_PAGE_URL", "https://titanfci.co/where-to-buy/rep-locator/")
REP_LOCATOR_AJAX_URL = os.environ.get(
    "REP_LOCATOR_AJAX_URL", "https://titanfci.co/wp-admin/admin-ajax.php")
REP_LOCATOR_TABLE_ID = os.environ.get("REP_LOCATOR_TABLE_ID", "73")

# ── Daily Plan agent (v1.6, 2026-09-06) ──────────────────────────────
# The morning proposal run for the Titan Daily Plan app (daily_plan_agent.py).
# Both DAILY_PLAN_APP_URL and AGENT_API_KEY must be set or the module stays
# off. AGENT_API_KEY must equal the Anvil Secret of the same name in the
# Titan Daily Plan app. Run time / enable / fill % live in Nexus
# (pc_plan_parameters AGENT_*), not here, so PC can change them in the app.
DAILY_PLAN_APP_URL = os.environ.get("DAILY_PLAN_APP_URL", "")   # e.g. https://titan-plan.anvil.app
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "")
DAILY_PLAN_AGENT_ENABLED = os.environ.get("DAILY_PLAN_AGENT_ENABLED", "1") == "1"
DAILY_PLAN_TZ = os.environ.get("DAILY_PLAN_TZ", "America/New_York")
DAILY_PLAN_POLL_SECONDS = float(os.environ.get("DAILY_PLAN_POLL_SECONDS", "5"))
DAILY_PLAN_MAX_WAIT_SECONDS = int(os.environ.get("DAILY_PLAN_MAX_WAIT_SECONDS", "900"))
DAILY_PLAN_NARRATIVE_MAX_TOKENS = int(os.environ.get("DAILY_PLAN_NARRATIVE_MAX_TOKENS", "1500"))
# Twilio — same account/number the Hub Transfers app uses (its Anvil
# Secrets TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER).
# Leave blank to log texts without sending. The DB kill switch
# global_parameters.sms_enabled is honored regardless.
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")
SMS_TEST_MODE = os.environ.get("SMS_TEST_MODE", "false").lower() == "true"

# ── Behavior ─────────────────────────────────────────────────────────
POLL_SECONDS = float(os.environ.get("TITAN_AI_POLL_SECONDS", "1.0"))
MAX_TOOL_ITERATIONS = int(os.environ.get("TITAN_AI_MAX_TOOL_ITERATIONS", "8"))
HISTORY_MAX_TURNS = int(os.environ.get("TITAN_AI_HISTORY_MAX_TURNS", "20"))
TRACE_RESULT_PREVIEW_CHARS = 2000
LOG_FILE = str(BASE_DIR / "titan_ai_service.log")

SYSTEM_PROMPT_PATH = BASE_DIR / "system_prompt.md"

# ── Read-only tool allowlist ─────────────────────────────────────────
# Claude can ONLY see these nexus-mcp-server tools. Every decision /
# write tool (update/apply/bulk/execute) is deliberately absent —
# and the nexus_chat_ro login makes writes impossible anyway.
ALLOWED_TOOLS = {
    # transfers (read)
    "nexus_get_pending_transfers",
    "nexus_get_transfer_stats",
    "nexus_get_transfer_candidates",
    # min/max (read)
    "nexus_get_minmax_recommendations",
    "nexus_get_minmax_stats",
    "nexus_get_minmax_sku_detail",
    "nexus_get_divergent_skus",
    # classification (read)
    "nexus_get_classification_recommendations",
    "nexus_get_classification_stats",
    # inventory / SKU
    "nexus_search_skus",
    "nexus_get_inventory_levels",
    "nexus_get_usage_trends",
    "nexus_get_sales_history",
    "nexus_get_sku_detail",
    # raw SQL (SELECT-only path) + schema exploration
    "nexus_query",
    "nexus_list_tables",
    "nexus_describe_table",
}

# Friendly status lines shown in the chat while tools run.
TOOL_STATUS_TEXT = {
    "nexus_get_pending_transfers": "Checking pending transfers…",
    "nexus_get_transfer_stats": "Summarizing transfer stats…",
    "nexus_get_transfer_candidates": "Scanning live transfer needs…",
    "nexus_get_minmax_recommendations": "Reading min/max recommendations…",
    "nexus_get_minmax_stats": "Checking min/max review stats…",
    "nexus_get_minmax_sku_detail": "Pulling min/max detail…",
    "nexus_get_divergent_skus": "Finding divergent SKUs…",
    "nexus_get_classification_recommendations": "Reading classification recs…",
    "nexus_get_classification_stats": "Checking classification stats…",
    "nexus_search_skus": "Searching SKUs…",
    "nexus_get_inventory_levels": "Checking inventory levels…",
    "nexus_get_usage_trends": "Analyzing usage trends…",
    "nexus_get_sales_history": "Pulling sales history…",
    "nexus_get_sku_detail": "Pulling SKU details…",
    "nexus_query": "Querying the database…",
    "nexus_list_tables": "Listing database tables…",
    "nexus_describe_table": "Inspecting table structure…",
    # spec sheets (native tools, v1.2)
    "list_spec_sheets": "Listing spec sheets…",
    "get_spec_sheet": "Reading the spec sheet…",
    "search_spec_sheets": "Searching spec sheets…",
    # excel export (native tool)
    "export_excel": "Building the Excel file…",
    "get_corrosion_chart_row": "Pulling the chart row from the book…",
    # how-to guides (native tools, v1.1)
    "list_howto_guides": "Listing the app guides…",
    "get_howto_guide": "Reading the how-to guide…",
    "search_howto_guides": "Searching the app guides…",
    # website (native tools, v1.3)
    "search_website": "Searching titanfci.com…",
    "get_webpage": "Reading the web page…",
    # online inventory (native tool, v1.4)
    "get_online_inventory": "Checking the online inventory…",
    # rep locator (native tool, v1.5)
    "find_titan_rep": "Looking up the Titan rep…",
}
