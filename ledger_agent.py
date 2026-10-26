"""
ledger_agent.py — Titan Daily Plan: the capacity ledger (ledger-1.0.0,
2026-09-16). Companion to daily_plan_agent.py / retro_agent.py.

Dave, 2026-09-16: the one number he would be embarrassed by at month end
is the capacity number - "everything else is built around it." So the
model is judged in public every day: this module asks the Daily Plan app
to write yesterday's ledger row (estimate / published / actual capacity,
planned, shipped, done, the ratios and the band) and texts the one-line
verdict to the DAILY_PLAN_LEDGER contacts. Shadow mode: that tag is Dave
only until the ledger has shown two weeks inside the band.

The APP computes and stores (daily_plan_ledger.py, migration 069) - this
side only schedules, relays and texts, the same split as the retro.

Schedule: once per weekday at LEDGER_RUN_TIME (pc_plan_parameters,
default 08:45 Eastern - after the ~08:17 sales_orders_ship load and the
attendance snapshot). Re-computes LEDGER_DAYS_BACK business days each
run, so late ship rows and late attendance loads settle on their own.

Wiring: worker.py calls tick() in its poll loop (one line, next to
daily_plan_agent.tick()).

Manual:
    python ledger_agent.py                  # previous business day + days back
    python ledger_agent.py 2026-09-15       # ending at a specific day
    python ledger_agent.py 2026-09-15 --back 5
    python ledger_agent.py --no-sms
"""

import logging
import sys
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

import config
import db
import daily_plan_agent as dpa

log = logging.getLogger("titan-ai.ledger")
TZ = ZoneInfo(config.DAILY_PLAN_TZ)
NOTIFY = "DAILY_PLAN_LEDGER"          # Dave only, for now
RUN_ACTION = "DAILY_PLAN_LEDGER_RUN"


def _prev_business_day(d):
  d = d - timedelta(days=1)
  while d.weekday() >= 5:
    d -= timedelta(days=1)
  return d


def _params():
  """LEDGER_* rows from pc_plan_parameters (titan_ai_svc has SELECT)."""
  conn = db._connect()
  try:
    cur = conn.cursor()
    cur.execute("SELECT param_code, param_value FROM dbo.pc_plan_parameters "
                "WHERE param_code LIKE %s", ("LEDGER%",))
    return {r["param_code"]: (r["param_value"] or "").strip() for r in cur.fetchall()}
  finally:
    conn.close()


def _run_time(params):
  raw = params.get("LEDGER_RUN_TIME") or "08:45"
  try:
    hh, mm = raw.split(":")[:2]
    return int(hh), int(mm)
  except Exception:
    log.warning("LEDGER_RUN_TIME '%s' unreadable - using 08:45", raw)
    return 8, 45


def _already_ran(day):
  """A ledger run logged for this end day in the last 12 h (SQL clock)."""
  conn = db._connect()
  try:
    cur = conn.cursor()
    cur.execute("""
        SELECT TOP 1 action_id FROM dbo.ai_agent_log
        WHERE action_type = %s AND new_value LIKE %s
          AND DATEDIFF(minute, action_timestamp, GETDATE()) BETWEEN 0 AND 720
        ORDER BY action_timestamp DESC
    """, (RUN_ACTION, f"ledger {day.isoformat()}%"))
    return cur.fetchone() is not None
  except Exception:
    log.exception("ai_agent_log read failed - assuming not run")
    return False
  finally:
    conn.close()


# ── 1. the app run ────────────────────────────────────────────────────

def request_ledger(end_day=None, days_back=None):
  body = {}
  if end_day:
    body["plan_date"] = end_day.isoformat()
  if days_back:
    body["days_back"] = int(days_back)
  r = requests.post(dpa._api("/agent/ledger"), json=body, headers=dpa._headers(),
                    timeout=180)
  if r.status_code == 401:
    raise RuntimeError("Daily Plan app rejected the agent key (401)")
  r.raise_for_status()
  return r.json()


# ── 2. the text ───────────────────────────────────────────────────────

def _fmt(v, nd=0):
  if v is None:
    return "-"
  return f"{float(v):,.{nd}f}"


def build_sms(row, tolerance_pct):
  """One text, one verdict. Example:
  Ledger Tue 09/15: crew 14.5 -> cap 2,394 in. Shipped 1,740 in (0.73x).
  5-day 0.92x - within +/-10%. Planned 3,749 in (157% of cap), 161 shipped
  on plan (4%). Est 2,482 vs stamped 2,316 (93% attendance)."""
  d = date.fromisoformat(str(row["plan_date"])[:10])
  parts = [f"Ledger {d.strftime('%a %m/%d')}: crew {_fmt(row.get('actual_crew'), 1)} -> "
           f"cap {_fmt(row.get('actual_capacity_inches'))} in."]
  if row.get("shipped_inches") is not None:
    parts.append(f"Shipped {_fmt(row['shipped_inches'])} in "
                 f"({_fmt(row.get('daily_ratio'), 2)}x).")
  else:
    parts.append("Shipped: ship feed not loaded yet.")
  rr, rn, wb = row.get("rolling_ratio"), row.get("rolling_days"), row.get("within_band")
  if rr is not None:
    verdict = ("not judged yet" if wb is None else
               f"within +/-{tolerance_pct:g}%" if wb else
               f"OUTSIDE +/-{tolerance_pct:g}%")
    parts.append(f"{rn}-day {_fmt(rr, 2)}x - {verdict}.")
  if row.get("planned_final_inches"):
    parts.append(f"Planned {_fmt(row['planned_final_inches'])} in "
                 f"({_fmt(row.get('plan_load_pct'))}% of cap), "
                 f"{_fmt(row.get('shipped_planned_inches'))} shipped on plan "
                 f"({_fmt(row.get('attainment_pct'))}%).")
  if row.get("est_capacity_inches") and row.get("published_capacity_inches"):
    parts.append(f"Est {_fmt(row['est_capacity_inches'])} vs stamped "
                 f"{_fmt(row['published_capacity_inches'])} "
                 f"({_fmt(row.get('attendance_pct'))}% attendance).")
  return " ".join(parts)[:600]


