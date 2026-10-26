"""
nugget_agent.py — Titan Daily Plan: the lesson of the day (nugget-1.0.0,
2026-09-17). Companion to daily_plan_agent.py / retro_agent.py /
ledger_agent.py.

Dave, 2026-09-16: the agent "must act as an expert in production control
and a graduate-level professor - both directing and instructing"; the
students are everyone, and "training time has to be in brief nuggets."
So every morning the Daily Plan app picks one two-sentence lesson per
channel (daily_plan_nuggets.py, migration 073) and this side:

  1. asks for it during the morning run, right before the narrative is
     written, and puts it at the top of the narrative:
         Today's lesson - <concept>: <two sentences> <live number>
  2. texts the same line to the DAILY_PLAN_NUGGET contacts (shadow:
     Dave only, until he widens the tag),
  3. on NUGGET_DIGEST_DAY at NUGGET_DIGEST_TIME texts the week's digest
     to DAILY_PLAN_NUGGET_DIGEST: what was taught, what fired but was
     not taught, what comes next.

The APP picks and logs (idempotent per day + channel); this side
relays, composes and texts - the same split as the ledger and retro.

Wiring: daily_plan_agent.run_daily() calls pick_lesson() + compose();
worker.py calls tick() in its poll loop for the digest.

Manual:
    python nugget_agent.py                  # pick today's lesson (no re-pick if logged)
    python nugget_agent.py 2026-09-18       # a specific plan day
    python nugget_agent.py --no-sms
    python nugget_agent.py --digest         # this week's digest, now
"""

import logging
import sys
import threading
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

import config
import db
import daily_plan_agent as dpa

log = logging.getLogger("titan-ai.nugget")
TZ = ZoneInfo(config.DAILY_PLAN_TZ)
NOTIFY = "DAILY_PLAN_NUGGET"                 # the daily lesson (Dave only, for now)
NOTIFY_DIGEST = "DAILY_PLAN_NUGGET_DIGEST"   # the Friday digest (Dave)
LESSON_ACTION = "DAILY_PLAN_NUGGET"
DIGEST_ACTION = "DAILY_PLAN_NUGGET_DIGEST"
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4}


def _params():
    """NUGGET_* rows from pc_plan_parameters (titan_ai_svc has SELECT)."""
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT param_code, param_value FROM dbo.pc_plan_parameters "
                    "WHERE param_code LIKE %s", ("NUGGET%",))
        return {r["param_code"]: (r["param_value"] or "").strip() for r in cur.fetchall()}
    finally:
        conn.close()


def _hhmm(raw, default):
    try:
        hh, mm = raw.split(":")[:2]
        return int(hh), int(mm)
    except Exception:
        return default


def _request(body):
    r = requests.post(dpa._api("/agent/nugget"), json=body, headers=dpa._headers(),
                      timeout=120)
    if r.status_code == 401:
        raise RuntimeError("Daily Plan app rejected the agent key (401)")
    r.raise_for_status()
    return r.json()


# ── 1. the lesson of the day ─────────────────────────────────────────

def _run_numbers(result):
    """The handful of run numbers the app's triggers read; never the lines."""
    keys = ("n_gated", "n_split_needed", "n_stretch", "n_proposed",
            "n_zero_touch_skipped", "capacity_inches", "target_inches",
            "proposed_inches", "fill_pct")
    return {k: result.get(k) for k in keys if result is not None and result.get(k) is not None}


def lesson_line(pick):
    """The line people see, at the top of the narrative and in the text."""
    return f"Today's lesson - {pick['concept_name']}: {pick['text']}"


def compose(lesson, narrative):
    """Lesson on top, blank line, the narrative Claude wrote."""
    if not lesson:
        return narrative
    return f"{lesson_line(lesson)}\n\n{narrative or ''}".rstrip()


