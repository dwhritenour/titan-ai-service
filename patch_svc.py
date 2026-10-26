"""Apply the Daily Plan agent hooks to the titan-ai-service files.
Reads from SRC (current live copies), writes to DST (staging)."""
import sys, pathlib, re

SRC = pathlib.Path(sys.argv[1]); DST = pathlib.Path(sys.argv[2])
DST.mkdir(parents=True, exist_ok=True)


def patch(name, edits):
    raw = (SRC / name).read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    for old, new in edits:
        assert text.count(old) == 1, f"{name}: anchor not unique/found: {old[:60]!r}"
        text = text.replace(old, new)
    out = text.replace("\n", "\r\n") if crlf else text
    (DST / name).write_bytes(out.encode("utf-8"))
    print("patched", name, "(crlf)" if crlf else "(lf)")


# ── config.py ─────────────────────────────────────────────────────────
patch("config.py", [(
    "# ── Behavior ─────────────────────────────────────────────────────────\n",
    '''# ── Daily Plan agent (v1.6, 2026-09-06) ──────────────────────────────
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
DAILY_PLAN_NARRATIVE_MAX_TOKENS = int(os.environ.get("DAILY_PLAN_NARRATIVE_MAX_TOKENS", "4000"))
# Twilio — same account/number the Hub Transfers app uses (its Anvil
# Secrets TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER).
# Leave blank to log texts without sending. The DB kill switch
# global_parameters.sms_enabled is honored regardless.
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")
SMS_TEST_MODE = os.environ.get("SMS_TEST_MODE", "false").lower() == "true"

# ── Behavior ─────────────────────────────────────────────────────────
''')])

# ── worker.py ─────────────────────────────────────────────────────────
patch("worker.py", [
    ("import config\nimport db\nimport howto_docs\n",
     "import config\nimport daily_plan_agent\nimport db\nimport howto_docs\n"),
    ("""                while True:
                    msg = db.claim_pending_message()
                    if msg is None:
""",
     """                while True:
                    # Daily Plan agent (v1.6): once per weekday at
                    # AGENT_RUN_TIME it launches the proposal run on
                    # its own thread. Cheap on every other pass.
                    try:
                        daily_plan_agent.tick()
                    except Exception:
                        log.exception("daily_plan_agent.tick failed")
                    msg = db.claim_pending_message()
                    if msg is None:
"""),
])

# ── requirements.txt ──────────────────────────────────────────────────
patch("requirements.txt", [(
    "beautifulsoup4>=4.12  # website HTML parsing (v1.3)\n",
    "beautifulsoup4>=4.12  # website HTML parsing (v1.3)\n"
    "twilio>=9.0       # Daily Plan proposal SMS (v1.6)\n")])

# ── .env.example ──────────────────────────────────────────────────────
env = (SRC / ".env.example").read_bytes().decode("utf-8")
crlf = "\r\n" in env
env = env.replace("\r\n", "\n")
# never ship a real-looking password in the example
env = re.sub(r"(?m)^WEBSITE_PASSWORD=.*$", "WEBSITE_PASSWORD=", env)
env = re.sub(r"(?m)^WEBSITE_USERNAME=.*$", "WEBSITE_USERNAME=", env)
block = '''
# Daily Plan agent (v1.6) — the 06:30 proposal run for the Titan Daily
# Plan app. Both required or the module stays off. AGENT_API_KEY must
# EQUAL the Anvil Secret AGENT_API_KEY in the Titan Daily Plan app.
DAILY_PLAN_APP_URL=https://titan-plan.anvil.app
AGENT_API_KEY=
# Optional: 0 pauses the run without touching Nexus (pc_plan_parameters
# AGENT_ENABLED is the normal switch, editable in the app).
DAILY_PLAN_AGENT_ENABLED=1
# Twilio — copy the three values from the Hub Transfers app's Anvil
# Secrets. Blank = texts are logged to ai_agent_log but not sent.
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
# true = log texts, never send (first-morning safety)
SMS_TEST_MODE=false
'''
anchor = "\n# Behavior (defaults are fine)\n"
assert anchor in env
env = env.replace(anchor, block + anchor)
(DST / ".env.example").write_bytes((env.replace("\n", "\r\n") if crlf else env).encode("utf-8"))
print("patched .env.example")
