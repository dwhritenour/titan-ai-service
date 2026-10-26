"""
rush_agent.py — Titan Daily Plan: the rush lane (rush-1.0.0, 2026-09-24).

Every RUSH_POLL_MINUTES (pc_plan_parameters, default 5) on weekdays between
RUSH_WINDOW_START and RUSH_WINDOW_END (Eastern; 06:30–17:30), ask the app
for new rush lines (POST /_/api/agent/rush). The APP holds the rule and
does the work — vw_pc_rush_candidates (expedited A05 or PC's A04 flag,
ship-by on or before the next business day, ungated, not on the plan),
proposes each new line as Must / RUSH (one tap to confirm) and records it
in pc_plan_rush so nothing is proposed or announced twice. This module
only turns the answer into ONE text per sales order for the
DAILY_PLAN_RUSH contacts (Tara, Kimberly, Dave), through the same Twilio
path and kill switch as every other Titan text.

Why the service and not the app: Anvil has no scheduler; worker.py already
ticks every 30 s for the retro, so the poll rides there
(daily_plan_agent.tick -> rush_agent.tick).

Manual run (from the service folder):
    python rush_agent.py            # one poll, texts go out
    python rush_agent.py --no-sms   # one poll, texts logged only
    python rush_agent.py --force    # ignore RUSH_ENABLED
"""

import json
import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import config
import db

log = logging.getLogger("titan-ai.rush")

TZ = ZoneInfo(config.DAILY_PLAN_TZ)
NOTIFICATION_TYPE = "DAILY_PLAN_RUSH"
RUN_ACTION = "DAILY_PLAN_RUSH_POLL"
AGENT_VERSION = "rush-1.0.1"
WINDOW_START = (6, 40)     # after the 06:30 proposal has filled (2026-09-25: the
                           # 06:30:04 poll beat the 06:30:38 fill, which superseded it)
WINDOW_END = (17, 30)      # UPS is gone; anything now is tomorrow's, caught at 06:30


def _params():
    conn = db._connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT param_code, param_value FROM dbo.pc_plan_parameters "
                    "WHERE param_code LIKE %s", ("RUSH%",))
        return {r["param_code"]: (r["param_value"] or "").strip() for r in cur.fetchall()}
    finally:
        conn.close()


def _api(path):
    return config.DAILY_PLAN_APP_URL.rstrip("/") + "/_/api" + path


def poll(force=False):
    """One call to the app. Returns its result dict."""
    r = requests.post(_api("/agent/rush"), json={"force": bool(force)},
                      headers={"X-Agent-Key": config.AGENT_API_KEY}, timeout=60)
    if r.status_code == 401:
        raise RuntimeError("Daily Plan app rejected the agent key (401)")
    r.raise_for_status()
    return r.json()


def build_sms(order, plan_date, after_cutoff, today):
    """'RUSH 610908-001 JOHN M ELLSWORTH - MILWAUKEE, WI: 610908-001-10 / CV42SSV0600 x1
    pick&ship, UPS 2DAY, ship today - PROPOSED on today's plan, confirm in the app.'"""
    lines = order.get("lines") or []
    parts = []
    for l in lines[:4]:
        q = l.get("qty")
        qtxt = f" x{int(q) if q and float(q).is_integer() else q}" if q else ""
        kind = ("pick&ship" if l.get("zero_touch")
                else f"{float(l.get('load_inches') or 0):,.1f} in")
        parts.append(f"{l['line']} / {l.get('sku') or ''}{qtxt} {kind}")
    if len(lines) > 4:
        parts.append(f"+{len(lines) - 4} more")
    how = " / ".join(x for x in (order.get("carrier"), order.get("mos")) if x)
    when = "ship today" if str(order.get("ship_by") or "")[:10] == today else \
           f"ship by {str(order.get('ship_by') or '')[:10]}"
    if order.get("n_proposed"):
        where = (f"PROPOSED for {plan_date} (after {order.get('cutoff') or 'cutoff'}, cannot ship today)"
                 if after_cutoff else "PROPOSED on today's plan")
        tail = f" - {where}, confirm in the app."
    else:
        tail = " - already on the plan."
    basis = " (PC rush flag)" if order.get("basis") == "A04" else ""
    return (f"RUSH {order['order']} {order.get('customer') or ''}: "
            + "; ".join(parts) + f", {how}, {when}{basis}" + tail)[:1600]


def announce(result, sms=True):
    """One text per order in the result. Returns the count sent (or logged)."""
    from daily_plan_agent import send_sms_text, _log_action
    n = 0
    plan_date = result.get("plan_date")
    today = result.get("today")
    after_cutoff = bool(result.get("after_cutoff"))
    for o in result.get("orders") or []:
        o["cutoff"] = result.get("cutoff")
        msg = build_sms(o, plan_date, after_cutoff, today)
        try:
            send_sms_text(msg, NOTIFICATION_TYPE, datetime.fromisoformat(plan_date).date(),
                          dry_run=not sms)
            n += 1
        except Exception:
            log.exception("rush text failed for %s", o.get("order"))
    if result.get("n_new"):
        _log_action(RUN_ACTION,
                    f"plan {plan_date}: {result.get('n_new')} new rush line(s), "
                    f"{result.get('n_proposed')} proposed, {n} order text(s)",
                    f"{'after cutoff; ' if after_cutoff else ''}{AGENT_VERSION}")
    return n


def run_once(force=False, sms=True):
    res = poll(force=force)
    if res.get("status") == "skipped":
        log.info("Rush poll skipped: %s", res.get("message"))
        return res
    if res.get("status") != "success":
        raise RuntimeError(res.get("message") or f"app returned {res.get('status')}")
    if res.get("n_new"):
        log.info("Rush poll: %s candidate(s), %s new, %s proposed for %s%s",
                 res.get("n_candidates"), res.get("n_new"), res.get("n_proposed"),
                 res.get("plan_date"), " (after cutoff)" if res.get("after_cutoff") else "")
        res["n_texts"] = announce(res, sms=sms)
    return res


# ── scheduler hook (called from daily_plan_agent.tick) ────────────────

_state = {"last_poll": 0.0, "announced_off": False}


def tick():
    """Cheap. Polls the app every RUSH_POLL_MINUTES inside the weekday
    window. Never raises."""
    if not (config.DAILY_PLAN_APP_URL and config.AGENT_API_KEY
            and config.DAILY_PLAN_AGENT_ENABLED):
        return
    now = datetime.now(TZ)
    if now.weekday() >= 5:
        return
    hm = (now.hour, now.minute)
    if hm < WINDOW_START or hm > WINDOW_END:
        return
    mono = time.monotonic()
    try:
        minutes = float(_params().get("RUSH_POLL_MINUTES") or 5)
    except Exception:
        minutes = 5.0
    if mono - _state["last_poll"] < max(1.0, minutes) * 60:
        return
    _state["last_poll"] = mono
    try:
        run_once()
    except Exception:
        log.exception("Rush poll failed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not (config.DAILY_PLAN_APP_URL and config.AGENT_API_KEY):
        print("Set DAILY_PLAN_APP_URL and AGENT_API_KEY in .env to call the app")
        sys.exit(2)
    out = run_once(force="--force" in flags, sms="--no-sms" not in flags)
    print(json.dumps(out, indent=1, default=str))