def pick_lesson(plan_date, result=None, sms=True, trigger="manual"):
    """Ask the app for the day's lessons (MEETING + ASSEMBLY). Returns the
    MEETING pick (dict) or None. Never raises - a lesson must never stop
    the proposal."""
    try:
        params = _params()
        if params.get("NUGGET_ENABLED", "1") != "1":
            log.info("Teaching nuggets off (NUGGET_ENABLED=0)")
            return None
        res = _request({"action": "pick", "plan_date": plan_date.isoformat(),
                        "channels": ["MEETING", "ASSEMBLY"],
                        "run": _run_numbers(result)})
        st = res.get("status")
        if st == "skipped":
            log.info("Lesson skipped: %s", res.get("message"))
            return None
        if st != "success":
            raise RuntimeError(res.get("message") or f"app returned {st}")
        picks = {p.get("channel"): p for p in res.get("picks") or [] if p.get("status") == "success"}
        meeting = picks.get("MEETING")
        for ch, p in picks.items():
            log.info("Lesson %s %s: %s (%s%s) - %s", plan_date, ch, p.get("concept_code"),
                     p.get("reason"), ", already logged" if p.get("already_logged") else "",
                     (p.get("text") or "")[:120])
        if meeting is None:
            dpa._log_action(LESSON_ACTION, f"lesson {plan_date}: nothing picked",
                            f"{trigger}; picks={list(picks)}")
            return None
        if sms and not meeting.get("already_logged"):
            dpa.send_sms_text(lesson_line(meeting)[:600], NOTIFY, plan_date)
        dpa._log_action(LESSON_ACTION,
                        f"lesson {plan_date}: {meeting.get('concept_code')} ({meeting.get('reason')})"
                        + (f"; floor: {picks['ASSEMBLY'].get('concept_code')}" if 'ASSEMBLY' in picks else ""),
                        f"{trigger}; fired={','.join(meeting.get('fired') or []) or '-'}"[:1000])
        return meeting
    except Exception as e:
        log.exception("Lesson pick FAILED for %s", plan_date)
        dpa._log_action(LESSON_ACTION, f"lesson {plan_date}: FAILED", str(e)[:1000])
        return None


# ── 2. the Friday digest ─────────────────────────────────────────────

def build_digest_sms(week):
    """One text. Example:
    Lessons this week (09/14-09/18): Mon One work-inch (foundation); Tue
    Capacity is people (foundation); ... Fired, not taught: BAND_OUT,
    RUSH_HEAVY. Next up: The score; If Time lines; ... Library 57, taught 9."""
    ws = date.fromisoformat(week["week_start"]).strftime("%m/%d")
    we = date.fromisoformat(week["week_end"]).strftime("%m/%d")
    taught = [l for l in week.get("lessons") or [] if l.get("channel") == "MEETING"]
    parts = [f"Lessons this week ({ws}-{we}):"]
    if taught:
        parts.append("; ".join(
            f"{date.fromisoformat(str(l['plan_date'])[:10]).strftime('%a')} {l['concept_name']} "
            f"({(l.get('reason') or '').replace('trigger:', '')})" for l in taught) + ".")
    else:
        parts.append("none logged.")
    if week.get("fired_untaught"):
        parts.append("Fired, not taught: " + ", ".join(week["fired_untaught"]) + ".")
    if week.get("next_up"):
        parts.append("Next up: " + "; ".join(n["concept_name"] for n in week["next_up"]) + ".")
    c = week.get("counts") or {}
    parts.append(f"Library {c.get('active', '-')}, taught {c.get('taught_meeting', '-')}"
                 f" (floor {c.get('taught_assembly', '-')}).")
    if week.get("pending_rules"):
        parts.append(f"Rule candidates awaiting you: {week['pending_rules']} (#retrev).")
    return " ".join(parts)[:900]