# ── 3. the run ────────────────────────────────────────────────────────

def run_ledger(end_day=None, days_back=None, sms=True, trigger="manual"):
  """The whole ledger run for one end day. Never raises."""
  end_day = end_day or _prev_business_day(datetime.now(TZ).date())
  log.info("Ledger run starting for %s (%s)", end_day, trigger)
  try:
    result = request_ledger(end_day, days_back)
    st = result.get("status")
    if st == "skipped":
      log.info("Ledger skipped: %s", result.get("message"))
      dpa._log_action(RUN_ACTION, f"ledger {end_day}: skipped", result.get("message"))
      return result
    if st != "success":
      raise RuntimeError(result.get("message") or f"app returned {st}")
    rows = result.get("rows") or []
    if not rows:
      msg = f"no Published plan on {end_day} or the days behind it"
      log.info("Ledger: %s", msg)
      dpa._log_action(RUN_ACTION, f"ledger {end_day}: nothing to write", msg)
      return result
    latest = rows[-1]
    text = build_sms(latest, float(result.get("tolerance_pct") or 10))
    summary = (f"{len(rows)} day(s) written, latest {latest.get('plan_date')}: "
               f"cap {latest.get('actual_capacity_inches')} shipped {latest.get('shipped_inches')} "
               f"ratio {latest.get('daily_ratio')} rolling {latest.get('rolling_ratio')} "
               f"({latest.get('rolling_days')}d) band {latest.get('within_band')}")
    log.info("Ledger run done for %s - %s", end_day, summary)
    if sms:
      dpa.send_sms_text(text, NOTIFY, end_day)
    dpa._log_action(RUN_ACTION, f"ledger {end_day}: {summary}"[:1000], trigger)
    return result
  except Exception as e:
    log.exception("Ledger run FAILED for %s", end_day)
    dpa._log_action(RUN_ACTION, f"ledger {end_day}: FAILED", str(e)[:1000])
    return {"status": "error", "message": str(e)}


# ── 4. the scheduler hook ─────────────────────────────────────────────

_state = {"last_check": 0.0, "ran_for": None, "thread": None}


def tick():
  """Call from the worker loop. Runs once per weekday at/after
  LEDGER_RUN_TIME for the previous business day. Cheap otherwise."""
  if not (config.DAILY_PLAN_APP_URL and config.AGENT_API_KEY):
    return
  now_mono = time.monotonic()
  if now_mono - _state["last_check"] < 60:
    return
  _state["last_check"] = now_mono
  now = datetime.now(TZ)
  if now.weekday() >= 5:
    return
  end_day = _prev_business_day(now.date())
  if _state["ran_for"] == end_day:
    return
  try:
    params = _params()
  except Exception:
    log.exception("Could not read LEDGER_* parameters - will retry")
    return
  if params.get("LEDGER_ENABLED", "1") != "1":
    return
  hh, mm = _run_time(params)
  if (now.hour, now.minute) < (hh, mm):
    return
  if _already_ran(end_day):
    log.info("Ledger for %s already ran today - not re-running", end_day)
    _state["ran_for"] = end_day
    return
  th = _state["thread"]
  if th is not None and th.is_alive():
    return
  _state["ran_for"] = end_day
  th = threading.Thread(target=run_ledger, kwargs={"end_day": end_day, "trigger": "schedule"},
                        name="daily-plan-ledger", daemon=True)
  _state["thread"] = th
  th.start()
  log.info("Ledger run launched for %s at %s", end_day, now.strftime("%H:%M %Z"))


if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                      handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
                                logging.StreamHandler(sys.stdout)])
  args = sys.argv[1:]
  flags = {a for a in args if a.startswith("--")}
  vals = [a for a in args if not a.startswith("--")]
  back = None
  if "--back" in args:
    i = args.index("--back")
    back = int(args[i + 1]) if i + 1 < len(args) else None
    vals = [v for v in vals if v != str(back)]
  end = date.fromisoformat(vals[0]) if vals else None
  res = run_ledger(end, days_back=back, sms=("--no-sms" not in flags), trigger="cli")
  for r in res.get("rows") or []:
    print(f"{r['plan_date']}: est {r.get('est_capacity_inches')} | published "
          f"{r.get('published_capacity_inches')} (crew {r.get('published_crew')}) | actual "
          f"{r.get('actual_capacity_inches')} (crew {r.get('actual_crew')}) | planned "
          f"{r.get('planned_final_inches')} | shipped {r.get('shipped_inches')} "
          f"[{r.get('shipped_planned_inches')} on plan] | ratio {r.get('daily_ratio')} | "
          f"rolling {r.get('rolling_ratio')} ({r.get('rolling_days')}d) band {r.get('within_band')}")
  if res.get("status") != "success":
    print(res)
