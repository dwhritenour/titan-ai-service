"""
retro_agent.py — Titan Daily Plan: the retro-review half of the agent
(v1.1, 2026-09-07). Companion to daily_plan_agent.py.

Four jobs, all against Nexus with the titan_ai_svc login:

  1. Morning run (called by daily_plan_agent right before the proposal):
     POST /_/api/agent/retro to the Daily Plan app for the previous
     business day. The APP classifies every planned line and writes the
     variance ledger + asks the day's questions (RETRO_MAX_QUESTIONS,
     2 PC + 1 Sales floor). This side writes the narrative onto
     pc_plan_retro.narrative and texts each SIDE that has questions
     (DAILY_PLAN_RETRO_PC / DAILY_PLAN_RETRO_SALES) with the #retro link,
     once per day. When every asked question is answered - or aged out -
     the day is stamped complete (review_notified_at) and logged; Dave
     checks #retrev on his own schedule (he declined a text).
  2. Reading poll (every couple of minutes from the worker loop): each
     answered question with no proposed reading gets a ONE-SENTENCE
     restatement from Claude plus a suggested evidence class and cause
     key from pc_plan_cause_keys. Written to proposed_*; Dave confirms in
     the app (confirmed_* stay his - always Dave).
  3. Ageing: questions unanswered after RETRO_UNKNOWN_AFTER_DAYS business
     days close as CLOSED_UNKNOWN / Unknown.
  4. Monday recurrence scan: a confirmed cause_key at N >= 3 in the
     trailing 14 days (Verified/Probable) becomes a PROPOSED row in
     pc_plan_rule_register, once, and Dave is texted (DAILY_PLAN_RULE_CANDIDATE).

Manual:
    python retro_agent.py                 # retro for the previous business day
    python retro_agent.py 2026-09-08      # a specific day
    python retro_agent.py --no-sms
    python retro_agent.py --readings      # just run the reading poll once
    python retro_agent.py --scan          # just run the recurrence scan
"""

import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from anthropic import Anthropic

import config
import db
import daily_plan_agent as dpa

log = logging.getLogger("titan-ai.retro")
TZ = ZoneInfo(config.DAILY_PLAN_TZ)
NOTIFY_PC = "DAILY_PLAN_RETRO_PC"          # Tara, Kimberly - the #retro link
NOTIFY_SALES = "DAILY_PLAN_RETRO_SALES"    # the Sales owner - the #retro link
NOTIFY_REVIEW = "DAILY_PLAN_RETRO_REVIEW"  # reserved - Dave declined the completion text
NOTIFY_RULES = "DAILY_PLAN_RULE_CANDIDATE" # Dave - the Monday scan proposed register rows


def _link(hash_):
  return config.DAILY_PLAN_APP_URL.rstrip("/") + "/#" + hash_
RUN_ACTION = "DAILY_PLAN_RETRO_RUN"
_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _prev_business_day(d):
  d = d - timedelta(days=1)
  while d.weekday() >= 5:
    d -= timedelta(days=1)
  return d


# ── 1. morning run ────────────────────────────────────────────────────

def request_retro(plan_date, force=False):
  body = {"plan_date": plan_date.isoformat(), "force": bool(force)}
  r = requests.post(dpa._api("/agent/retro"), json=body, headers=dpa._headers(),
                    timeout=120)
  if r.status_code == 401:
    raise RuntimeError("Daily Plan app rejected the agent key (401)")
  r.raise_for_status()
  return r.json()


RETRO_SYSTEM = """You are the Titan Daily Plan agent at Titan Flow Control, writing the short retro that Production Control and Sales read at the 08:30 Daily meeting about YESTERDAY's published plan.

Ground rules:
- Report what the records show, in Titan's terms: planned lines that shipped or were worked, lines removed with a recorded reason, lines with no recorded activity, ship-by dates that moved after publish, orders that shipped without being on the plan, and how much of the rush reserve (capacity minus the fill target) those unplanned shipments used.
- Every inferred outcome comes from documents, not the floor: say "shows no recorded activity", never "was not worked". A line can be built with nobody touching the kiosk.
- This is a data finding, never a people finding. No blame, no "should have", no speculation about motives. Name orders exactly as given ("order 123456 / SKU").
- The questions were already chosen and sent by the system (listed in the data); restate them briefly so the meeting knows what is open, and name who they went to. Do not invent new questions.
- Plain text only, no markdown, short paragraphs separated by one blank line, under 250 words. Order: (1) the day in numbers (planned vs moved, reserve used); (2) what did not move and why the records can't say; (3) removals and their recorded reasons; (4) the Sales-side items (dates moved, unplanned shipments); (5) the open questions and who owes an answer; (6) anything the numbers suggest about the RULES (a flag, a threshold, the fill %) — as an observation for Dave, not a recommendation to change anything.
"""


