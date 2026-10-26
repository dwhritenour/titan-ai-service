# titan-ai-service — Titan AI agent service (runs on Hermes)

The "brain" of the Titan AI chat app. Polls the `tai_chat_messages`
queue in Nexus, answers each question with Claude + read-only
nexus-mcp-server tools, and writes the answer back. The Anvil app and
this service never talk directly — the database is the interface, same
as every other app in the family.

```
Anvil "Titan AI" app ──▶ tai_chat_messages (status=pending)
                                    │  poll ~1s
                          titan-ai-service (this)
                          │  Claude agent loop (Anthropic API)
                          └─ nexus-mcp-server (stdio subprocess,
                             nexus_chat_ro read-only login)
                                    │
                          tai_chat_messages (status rows + answer)
                                    ▲  Timer poll ~1s
                          Anvil "Titan AI" app renders the thread
```

## One-time setup on Hermes (192.168.16.35)

Prerequisites (install if missing): **Python 3.10+** and **Node.js 18+**
(`python --version`, `node --version`).

1. **Database side (Dave, once):**
   - Apply migration `020_titan_ai_chat_tables.sql` (claim the number first —
     see the script header).
   - Run `sql/titan_ai_logins.sql` with real passwords.

2. **nexus-mcp-server on Hermes:** copy the `nexus-mcp-server` folder to
   `C:\nexus-mcp-server` (or note your path for `.env`), then:

   ```
   cd C:\nexus-mcp-server
   npm install
   npm run build
   ```

   No env vars needed at this step — the service injects the read-only
   credentials when it spawns the subprocess.

3. **This service:** copy the `titan-ai-service` folder to
   `C:\titan-ai-service`, then:

   ```
   cd C:\titan-ai-service
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   copy .env.example .env
   notepad .env        &REM fill in passwords, API key, NEXUS_MCP_PATH
   ```

4. **Smoke test (foreground):**

   ```
   venv\Scripts\python worker.py
   ```

   Expected log lines: `Titan AI service starting` then
   `nexus-mcp-server up — 17 read-only tools`. Now insert a test row
   (or send a question from the Anvil app) and watch it get answered:

   ```sql
   INSERT INTO dbo.tai_chat_sessions (username) VALUES ('dave-test');
   INSERT INTO dbo.tai_chat_messages (session_id, role, content, status)
   VALUES (SCOPE_IDENTITY(), 'user', 'How many tables are in the database?', 'pending');
   -- then: SELECT * FROM dbo.tai_chat_messages ORDER BY message_id DESC;
   ```

