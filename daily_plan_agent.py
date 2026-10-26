"""
daily_plan_agent.py — Titan Daily Plan: the agent's morning run (v1.0).

What this does, once per weekday at AGENT_RUN_TIME (pc_plan_parameters,
Eastern; 06:30 by default):

  1. Asks the Titan Daily Plan Anvil app to build today's proposal
     (POST /_/api/agent/propose, shared secret in X-Agent-Key) and
     waits for the background task (GET /_/api/agent/status).
     The APP chooses the lines — deterministic, from the flag scores,
     the fill % and the capacity model. Nothing here decides a line.
  2. Writes the narrative for the 08:30 Daily meeting with Claude,
     grounded in the run result + pc_flag_definitions +
     the approved rules in pc_plan_rule_register, and stores it in
     pc_agent_proposal.rationale (the 'Agent proposal' popup shows it).
     Since svc-1.1 the day's lesson (nugget_agent.py, migration 073)
     sits on top of it: "Today's lesson - <concept>: <two sentences>".
     svc-1.2 (app agent v1.2, 2026-09-18): the app's planned-short rule -
     a gated sibling rides with its order only when X06 says the stock is
     due in by the plan date; every other gated sibling stays off the
     plan and the order is proposed SHORT. The run result carries
     n_short / short[]; the narrative names them, the text counts them.
     svc-1.3 (2026-09-24): tick() also drives rush_agent.tick() - the rush
     lane poll (migration 091), every RUSH_POLL_MINUTES on weekdays.
  3. Texts the DAILY_PLAN_PROPOSAL contacts in
     dbo.sms_notification_contacts (Twilio), honoring the same kill
     switch as every other Titan text: global_parameters.sms_enabled.
     Every text and every run is logged to dbo.ai_agent_log.

Wiring: worker.py calls tick() inside its poll loop (cheap; checks the
clock at most every 30 s) and the run itself happens on a daemon
thread so the chat queue never waits on it.

Manual run (for testing, from the service folder):
    python daily_plan_agent.py                  # today (or next Monday)
    python daily_plan_agent.py 2026-09-08       # a specific day
    python daily_plan_agent.py --no-sms         # narrative only
    python daily_plan_agent.py --force          # even if published / disabled
    python daily_plan_agent.py --narrative-only # skip the app run; re-write
                                                #   the narrative for the
                                                #   latest proposal + SMS
    python daily_plan_agent.py --with-retro     # retro of the previous
                                                #   business day first (the
                                                #   scheduled run always does)

Config (.env): DAILY_PLAN_APP_URL, AGENT_API_KEY, TWILIO_* — see
config.py / .env.example. Missing app URL or key = module stays off and
says so once in the log.
"""

import json
import logging
import sys
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from anthropic import Anthropic

import config
import db

log = logging.getLogger("titan-ai.daily-plan")
# twilio logs every request header at INFO — keep the service log readable
logging.getLogger("twilio").setLevel(logging.WARNING)

TZ = ZoneInfo(config.DAILY_PLAN_TZ)
NOTIFICATION_TYPE = "DAILY_PLAN_PROPOSAL"
RUN_ACTION = "DAILY_PLAN_AGENT_RUN"
EXECUTED_BY = "titan-ai-service"
AGENT_VERSION = "svc-1.4"          # 1.1: lesson; 1.2: proposed SHORT; 1.3: rush lane tick; 1.4: morning retry window

_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)


# ── small helpers ─────────────────────────────────────────────────────

def _enabled():
    return bool(config.DAILY_PLAN_APP_URL and config.AGENT_API_KEY
                and config.DAILY_PLAN_AGENT_ENABLED)


def _plan_date_for(today):
    """Same rule as the app's _next_business_day(): today if it is a
    weekday, otherwise the following Monday."""
    d = today
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _params():
    """AGENT_* rows from pc_plan_parameters (titan_ai_svc has SELECT)."""
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT param_code, param_value FROM dbo.pc_plan_parameters "
                    "WHERE param_code LIKE %s", ("AGENT%",))
        return {r["param_code"]: (r["param_value"] or "").strip()
                for r in cur.fetchall()}
    finally:
        conn.close()