def write_retro_narrative(plan_date, result):
  ctx = {"plan_date": plan_date.isoformat(), "weekday": plan_date.strftime("%A"),
         "result": {k: v for k, v in result.items() if k != "lines"},
         "lines": result.get("lines") or []}
  resp = _client.messages.create(
      model=config.MODEL, max_tokens=config.DAILY_PLAN_NARRATIVE_MAX_TOKENS,
      system=RETRO_SYSTEM,
      messages=[{"role": "user", "content": "Write yesterday's retro from this data.\n\n"
                                            + json.dumps(dpa._jsonable(ctx), indent=1, default=str)}])
  text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
  log.info("Retro narrative: %s chars, %s in / %s out tokens, stop=%s",
           len(text), resp.usage.input_tokens, resp.usage.output_tokens, resp.stop_reason)
  if resp.stop_reason == "max_tokens":
    text += "\n\n[narrative cut off at the token limit]"
  return text


def store_retro_narrative(plan_date, text):
  conn = db._connect()
  try:
    cur = conn.cursor()
    cur.execute("UPDATE dbo.pc_plan_retro SET narrative = %s WHERE plan_date = %s",
                (text, plan_date))
    conn.commit()
    return cur.rowcount
  finally:
    conn.close()


def build_side_sms(plan_date, r, side, n):
  day = plan_date.strftime("%a %m/%d")
  c = r.get("counts") or {}
  moved = c.get("SHIPPED", 0) + c.get("WORKED", 0)
  who = "Sales" if side == "SALES" else "Production Control"
  return (f"Titan Daily Plan - retro for {day}: {moved} of {r.get('n_planned', 0)} planned "
          f"lines moved. {n} question{'s' if n != 1 else ''} for {who} - answer here: "
          f"{_link('retro')}")


def _stamp(plan_date, column):
  """Set pc_plan_retro.<column> = now if it is still NULL. Returns True when
  this call did the stamping (so a text goes out exactly once)."""
  conn = db._connect()
  try:
    cur = conn.cursor()
    cur.execute(f"UPDATE dbo.pc_plan_retro SET {column} = SYSDATETIME() "
                f"WHERE plan_date = %s AND {column} IS NULL", (plan_date,))
    conn.commit()
    return cur.rowcount > 0
  finally:
    conn.close()


def send_side_texts(plan_date, result):
  """One text per side that has questions, each once per day (stamped)."""
  qs = result.get("questions") or []
  n_sales = sum(1 for q in qs if q.get("to") == "SALES")
  n_pc = len(qs) - n_sales
  if n_pc and _stamp(plan_date, "pc_notified_at"):
    dpa.send_sms_text(build_side_sms(plan_date, result, "PC", n_pc), NOTIFY_PC, plan_date)
  if n_sales and _stamp(plan_date, "sales_notified_at"):
    dpa.send_sms_text(build_side_sms(plan_date, result, "SALES", n_sales), NOTIFY_SALES, plan_date)
  if not qs:
    log.info("Retro %s: no questions - no side texts", plan_date)