5. **Run as a Windows service** (survives reboot/logoff). Simplest is
   [NSSM](https://nssm.cc):

   ```
   nssm install TitanAI C:\titan-ai-service\venv\Scripts\python.exe C:\titan-ai-service\worker.py
   nssm set TitanAI AppDirectory C:\titan-ai-service
   nssm set TitanAI AppStdout C:\titan-ai-service\service_stdout.log
   nssm set TitanAI AppStderr C:\titan-ai-service\service_stderr.log
   nssm start TitanAI
   ```

   (Task Scheduler "At startup, run whether user is logged on or not"
   works too if you prefer no new tools.)

## Operating notes

- **Kill switch:** `nssm stop TitanAI`. The chat app keeps working;
  questions just sit at "Titan AI is thinking…" until the service is
  back (they're queued, nothing is lost). Users see queued questions
  answered on restart.
- **Logs:** `titan_ai_service.log` in this folder — one line per
  question with tool count, tokens, latency. Hourly idle heartbeat.
- **Model/cost:** set `TITAN_AI_MODEL` in `.env`. Default
  `claude-sonnet-5` ($3/MTok in, $15/MTok out; intro $2/$10 through
  2026-08-31). Prompt caching is enabled in code, so a typical question
  runs a few cents. `claude-haiku-4-5-20251001` is the cheap fallback if
  volume ever grows.
- **Read-only guarantee (three layers):** tool allowlist in `config.py`
  (17 read tools; no update/apply/execute tools are ever registered) →
  `nexus_chat_ro` login is db_datareader with explicit DENY on writes →
  nexus-mcp-server's own SELECT-only guard on `nexus_query`.
- **Crash recovery:** on start, anything stuck `processing` is requeued.
  The claim query is atomic, so even two service instances can't
  double-answer (still: run one instance).
- **Upgrading the brain:** the system prompt is `system_prompt.md` —
  edit and restart. New knowledge sources arrive as additional tools;
  no architecture change.

## Spec sheets (v1.2, added 2026-08-07)

The service also answers product spec questions ("face-to-face for a
2 inch YS61-CS") from the PDFs in `SPEC_SHEETS_DIR` (default
`C:\spec_sheets`, same box). Three native tools ride alongside the
Nexus tools: `list_spec_sheets`, `get_spec_sheet`, `search_spec_sheets`.

Install/upgrade steps on the server:

```
nssm stop TitanAI
venv\Scripts\pip install pdfplumber
notepad .env        &REM add: SPEC_SHEETS_DIR=C:\spec_sheets
&REM copy in the updated files: spec_sheets.py, config.py, agent.py,
&REM worker.py, system_prompt.md, requirements.txt
nssm start TitanAI
```

## App how-to guides (added 2026-08-07)

"How do I…?" questions about the Titan apps answer from the markdown
guides in `HOWTO_DOCS_DIR` (default `C:\titan_ai_howto`). Guides are
authored per-app by each app's owner via the Claude Exchange topic
`2026-08-07_titan-ai-howto-docs`; the ready-to-copy corpus lives in the
project's `titan_ai_howto\` folder. Updating a guide = drop the new .md
in the folder + `nssm restart TitanAI`. New service file: howto_docs.py.

e21 code lookups — sales/purchase order header types (R, D, F, S, N, W, T, C),
line-item status codes (10 Entered … 16 Shipped, 18 Invoiced, 90 Canceled),
PO types — live in the "E21 Sales and Purchase Order Codes" guide.
Use get_howto_guide("e21 codes") for any "what does code X mean" question.
Ship-plan rule: only SO types R, D, F, S count.

## Website index (v1.3, added 2026-08-07)

Titan AI answers from an index of www.titanfci.com: public pages plus
(optionally) the secure dealer side — consignment-site pages and a CAD
Model Index built from every solid-model download link found. Setup:

```
venv\Scripts\pip install requests beautifulsoup4
notepad .env    &REM WEBSITE_* settings; secure side needs a DEDICATED
                &REM login for Titan AI + WEBSITE_LOGIN_URL + the
                &REM WEBSITE_SECURE_START_URLS (consignment + models
                &REM pages; NOT plain inventory — Nexus is fresher)
venv\Scripts\python site_crawler.py    &REM foreground test crawl
nssm restart TitanAI
```

The test crawl prints page counts and titles. In service, the cache
answers immediately and re-crawls in a background thread when older
than WEBSITE_REFRESH_DAYS (7). If Cloudflare ever blocks the crawler,
allowlist the server's IP in the Cloudflare dashboard. The crawler
identifies itself as `TitanAI-internal-crawler/1.0`.

## Online inventory (v1.4, added 2026-08-11)

Dealer-site inventory questions (incl. consignment sites) answer from
the live CSVs behind titanfci.co's inventory pages
(wp-content/uploads/inventory/<line>.csv) via the `get_online_inventory`
tool — fetched at question time with a 15-minute cache, filtered
server-side. No .env changes needed (override ONLINE_INVENTORY_URL_BASE
if the site path ever moves). New file: online_inventory.py; updated:
agent.py, config.py, system_prompt.md. Nexus stays authoritative for
internal warehouse stock — the prompt routes accordingly.

## Rep locator (v1.5, added 2026-08-11)

"Who is our rep for zip 28601?" answers from the live wpDataTables
endpoint behind the site's Rep Locator page (admin-ajax.php,
action=get_wdtable, table_id=73 — public, no credentials). The
`find_titan_rep` tool GETs the page for the nonce (cached 6h,
auto-refreshed on expiry) and posts a per-column zip search — the
global search does not work on this table; the column filter does.
New file: rep_locator.py; updated: agent.py, config.py,
system_prompt.md. No .env or pip changes.

## Excel exports (added 2026-08-07)

Users can ask for data "as a spreadsheet" and get a real .xlsx download
chip in the chat. Requires migration `021_titan_ai_export_files.sql`
(claim the number first), `pip install openpyxl` in the venv, the
updated service files (excel_export.py is new), and the updated Anvil
files (chat_service.py + TitanAIMessageRow). Files are stored in
dbo.tai_chat_files; no auto-cleanup in v1 (manual cleanup SQL is in the
migration header).

Startup log should show `Spec sheets loaded: ~50 from C:\spec_sheets`
(first start extracts everything — a minute or so; after that a cache
keyed by file modification time makes it instant). **Adding or
updating a spec sheet** = drop the PDF in the folder and
`nssm restart TitanAI`. If the folder is missing, the service runs
normally with spec tools disabled.

## Daily Plan agent (v1.6, added 2026-09-06)

Once per weekday at `AGENT_RUN_TIME` (Eastern; `pc_plan_parameters`,
06:30 by default) the service asks the **Titan Daily Plan** app to build
that day's proposal, writes the meeting narrative with Claude, stores it
on `pc_agent_proposal.rationale` (shown in the app's *Agent proposal*
popup) and texts the `DAILY_PLAN_PROPOSAL` contacts in
`sms_notification_contacts`. The APP chooses the lines (deterministic:
flag scores, fill %, capacity); this service only runs it, explains it,
and sends the text.

New file: `daily_plan_agent.py`; updated: `worker.py` (one `tick()`
call in the poll loop), `config.py`, `requirements.txt`
(`pip install twilio`), `.env.example`. Requires migration 052 (grants
to titan_ai_svc) and the Daily Plan app's `/agent/propose` +
`/agent/status` HTTP endpoints (server module `daily_ship_plan`).

Setup on Hermes:

1. `.env` — add `DAILY_PLAN_APP_URL` (the app's URL, no trailing slash)
   and `AGENT_API_KEY` (must EQUAL the Anvil Secret `AGENT_API_KEY` in
   the Titan Daily Plan app), plus `TWILIO_ACCOUNT_SID`,
   `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` copied from the Hub
   Transfers app's Anvil Secrets. Leave the Twilio values blank to log
   texts without sending. `SMS_TEST_MODE=true` for the first morning.
2. `pip install twilio` in the venv, drop in the files, `nssm restart TitanAI`.
   Startup: nothing new is printed until the first `tick()`; if the URL or
   key is missing the log says `Daily Plan agent OFF (...)` once.
3. Dry run from the service folder (activate the venv first):
   `python daily_plan_agent.py --no-sms` — runs the app for today (or
   next Monday), writes the narrative, prints the summary. Add a date
   (`python daily_plan_agent.py 2026-09-08`) to target a day;
   `--force` re-runs a published/disabled day; `--narrative-only`
   rewrites the narrative for the latest proposal without a new run.

Switches, in the order they are checked: `.env DAILY_PLAN_AGENT_ENABLED`
(0 = pause the service side), `pc_plan_parameters AGENT_ENABLED`
(0 = the app refuses; editable in the app), and for texts
`global_parameters.sms_enabled` (the company-wide kill switch — same as
every other Titan text). A restart after 06:30 does NOT re-run: a
proposal for the day generated in the last 12 h counts as done. Every
run and every text goes to `dbo.ai_agent_log`
(`DAILY_PLAN_AGENT_RUN`, `SMS_DAILY_PLAN_PROPOSAL`, executed_by
`titan-ai-service`).