def _run_time(params):
    raw = params.get("AGENT_RUN_TIME") or "06:30"
    try:
        hh, mm = raw.split(":")[:2]
        return int(hh), int(mm)
    except Exception:
        log.warning("AGENT_RUN_TIME '%s' unreadable — using 06:30", raw)
        return 6, 30


def _retry_until(params):
    """AGENT_RETRY_UNTIL (HH:MM, default 08:00): the scheduler keeps
    re-trying a failed morning run until this time. 1.4."""
    raw = params.get("AGENT_RETRY_UNTIL") or "08:00"
    try:
        hh, mm = raw.split(":")[:2]
        return int(hh), int(mm)
    except Exception:
        log.warning("AGENT_RETRY_UNTIL '%s' unreadable — using 08:00", raw)
        return 8, 0


def _retry_minutes(params):
    """AGENT_RETRY_MINUTES (default 5): gap between retries. 1.4."""
    try:
        return max(1.0, float(params.get("AGENT_RETRY_MINUTES") or 5))
    except Exception:
        return 5.0


def _already_ran(plan_date):
    """A proposal for plan_date generated in the last 12 h (SQL clock on
    both sides) means this morning's run already happened — e.g. the
    service restarted after 06:30, or Dave pressed 'Run agent' first."""
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT TOP 1 proposal_id FROM dbo.pc_agent_proposal
            WHERE plan_date = %s
              AND DATEDIFF(minute, generated_at, SYSDATETIME()) BETWEEN 0 AND 720
            ORDER BY generated_at DESC
        """, (plan_date,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def _log_action(action_type, new_value, reason, sku=None):
    """Audit row in dbo.ai_agent_log (house pattern from the Hub app)."""
    try:
        conn = db._connect()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO dbo.ai_agent_log
                    (action_type, sku, old_value, new_value, reason,
                     action_timestamp, executed_by)
                VALUES (%s, %s, NULL, %s, %s, GETDATE(), %s)
            """, (action_type[:50], sku, new_value, reason, EXECUTED_BY))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.exception("ai_agent_log write failed (%s)", action_type)


# ── 1. the app run ────────────────────────────────────────────────────

def _api(path):
    return config.DAILY_PLAN_APP_URL.rstrip("/") + "/_/api" + path


def _headers():
    return {"X-Agent-Key": config.AGENT_API_KEY}


def request_proposal(plan_date, force=False):
    """POST /agent/propose then poll /agent/status until the background
    task finishes. Returns the task's result dict (status success /
    skipped / error)."""
    body = {"plan_date": plan_date.isoformat(), "force": bool(force)}
    r = requests.post(_api("/agent/propose"), json=body, headers=_headers(),
                      timeout=60)
    if r.status_code == 401:
        raise RuntimeError("Daily Plan app rejected the agent key (401) — "
                           "AGENT_API_KEY in .env must equal the Anvil "
                           "Secret AGENT_API_KEY")
    r.raise_for_status()
    started = r.json()
    if started.get("status") != "started":
        raise RuntimeError(f"propose did not start: {started}")
    task_id = started["task_id"]
    log.info("Proposal task %s started for %s", task_id, plan_date)

    deadline = time.monotonic() + config.DAILY_PLAN_MAX_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(config.DAILY_PLAN_POLL_SECONDS)
        s = requests.get(_api("/agent/status"), params={"task_id": task_id},
                         headers=_headers(), timeout=60)
        s.raise_for_status()
        st = s.json()
        if st.get("status") == "done":
            return st.get("result") or {"status": "error",
                                        "message": "task returned nothing"}
        if st.get("status") == "error":
            raise RuntimeError(f"status poll error: {st.get('message')}")
    raise RuntimeError(f"proposal task {task_id} did not finish within "
                       f"{config.DAILY_PLAN_MAX_WAIT_SECONDS}s")