def run_retro(plan_date=None, force=False, sms=True, trigger="manual"):
  """The whole retro morning for one day. Never raises."""
  plan_date = plan_date or _prev_business_day(datetime.now(TZ).date())
  log.info("Retro run starting for %s (%s)", plan_date, trigger)
  try:
    result = request_retro(plan_date, force=force)
    st = result.get("status")
    if st == "skipped":
      log.info("Retro skipped: %s", result.get("message"))
      dpa._log_action(RUN_ACTION, f"retro {plan_date}: skipped", result.get("message"))
      return result
    if st != "success":
      raise RuntimeError(result.get("message") or f"app returned {st}")
    c = result.get("counts") or {}
    summary = (f"{c.get('SHIPPED', 0)} shipped, {c.get('WORKED', 0)} worked, "
               f"{c.get('UNTOUCHED', 0)} untouched, {c.get('REMOVED_WITH_REASON', 0)}+"
               f"{c.get('REMOVED_NO_REASON', 0)} removed, {c.get('DATE_MOVED', 0)} dates moved, "
               f"{c.get('UNPLANNED_SHIP', 0)} unplanned; {result.get('n_questions')} question(s) "
               f"of {result.get('n_askable')} askable")
    log.info("Retro run done for %s — %s", plan_date, summary)
    try:
      text = write_retro_narrative(plan_date, result)
      store_retro_narrative(plan_date, text)
    except Exception:
      log.exception("Retro narrative failed for %s", plan_date)
    if sms:
      send_side_texts(plan_date, result)
      check_completion()          # a no-question day completes immediately
    dpa._log_action(RUN_ACTION, f"retro {plan_date}: {summary}", trigger)
    return result
  except Exception as e:
    log.exception("Retro run FAILED for %s", plan_date)
    dpa._log_action(RUN_ACTION, f"retro {plan_date}: FAILED", str(e)[:1000])
    return {"status": "error", "message": str(e)}


# ── 2. reading poll ───────────────────────────────────────────────────

READING_SYSTEM = """You classify one answer to a Titan Daily Plan retro question. Return ONLY a JSON object:
{"reading": "<one sentence, plain, restating the answer as a cause — what happened, in the answerer's terms>",
 "evidence_class": "Verified" | "Probable" | "Unverified" | "Disputed" | "Unknown",
 "cause_key": "<one key from the allowed list>",
 "expected_date": "<YYYY-MM-DD or null>"}
Rules: Verified only when the answer states a checkable fact (a document, a date, a person, a part number); Probable when it is a plausible first-hand account; Unverified when it is hearsay or vague; Disputed when it contradicts the records shown; Unknown when the answer does not actually answer. Never add facts. Never judge the person. If nothing fits, cause_key "other".
expected_date: the date the answer says the line can be built or will ship, as a calendar date. Resolve relative words ("tomorrow", "Friday", "next week", "end of month") against the "today" given with the variance. null when the answer gives no date or only "when the stock comes in"."""


def _pending_readings(conn, limit=10):
  cur = conn.cursor()
  cur.execute("""
      SELECT TOP %s variance_id, plan_date, nx_order_numb, nx_sku, variance_case,
             routed_to, system_explanation, question_text, answer_text, answered_by
      FROM dbo.pc_plan_variance
      WHERE answer_text IS NOT NULL AND proposed_reading IS NULL
        AND reading_confirmed_at IS NULL
      ORDER BY answered_at
  """, (limit,))
  return cur.fetchall()


def _cause_keys(conn):
  cur = conn.cursor()
  cur.execute("SELECT cause_key, label, side, variance_kind FROM dbo.pc_plan_cause_keys "
              "WHERE is_active = 1 ORDER BY sort_order")
  return cur.fetchall()


def propose_reading(row, causes):
  allowed = [c["cause_key"] for c in causes]
  user = ("Allowed cause keys: " + json.dumps([{"key": c["cause_key"], "label": c["label"],
                                                 "side": c["side"]} for c in causes])
          + "\n\nToday: " + datetime.now(TZ).strftime("%Y-%m-%d (%A)")
          + "\n\nVariance: " + json.dumps(dpa._jsonable(row), default=str))
  resp = _client.messages.create(model=config.MODEL, max_tokens=2000, system=READING_SYSTEM,
                                 messages=[{"role": "user", "content": user}])
  text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
  start, end = text.find("{"), text.rfind("}")
  data = json.loads(text[start:end + 1])
  reading = str(data.get("reading", "")).strip()[:500]
  ev = data.get("evidence_class")
  if ev not in ("Verified", "Probable", "Unverified", "Disputed", "Unknown"):
    ev = "Unverified"
  ck = data.get("cause_key")
  if ck not in allowed:
    ck = "other"
  exp = data.get("expected_date")          # 096
  try:
    exp = date.fromisoformat(str(exp)[:10]) if exp else None
  except Exception:
    exp = None
  return reading, ev, ck, exp