def run_digest(end_day=None, sms=True, trigger="manual"):
    """The week's digest for the week holding end_day. Never raises."""
    end_day = end_day or datetime.now(TZ).date()
    log.info("Lesson digest starting for the week of %s (%s)", end_day, trigger)
    try:
        week = _request({"action": "digest", "end_date": end_day.isoformat()})
        if week.get("status") != "success":
            raise RuntimeError(week.get("message") or f"app returned {week.get('status')}")
        text = build_digest_sms(week)
        log.info("Lesson digest: %s", text)
        if sms:
            dpa.send_sms_text(text, NOTIFY_DIGEST, end_day)
        dpa._log_action(DIGEST_ACTION, f"digest {week['week_start']}..{week['week_end']}: "
                        f"{len(week.get('lessons') or [])} lesson(s) logged", trigger)
        return {"status": "success", "text": text, "week": week}
    except Exception as e:
        log.exception("Lesson digest FAILED for %s", end_day)
        dpa._log_action(DIGEST_ACTION, f"digest {end_day}: FAILED", str(e)[:1000])
        return {"status": "error", "message": str(e)}


def _digest_sent_this_week(day):
    """A digest logged in the last 4 days (SQL clock)."""
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT TOP 1 action_id FROM dbo.ai_agent_log
            WHERE action_type = %s AND new_value LIKE 'digest %%'
              AND new_value NOT LIKE '%%FAILED%%'
              AND DATEDIFF(hour, action_timestamp, GETDATE()) BETWEEN 0 AND 96
            ORDER BY action_timestamp DESC
        """, (DIGEST_ACTION,))
        return cur.fetchone() is not None
    except Exception:
        log.exception("ai_agent_log read failed - assuming no digest yet")
        return False
    finally:
        conn.close()


# ── 3. the scheduler hook (digest only; the lesson rides the morning run)

_state = {"last_check": 0.0, "sent_for": None, "thread": None}


def tick():
    """Call from the worker loop. Sends the digest once per week on
    NUGGET_DIGEST_DAY at/after NUGGET_DIGEST_TIME. Cheap otherwise."""
    if not (config.DAILY_PLAN_APP_URL and config.AGENT_API_KEY):
        return
    now_mono = time.monotonic()
    if now_mono - _state["last_check"] < 60:
        return
    _state["last_check"] = now_mono
    now = datetime.now(TZ)
    try:
        params = _params()
    except Exception:
        log.exception("Could not read NUGGET_* parameters - will retry")
        return
    if params.get("NUGGET_ENABLED", "1") != "1":
        return
    day_raw = (params.get("NUGGET_DIGEST_DAY") or "").strip().lower()[:3]
    if day_raw not in _WEEKDAYS:
        return                                   # blank = no digest
    if now.weekday() != _WEEKDAYS[day_raw]:
        return
    if _state["sent_for"] == now.date():
        return
    hh, mm = _hhmm(params.get("NUGGET_DIGEST_TIME") or "15:30", (15, 30))
    if (now.hour, now.minute) < (hh, mm):
        return
    if _digest_sent_this_week(now.date()):
        _state["sent_for"] = now.date()
        return
    th = _state["thread"]
    if th is not None and th.is_alive():
        return
    _state["sent_for"] = now.date()
    th = threading.Thread(target=run_digest, kwargs={"end_day": now.date(), "trigger": "schedule"},
                          name="daily-plan-nugget-digest", daemon=True)
    _state["thread"] = th
    th.start()
    log.info("Lesson digest launched at %s", now.strftime("%H:%M %Z"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    args = sys.argv[1:]
    flags = {a for a in args if a.startswith("--")}
    vals = [a for a in args if not a.startswith("--")]
    day = date.fromisoformat(vals[0]) if vals else None
    if "--digest" in flags:
        out = run_digest(day, sms="--no-sms" not in flags, trigger="cli")
        print(out.get("text") or out)
    else:
        pick = pick_lesson(day or dpa._plan_date_for(datetime.now(TZ).date()),
                           sms="--no-sms" not in flags, trigger="cli")
        print(lesson_line(pick) if pick else "no lesson picked (see log)")