# ── 2. the narrative ──────────────────────────────────────────────────

def _flag_definitions():
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT flag_code, category, flag_name, description, weight,
                   threshold_value
            FROM dbo.pc_flag_definitions
            ORDER BY category, flag_code
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _active_rules(plan_date):
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT rule_id, rule_kind, title, description, scope_type,
                   scope_value, effect_flag_code, score_adjustment,
                   gate_override_code, new_weight, new_threshold,
                   effective_from, expires_on, cause_key, decision_note
            FROM dbo.pc_plan_rule_register
            WHERE status = 'APPROVED'
              AND effective_from <= %s
              AND (expires_on IS NULL OR expires_on >= %s)
            ORDER BY rule_id
        """, (plan_date, plan_date))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _latest_proposal(plan_date):
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT TOP 1 proposal_id, status, capacity_inches, proposed_inches,
                   generated_at
            FROM dbo.pc_agent_proposal
            WHERE plan_date = %s ORDER BY generated_at DESC
        """, (plan_date,))
        hdr = cur.fetchone()
        if not hdr:
            return None, []
        cur.execute("""
            SELECT rank_no, nx_order_numb, nx_rel_numb, nx_item_no, nx_sku,
                   proposed_tier, load_inches, priority_score, gate_codes, flag_codes, reason
            FROM dbo.pc_agent_proposal_line
            WHERE proposal_id = %s ORDER BY rank_no
        """, (hdr["proposal_id"],))
        return dict(hdr), [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
        try:
            return float(v)
        except Exception:
            return str(v)
    return v


NARRATIVE_SYSTEM = """You are the Titan Daily Plan agent at Titan Flow Control. Every weekday morning you write the short narrative that Production Control and Sales read before the 08:30 Daily meeting, explaining the ship-plan proposal the planning engine just built.

Ground rules:
- Explain the proposal in terms of TITAN'S rules — the flag codes and their weights, gates (X flags), the fill target (a percentage of the day's work-inch capacity, the rest held for same-day rush), the horizon, and any approved exception rules. Never present a choice as your opinion; every "why" points at a rule, a flag, a date or a number in the data you were given.
- Use only the facts provided. Do not invent orders, customers, quantities, dates or reasons. If something is not in the data, do not mention it.
- Gated orders are DECISIONS for people, not verdicts: name what gate holds them and what would release them (the flag descriptions say what each gate means).
- Split decisions are orders too big for one day or bigger than the per-line cap: name them and say the engine left them for PC to decide.
- Orders proposed SHORT (planned_short): the order is on the plan but one or more of its lines were left OFF because a gate holds them (no stock, committed elsewhere, on hold, or a PO due after the plan date). Name each short line with its gate and what would release it, and say the rest of the order is planned without it. A gated line that DID ride along has stock due in by the plan date (its reason says 'stock due in <date>'): mention that the order depends on that PO landing.
- Plain text only. No markdown, no bullets, no headers with # or *. Short paragraphs separated by one blank line. Refer to lines as "order 123456-001-20 / SKU" - the order number, the release number, the e21 item number (e.g. 595613-001-20), then the SKU - always all three parts, exactly as given; a sales order can have several releases and several lines of the same SKU on different dates, so the release and item are part of the name. Keep it under 350 words — the app shows the full line list under this text, so do NOT enumerate every line. Name a line only when it is notable: the highest-scoring group (say how many lines and what flags make the score), any single line over a quarter of the fill target, every Stretch line, and the gated and split cases. Summarize the rest by count and reason ("the other 30 Musts are late orders on high-dollar books, oldest ship-by first").
- Write in this order: (1) capacity basis and fill; (2) what was chosen and why, grouped by reason; (3) Stretch lines; (4) gated orders that need a decision, then the orders proposed short; (5) split decisions; (6) what was left out and why (beyond horizon, zero-touch); (7) at most three questions for the meeting — bounded, factual questions about specific orders, never "why was this a bad decision".
"""


def write_narrative(plan_date, result, proposal_hdr, proposal_lines):
    """Ask Claude for the meeting narrative; returns the text."""
    ctx = {
        "plan_date": plan_date.isoformat(),
        "weekday": plan_date.strftime("%A"),
        "run_result": {k: v for k, v in result.items()
                       if k not in ("lines", "gated", "oversize", "short", "blocked")},
        "proposed_lines": result.get("lines") or proposal_lines,
        "gated_top": result.get("gated") or [],
        "planned_short": result.get("short") or [],       # app agent v1.2
        "blocked_orders": result.get("blocked") or [],
        "split_decisions": result.get("oversize") or [],
        "flag_definitions": _flag_definitions(),
        "approved_rules": _active_rules(plan_date),
        "proposal_header": proposal_hdr,
    }
    user = ("Write today's narrative from this data.\n\n"
            + json.dumps(_jsonable(ctx), indent=1, default=str))
    t0 = time.monotonic()
    resp = _client.messages.create(
        model=config.AGENT_MODEL,
        max_tokens=config.DAILY_PLAN_NARRATIVE_MAX_TOKENS,
        system=NARRATIVE_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    # Block types matter: a model that thinks before writing returns a
    # thinking block first, and those tokens count against max_tokens.
    blocks = [f"{getattr(b, 'type', '?')}:{len(getattr(b, 'text', '') or getattr(b, 'thinking', '') or '')}"
              for b in resp.content]
    log.info("Narrative: %s chars, %s in / %s out tokens, %s ms, stop=%s, blocks=%s",
             len(text), resp.usage.input_tokens, resp.usage.output_tokens,
             int((time.monotonic() - t0) * 1000), resp.stop_reason, blocks)
    if resp.stop_reason == "max_tokens":
        log.warning("Narrative hit the %s-token ceiling — text is cut off; "
                    "raise DAILY_PLAN_NARRATIVE_MAX_TOKENS",
                    config.DAILY_PLAN_NARRATIVE_MAX_TOKENS)
        text += "\n\n[narrative cut off at the token limit]"
    return text


def store_narrative(proposal_id, text):
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.pc_agent_proposal SET rationale = %s "
                    "WHERE proposal_id = %s", (text, proposal_id))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ── 3. the text message ───────────────────────────────────────────────

def _sms_enabled(conn):
    """THE gate, same as the Hub app: global_parameters.sms_enabled = 1.
    Fails closed on a missing row, 0/NULL, or any error."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT parameter_value FROM dbo.global_parameters "
                    "WHERE parameter_name = 'sms_enabled'")
        row = cur.fetchone()
        if row is None:
            log.warning("global_parameters.sms_enabled is MISSING — SMS off")
            return False
        val = row["parameter_value"]
        if val is None or float(val) < 1:
            log.info("global_parameters.sms_enabled = %s — SMS off", val)
            return False
        return True
    except Exception:
        log.exception("Could not read sms_enabled — SMS off (fail closed)")
        return False


def _contacts(conn, notification_type=NOTIFICATION_TYPE):
    cur = conn.cursor()
    cur.execute("""
        SELECT contact_name, phone_number, role
        FROM dbo.sms_notification_contacts
        WHERE is_active = 1 AND notification_types LIKE %s
        ORDER BY contact_name
    """, (f"%{notification_type}%",))
    # One text per NUMBER: several contact rows share a phone (e.g. a
    # person and the department line they answer), so merge the names.
    by_number = {}
    for r in cur.fetchall():
        to = _e164(r["phone_number"])
        if to in by_number:
            by_number[to]["contact_name"] += f" / {r['contact_name']}"
        else:
            by_number[to] = {"contact_name": r["contact_name"],
                             "phone_number": to, "role": r["role"]}
    return list(by_number.values())


def _e164(number):
    n = str(number or "").strip()
    if n.startswith("+"):
        return n
    digits = "".join(ch for ch in n if ch.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits


def build_sms(plan_date, result):
    r = result
    day = plan_date.strftime("%a %m/%d")
    cap = float(r.get("capacity_inches") or 0)
    fill = r.get("fill_pct")
    basis = (f"{int(round(float(fill) * 100))}% of {cap:,.0f} cap" if fill
             else f"cap {cap:,.0f}")
    parts = [
        f"Titan Daily Plan - agent proposal for {day}: "
        f"{r.get('n_proposed', 0)} lines + {r.get('n_stretch', 0)} stretch = "
        f"{float(r.get('proposed_inches') or 0):,.0f} of "
        f"{float(r.get('target_inches') or 0):,.0f} target in ({basis}).",
    ]
    if r.get("already_planned_inches"):
        parts.append(f"PC had {float(r['already_planned_inches']):,.0f} in already planned.")
    bits = []
    if r.get("n_gated"):
        bits.append(f"{r['n_gated']} gated")
    if r.get("n_short"):
        bits.append(f"{r['n_short']} line(s) short")
    if r.get("n_split_needed"):
        bits.append(f"{r['n_split_needed']} split decision(s)")
    if r.get("n_zero_touch_skipped"):
        bits.append(f"{r['n_zero_touch_skipped']} zero-touch left off")
    if bits:
        parts.append(" / ".join(bits) + ".")
    parts.append("Review in the Daily Plan app (Agent proposal) before 8:30.")
    return " ".join(parts)


def send_sms(plan_date, result, dry_run=False):
    """Text every DAILY_PLAN_PROPOSAL contact with the proposal summary."""
    return send_sms_text(build_sms(plan_date, result), NOTIFICATION_TYPE,
                         plan_date, dry_run=dry_run)


def send_sms_text(message, notification_type, plan_date, dry_run=False):
    """Text every contact tagged notification_type (one text per number).
    Returns a list of per-contact result dicts (also logged to ai_agent_log).
    Shared by the proposal (DAILY_PLAN_PROPOSAL) and the retro
    (DAILY_PLAN_RETRO, retro_agent.py)."""
    log.info("SMS %s (%s chars): %s", notification_type, len(message), message)
    conn = db._connect()
    try:
        contacts = _contacts(conn, notification_type)
        if not contacts:
            log.warning("No active %s contacts — nobody to text", notification_type)
            return []
        enabled = _sms_enabled(conn)
        creds_ok = all([config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN,
                        config.TWILIO_PHONE_NUMBER])
        test_mode = dry_run or config.SMS_TEST_MODE
        client = None
        if enabled and creds_ok and not test_mode:
            from twilio.rest import Client       # only needed when live
            client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        elif enabled and not creds_ok and not test_mode:
            log.warning("TWILIO_* not set in .env — texts logged, not sent")

        results = []
        for c in contacts:
            to = _e164(c["phone_number"])
            res = {"to_number": to, "name": c["contact_name"], "success": False}
            if not enabled:
                res["status"] = "disabled"
                res["error_message"] = "global_parameters.sms_enabled is 0/missing"
            elif test_mode:
                res["success"] = True
                res["status"] = "test_mode"
                res["sid"] = "TEST_MODE_" + datetime.now().strftime("%Y%m%d%H%M%S")
            elif client is None:
                res["status"] = "no_credentials"
                res["error_message"] = "TWILIO_* not set in .env"
            else:
                try:
                    msg = client.messages.create(body=message[:1600],
                                                 from_=config.TWILIO_PHONE_NUMBER,
                                                 to=to)
                    res.update(success=True, status=msg.status, sid=msg.sid)
                except Exception as e:           # TwilioRestException etc.
                    res["status"] = "failed"
                    res["error_message"] = str(e)
            results.append(res)
            _log_action(
                f"SMS_{notification_type}",
                new_value=f"To: {to} ({c['contact_name']}), Status: {res.get('status')}",
                reason=(f"SID: {res.get('sid')}" if res["success"]
                        else f"Error: {res.get('error_message')}")
                       + f" | plan {plan_date.isoformat()}",
            )
            log.info("SMS -> %s (%s): %s", c["contact_name"], to, res.get("status"))
        return results
    finally:
        conn.close()


# ── the run ───────────────────────────────────────────────────────────

def run_daily(plan_date=None, force=False, sms=True, narrative_only=False,
              trigger="manual", with_retro=None):
    """The whole morning: retro of the previous business day (scheduled
    runs, or --with-retro) -> app run -> narrative -> SMS. Never raises;
    the outcome goes to the log and to ai_agent_log."""
    plan_date = plan_date or _plan_date_for(datetime.now(TZ).date())
    if with_retro is None:
        with_retro = (trigger == "schedule")
    if with_retro and not narrative_only:
        try:
            import retro_agent
            rres = retro_agent.run_retro(sms=sms, trigger=trigger)   # its own try/except
            _note_outcome("retro", (rres or {}).get("status") in ("success", "skipped"))
        except Exception:
            log.exception("Retro step failed — continuing with the proposal")
            _note_outcome("retro", False)
    log.info("Daily Plan agent run starting for %s (%s)", plan_date, trigger)
    t0 = time.monotonic()
    try:
        if narrative_only:
            hdr, lines = _latest_proposal(plan_date)
            if not hdr:
                raise RuntimeError(f"no proposal exists for {plan_date}")
            # Rebuild the summary the app run would have returned. The
            # fill % comes from the live parameter; the target is the
            # capacity × that (the app run reports the same numbers).
            try:
                fill_pct = float(_params().get("AGENT_FILL_PCT") or 80) / 100.0
            except Exception:
                fill_pct = None
            cap_in = float(hdr["capacity_inches"] or 0)
            result = {"status": "success", "proposal_id": hdr["proposal_id"],
                      "capacity_inches": cap_in,
                      "proposed_inches": float(hdr["proposed_inches"] or 0),
                      "n_proposed": sum(1 for l in lines if l["proposed_tier"] != "Stretch"
                                        and l["rank_no"] > 0),
                      "n_stretch": sum(1 for l in lines if l["proposed_tier"] == "Stretch"),
                      "target_inches": (round(cap_in * fill_pct, 1) if fill_pct
                                        else float(hdr["proposed_inches"] or 0)),
                      "fill_pct": fill_pct,
                      "note": "narrative-only rerun: gated / split / left-out "
                              "counts are not available (they come from the app run)"}
        else:
            result = request_proposal(plan_date, force=force)

        status = result.get("status")
        if status == "skipped":
            log.info("App skipped the run: %s", result.get("message"))
            _log_action(RUN_ACTION, f"plan {plan_date}: skipped", result.get("message"))
            _note_outcome("proposal", True)          # nothing to retry
            return result
        if status != "success":
            raise RuntimeError(result.get("message") or f"app returned {status}")
        # Belt and braces for the Labor Day case (2026-09-07): an app version
        # without the capacity guard still returns a 0-line, 0-capacity
        # "success". Treat it as skipped - no narrative, no text.
        if float(result.get("capacity_inches") or 0) <= 0 and not result.get("n_proposed"):
            msg = f"plan {plan_date}: zero capacity (holiday / no roster) - nothing to send"
            log.warning(msg)
            _log_action(RUN_ACTION, msg, trigger)
            _note_outcome("proposal", True)          # nothing to retry
            return {"status": "skipped", "message": msg}

        proposal_id = result["proposal_id"]
        hdr, lines = _latest_proposal(plan_date)
        summary = (f"proposal {proposal_id}: {result.get('n_proposed')} lines + "
                   f"{result.get('n_stretch')} stretch, "
                   f"{result.get('proposed_inches')} of {result.get('target_inches')} in")
        if result.get("n_gated") is not None:
            summary += (f"; {result.get('n_gated')} gated, "
                        f"{result.get('n_split_needed')} split, "
                        f"{result.get('n_short') or 0} short")
        log.info("%s — %s", "Narrative-only rerun" if narrative_only else "App run done",
                 summary)

        # lesson of the day (nugget-1.0.0): picked before the narrative so a
        # narrative failure never loses the day's lesson. Never raises; None
        # when NUGGET_ENABLED = 0 or migration 073 is not in yet.
        lesson = None
        try:
            import nugget_agent
            lesson = nugget_agent.pick_lesson(plan_date, result, sms=sms, trigger=trigger)
        except Exception:
            log.exception("Lesson step failed — narrative goes out without one")

        # narrative — a failure here must not stop the text going out
        try:
            text = write_narrative(plan_date, result, hdr, lines)
            if lesson:
                text = nugget_agent.compose(lesson, text)
            store_narrative(proposal_id, text)
            log.info("Narrative stored on proposal %s%s", proposal_id,
                     " (with lesson)" if lesson else "")
        except Exception:
            log.exception("Narrative failed — proposal %s has no rationale", proposal_id)
            _log_action(RUN_ACTION, f"plan {plan_date}: narrative FAILED",
                        f"proposal {proposal_id}")

        if sms:
            send_sms(plan_date, result)

        _log_action(RUN_ACTION, f"plan {plan_date}: {summary}",
                    f"{trigger}; {int(time.monotonic() - t0)}s; {AGENT_VERSION}")
        _note_outcome("proposal", True)
        return result
    except Exception as e:
        log.exception("Daily Plan agent run FAILED for %s", plan_date)
        _log_action(RUN_ACTION, f"plan {plan_date}: FAILED", str(e)[:1000])
        _note_outcome("proposal", False)
        return {"status": "error", "message": str(e)}


# ── scheduler hook for worker.py ──────────────────────────────────────

_state = {"last_check": 0.0, "ran_for": None, "thread": None,
          "announced": False,
          # 1.4 retry window: how the two parts of the morning went, when
          # the last attempt started, how many attempts so far, and whether
          # the "window closed" line was logged.
          "retro_ok": None, "proposal_ok": None, "last_attempt": 0.0,
          "attempts": 0, "window_closed": False}


def _note_outcome(part, ok):
    """run_daily / _retry_run report each part here; tick() reads it."""
    _state[part + "_ok"] = bool(ok)


def _retry_run(plan_date):
    """A later attempt at whatever failed this morning (1.4). Runs on the
    agent thread. The retro and the proposal are independent: only the
    part that has not succeeded is tried again. If the proposal exists by
    now (the app finished it, or someone pressed Run agent) it counts as
    done - the narrative / texts of a half-finished first attempt are not
    repeated."""
    try:
        if not _state["retro_ok"]:
            import retro_agent
            rres = retro_agent.run_retro(sms=True, trigger="schedule-retry")
            _note_outcome("retro", (rres or {}).get("status") in ("success", "skipped"))
        if not _state["proposal_ok"]:
            if _already_ran(plan_date):
                log.info("Retry: proposal for %s exists now — treating as done", plan_date)
                _note_outcome("proposal", True)
            else:
                run_daily(plan_date=plan_date, trigger="schedule-retry", with_retro=False)
    except Exception:
        log.exception("Retry attempt failed")


def _launch(target, kwargs, name):
    th = threading.Thread(target=target, kwargs=kwargs, name=name, daemon=True)
    _state["thread"] = th
    _state["last_attempt"] = time.monotonic()
    _state["attempts"] += 1
    th.start()
    return th


def tick():
    """Call from the worker loop. Fires run_daily() on a daemon thread once
    per weekday at/after AGENT_RUN_TIME (Eastern). Cheap otherwise. Also
    drives the retro's reading poll + ageing (retro_agent.tick). 1.4: if a
    part of the morning failed, tries again every AGENT_RETRY_MINUTES
    until AGENT_RETRY_UNTIL."""
    try:
        import retro_agent
        retro_agent.tick()
    except Exception:
        log.exception("retro_agent.tick failed")
    try:                                   # rush lane (rush_agent.py, 091)
        import rush_agent
        rush_agent.tick()
    except Exception:
        log.exception("rush_agent.tick failed")
    if not _enabled():
        if not _state["announced"]:
            if not config.DAILY_PLAN_AGENT_ENABLED:
                log.info("Daily Plan agent PAUSED (DAILY_PLAN_AGENT_ENABLED=0 in .env)")
            else:
                log.info("Daily Plan agent OFF — DAILY_PLAN_APP_URL and/or "
                         "AGENT_API_KEY missing from .env")
            _state["announced"] = True
        return
    now_mono = time.monotonic()
    if now_mono - _state["last_check"] < 30:
        return
    _state["last_check"] = now_mono

    th = _state["thread"]
    if th is not None and th.is_alive():
        return
    now = datetime.now(TZ)
    if now.weekday() >= 5:
        return
    plan_date = now.date()
    if (_state["ran_for"] == plan_date and _state["retro_ok"]
            and _state["proposal_ok"]):
        return                                  # the usual case all day
    try:
        params = _params()
    except Exception:
        log.exception("Could not read pc_plan_parameters — will retry")
        return
    if params.get("AGENT_ENABLED", "1") != "1":
        return

    if _state["ran_for"] == plan_date:
        # ---- 1.4 retry window: the first attempt is done; anything left? --
        if _state["retro_ok"] is None or _state["proposal_ok"] is None:
            # the attempt thread is gone (checked above) but never reported:
            # count the silent part as failed so the window can act on it
            for p in ("retro", "proposal"):
                if _state[p + "_ok"] is None:
                    _state[p + "_ok"] = False
        if (now.hour, now.minute) >= _retry_until(params):
            if not _state["window_closed"]:
                _state["window_closed"] = True
                left = [p for p in ("retro", "proposal") if not _state[p + "_ok"]]
                msg = (f"plan {plan_date}: retry window closed at "
                       f"{now.strftime('%H:%M')} after {_state['attempts']} attempt(s); "
                       f"still failed: {', '.join(left)}")
                log.error(msg)
                _log_action(RUN_ACTION, msg, "schedule-retry gave up")
            return
        if now_mono - _state["last_attempt"] < _retry_minutes(params) * 60:
            return
        left = [p for p in ("retro", "proposal") if not _state[p + "_ok"]]
        log.warning("Retry %d for %s at %s — %s", _state["attempts"], plan_date,
                    now.strftime("%H:%M"), ", ".join(left))
        _launch(_retry_run, {"plan_date": plan_date}, "daily-plan-agent-retry")
        return

    hh, mm = _run_time(params)
    if (now.hour, now.minute) < (hh, mm):
        return
    # new day: reset the window
    _state.update(ran_for=plan_date, retro_ok=None, proposal_ok=None,
                  attempts=0, window_closed=False)
    if _already_ran(plan_date):
        log.info("Proposal for %s already generated this morning — not re-running",
                 plan_date)
        _state.update(retro_ok=True, proposal_ok=True)
        return

    _launch(run_daily, {"plan_date": plan_date, "trigger": "schedule"},
            "daily-plan-agent")
    log.info("Daily Plan agent run launched for %s at %s",
             plan_date, now.strftime("%H:%M %Z"))


# ── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    args = [a for a in sys.argv[1:]]
    flags = {a for a in args if a.startswith("--")}
    dates = [a for a in args if not a.startswith("--")]
    pd = date.fromisoformat(dates[0]) if dates else None
    # A hand-run command is explicit intent: it needs the app URL + key but
    # ignores DAILY_PLAN_AGENT_ENABLED (that switch pauses the SCHEDULER).
    if not (config.DAILY_PLAN_APP_URL and config.AGENT_API_KEY) \
            and "--narrative-only" not in flags:
        print("Set DAILY_PLAN_APP_URL and AGENT_API_KEY in .env to call the app")
        sys.exit(2)
    out = run_daily(plan_date=pd, force="--force" in flags,
                    sms="--no-sms" not in flags,
                    narrative_only="--narrative-only" in flags,
                    trigger="cli", with_retro=("--with-retro" in flags))
    print(json.dumps(_jsonable({k: v for k, v in out.items()
                                if k not in ("lines", "gated", "oversize", "short", "blocked")}),
                     indent=1, default=str))