def poll_readings():
  """Called from the worker loop every READING_POLL_SECONDS; also --readings.
  Proposes readings for new answers, then checks whether any retro day is
  now fully answered (Dave's text)."""
  n = _propose_pending()
  try:
    check_completion()
  except Exception:
    log.exception("completion check failed")
  return n


def _propose_pending():
  conn = db._connect()
  try:
    rows = _pending_readings(conn)
    if not rows:
      return 0
    causes = _cause_keys(conn)
    n = 0
    for row in rows:
      try:
        reading, ev, ck, exp = propose_reading(row, causes)
      except Exception:
        log.exception("Reading failed for variance %s", row["variance_id"])
        continue
      cur = conn.cursor()
      cur.execute("""
          UPDATE dbo.pc_plan_variance
          SET proposed_reading = %s, proposed_evidence_class = %s, proposed_cause_key = %s,
              expected_date = %s
          WHERE variance_id = %s AND proposed_reading IS NULL
      """, (reading, ev, ck, exp, row["variance_id"]))
      # 096: a STALLED hold tied to this answer takes the date (released
      # when the date is today / next business day, else expires the day
      # before so the line is proposable on it). Material holds are NOT
      # touched here - those still go through Dave's confirm (decision 3).
      try:
        cur.execute("EXEC dbo.sp_pc_stall_answered @variance_id = %s, @expected_date = %s",
                    (row["variance_id"], exp))
        st = cur.fetchone() or {}
        if st.get("action"):
          log.info("Stalled hold %s for variance %s: %s", st.get("action"),
                   row["variance_id"], st.get("expires_on") or "")
      except Exception:
        log.exception("sp_pc_stall_answered failed for variance %s", row["variance_id"])
      # 100 (decision 3, 2026-10-12): a material answer places the hold NOW.
      # The proc checks the cause against HOLD_CAUSE_KEYS and the evidence
      # against HOLD_AUTO_MIN_EVIDENCE itself, skips lines already held,
      # and sets the expiry from the answer's date. Dave still reviews:
      # a confirm with a non-hold cause releases it (daily_plan_retro).
      try:
        cur.execute("EXEC dbo.sp_pc_material_answered @variance_id = %s, @expected_date = %s",
                    (row["variance_id"], exp))
        mh = cur.fetchone() or {}
        while cur.nextset():              # the place proc's own summary comes first
          last = cur.fetchone()
          if last is not None:
            mh = last
        if mh.get("action") in ("placed", "dated"):
          log.info("Material hold %s from PC answer, variance %s (%s / %s), expires %s",
                   mh.get("action"), row["variance_id"], ck, ev, mh.get("expires_on"))
      except Exception:
        log.exception("sp_pc_material_answered failed for variance %s", row["variance_id"])
      conn.commit()
      n += 1
      log.info("Reading proposed for variance %s (%s / %s%s): %s",
               row["variance_id"], ev, ck, (f" / {exp}" if exp else ""), reading[:120])
    return n
  finally:
    conn.close()


# ── 3. ageing ─────────────────────────────────────────────────────────

def check_completion():
  """Completion: once per retro day, when every asked question is answered
  (or closed as Unknown by ageing). A day with no questions completes at
  once. Stamped in review_notified_at (the column name predates Dave
  declining the text) so it happens exactly once."""
  conn = db._connect()
  try:
    cur = conn.cursor()
    cur.execute("""
        SELECT r.plan_date,
               (SELECT COUNT(*) FROM dbo.pc_plan_variance v
                 WHERE v.plan_date = r.plan_date AND v.asked_at IS NOT NULL) AS n_asked,
               (SELECT COUNT(*) FROM dbo.pc_plan_variance v
                 WHERE v.plan_date = r.plan_date AND v.asked_at IS NOT NULL
                   AND v.answer_text IS NULL AND v.resolution = 'OPEN') AS n_open,
               (SELECT COUNT(*) FROM dbo.pc_plan_variance v
                 WHERE v.plan_date = r.plan_date AND v.asked_at IS NOT NULL
                   AND v.answer_text IS NOT NULL) AS n_answered,
               (SELECT COUNT(*) FROM dbo.pc_plan_variance v
                 WHERE v.plan_date = r.plan_date AND v.asked_at IS NOT NULL
                   AND v.answer_text IS NOT NULL AND v.routed_to = 'SALES') AS n_sales,
               (SELECT COUNT(*) FROM dbo.pc_plan_variance v
                 WHERE v.plan_date = r.plan_date AND v.asked_at IS NOT NULL
                   AND v.resolution = 'CLOSED_UNKNOWN') AS n_unknown
        FROM dbo.pc_plan_retro r
        WHERE r.review_notified_at IS NULL
          AND r.run_at >= DATEADD(day, -14, SYSDATETIME())
    """)
    days = cur.fetchall()
  finally:
    conn.close()
  n_sent = 0
  for d in days:
    if int(d["n_open"] or 0) > 0:
      continue
    pd = d["plan_date"]
    if hasattr(pd, "date"):
      pd = pd.date()
    if not _stamp(pd, "review_notified_at"):
      continue
    day = pd.strftime("%a %m/%d")
    n_asked, n_ans, n_unk = int(d["n_asked"] or 0), int(d["n_answered"] or 0), int(d["n_unknown"] or 0)
    if n_asked == 0:
      msg = f"Titan Daily Plan - retro {day}: no questions today, nothing to review."
    else:
      n_sales = int(d["n_sales"] or 0)
      parts = f"{n_ans} of {n_asked} answered (PC {n_ans - n_sales}, Sales {n_sales})"
      if n_unk:
        parts += f", {n_unk} closed as Unknown"
      msg = f"Titan Daily Plan - retro {day}: {parts}. Review the readings: {_link('retrev')}"
    # Dave declined the completion text (2026-09-07: "I will remember to
    # check on my own"). The day is stamped complete and logged; the
    # #retrev form shows it. NOTIFY_REVIEW stays defined for the day he
    # changes his mind - one line to re-enable.
    log.info("Retro complete: %s", msg)
    dpa._log_action("DAILY_PLAN_RETRO_COMPLETE", msg[:1000], "all asked questions answered or aged out")
    n_sent += 1
  return n_sent


def close_unknown():
  conn = db._connect()
  try:
    cur = conn.cursor()
    cur.execute("SELECT param_value FROM dbo.pc_plan_parameters WHERE param_code = 'RETRO_UNKNOWN_AFTER_DAYS'")
    r = cur.fetchone()
    try:
      days = int(float(r["param_value"])) if r and r["param_value"] else 5
    except (TypeError, ValueError):
      days = 5
    cal_days = int(days * 7 / 5) + 1        # business days -> calendar, roughly
    cur.execute("""
        UPDATE dbo.pc_plan_variance
        SET resolution = 'CLOSED_UNKNOWN', evidence_class = 'Unknown', resolved_at = GETDATE()
        WHERE resolution = 'OPEN' AND asked_at IS NOT NULL AND answer_text IS NULL
          AND asked_at < DATEADD(day, -%s, GETDATE())
    """, (cal_days,))
    n = cur.rowcount
    conn.commit()
    if n:
      log.info("Closed %s unanswered question(s) as Unknown (older than %s business days)", n, days)
  finally:
    conn.close()
  if n:
    try:
      check_completion()
    except Exception:
      log.exception("completion check failed")
  return n


# ── 4. Monday recurrence scan ─────────────────────────────────────────

def recurrence_scan(n_min=3, window_days=14):
  """cause_key seen >= n_min times (confirmed, Verified/Probable) in the
  window -> one PROPOSED register row, unless a live row for that cause
  already exists. Returns the new titles."""
  conn = db._connect()
  try:
    cur = conn.cursor()
    cur.execute("""
        SELECT v.cause_key, k.label, COUNT(*) AS n,
               STRING_AGG(CAST(v.variance_id AS VARCHAR(10)), ',') AS ids,
               MAX(v.variance_kind) AS kind
        FROM dbo.pc_plan_variance v
        JOIN dbo.pc_plan_cause_keys k ON k.cause_key = v.cause_key
        WHERE v.reading_confirmed_at IS NOT NULL
          AND v.evidence_class IN ('Verified','Probable')
          AND v.plan_date >= DATEADD(day, -%s, CAST(GETDATE() AS DATE))
          AND v.cause_key NOT IN ('other')
        GROUP BY v.cause_key, k.label
        HAVING COUNT(*) >= %s
    """, (window_days, n_min))
    hits = cur.fetchall()
    made = []
    for h in hits:
      # "AS ok" is load-bearing: pymssql as_dict=True raises
      # ColumnsWithoutNamesError on an unnamed column (2026-09-24: this
      # is why the scan never wrote a row on 09-14 or 09-21)
      cur.execute("""
          SELECT 1 AS ok FROM dbo.pc_plan_rule_register
          WHERE cause_key = %s AND status IN ('PROPOSED','APPROVED','NEEDS_BUILD')
      """, (h["cause_key"],))
      if cur.fetchone():
        continue
      title = f"Recurring cause: {h['label']} ({h['n']}x in {window_days} days)"[:120]
      cur.execute("""
          INSERT INTO dbo.pc_plan_rule_register
              (rule_kind, status, title, description, scope_type, cause_key,
               recurrence_count, evidence_variance_ids, proposed_by)
          VALUES ('OTHER', 'PROPOSED', %s, %s, 'GLOBAL', %s, %s, %s, 'agent')
      """, (title,
            (f"The confirmed cause '{h['label']}' recurred {h['n']} times in the last "
             f"{window_days} days (variance ids {h['ids']}). Rule candidate for Dave: "
             "decide whether a flag, weight, threshold or exception should change. "
             "No planning logic changes until this row is APPROVED.")[:1000],
            h["cause_key"], int(h["n"]), (h["ids"] or "")[:200]))
      made.append(title)
    conn.commit()
    if made:
      log.info("Recurrence scan: %s rule candidate(s) proposed", len(made))
    return made
  finally:
    conn.close()


def text_candidates(made, day=None, sms=True):
  """The Monday scan proposed register rows: say so to NOTIFY_RULES (Dave)
  and log it. Until 2026-09-19 candidates were only logged, so a week
  could pass with PROPOSED rows nobody had seen."""
  if not made:
    return None
  day = day or datetime.now(TZ).date()
  items = "; ".join(m.replace("Recurring cause: ", "") for m in made)
  text = (f"Titan Daily Plan - rule candidates ({day.strftime('%a %m/%d')}): {items}. "
          f"Nothing changes until a row is APPROVED. Review: {config.DAILY_PLAN_APP_URL}/#retrev")
  dpa._log_action("DAILY_PLAN_RULE_CANDIDATE", "; ".join(made)[:1000],
                  "recurrence scan (N>=3 in 14 days)")
  if sms:
    dpa.send_sms_text(text[:600], NOTIFY_RULES, day)
  return text


# ── scheduler hooks ───────────────────────────────────────────────────

_state = {"last_poll": 0.0, "aged_on": None}


def tick():
  """Cheap. Reading poll every READING_POLL_SECONDS; ageing once a day."""
  if not (config.DAILY_PLAN_APP_URL and config.AGENT_API_KEY):
    return
  now = time.monotonic()
  if now - _state["last_poll"] < float(getattr(config, "RETRO_READING_POLL_SECONDS", 120)):
    return
  _state["last_poll"] = now
  try:
    poll_readings()
  except Exception:
    log.exception("reading poll failed")
  today = datetime.now(TZ).date()
  if _state["aged_on"] != today:
    _state["aged_on"] = today
    try:
      close_unknown()
    except Exception:
      log.exception("ageing failed")
    if today.weekday() == 0:               # Monday: the weekly loop, v1 = a query
      try:
        text_candidates(recurrence_scan(), today)
      except Exception:
        log.exception("recurrence scan failed")


if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                      handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
                                logging.StreamHandler(sys.stdout)])
  args = sys.argv[1:]
  flags = {a for a in args if a.startswith("--")}
  dates = [a for a in args if not a.startswith("--")]
  if "--readings" in flags:
    print("readings proposed:", poll_readings())
  elif "--scan" in flags:
    made = recurrence_scan()
    print(json.dumps(made, indent=1))
    if made:
      print(text_candidates(made, sms="--no-sms" not in flags))
  elif "--age" in flags:
    print("closed as unknown:", close_unknown())
  else:
    pd = date.fromisoformat(dates[0]) if dates else None
    out = run_retro(plan_date=pd, force="--force" in flags, sms="--no-sms" not in flags,
                    trigger="cli")
    print(json.dumps(dpa._jsonable({k: v for k, v in out.items() if k != "lines"}),
                     indent=1, default=str))
