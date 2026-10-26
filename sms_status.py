"""
sms_status.py — Titan texts: what did Twilio actually do with them?

The service logs every text as 'Status: queued' with its Twilio SID
(ai_agent_log, action_type SMS_*). 'queued' only means Twilio accepted it;
delivery (or a carrier rejection) happens afterwards and is never written
back. This asks Twilio for the final status of recent SIDs, per contact,
so "I am not getting the texts" can be answered from the record.

    python sms_status.py                      # every number, last 7 days
    python sms_status.py +19102479166         # one number
    python sms_status.py --days 14            # wider window
    python sms_status.py --failed             # only undelivered / failed

Read-only: one Twilio GET per SID (fine for a few hundred), no DB writes.
Needs TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN in .env (same as sending).

Twilio error codes worth knowing:
    30003 unreachable handset / off      30004 message blocked by recipient
    30005 unknown destination handset    30006 landline or unreachable carrier
    30007 carrier filtered (spam rules)  30008 unknown error
    21610 recipient replied STOP (opt-out) - texts are refused until START
"""

import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import config
import db

SID_RE = re.compile(r"SID:\s*(SM[0-9a-f]{32})")
NUM_RE = re.compile(r"To:\s*(\+\d+)\s*\(([^)]*)\)")


def _recent(days, number=None):
    conn = db._connect()
    try:
        cur = conn.cursor()
        sql = ("SELECT action_type, CAST(new_value AS VARCHAR(400)) AS new_value, "
               "CAST(reason AS VARCHAR(400)) AS reason, action_timestamp "
               "FROM dbo.ai_agent_log "
               "WHERE action_type LIKE %s AND action_timestamp >= %s "
               "AND CAST(reason AS VARCHAR(400)) LIKE %s")
        args = ["SMS_%", datetime.now() - timedelta(days=days), "SID: SM%"]
        if number:
            sql += " AND CAST(new_value AS VARCHAR(400)) LIKE %s"
            args.append(f"%{number}%")
        sql += " ORDER BY action_timestamp"
        cur.execute(sql, tuple(args))
        rows = []
        for r in cur.fetchall():
            m_sid = SID_RE.search(r["reason"] or "")
            m_num = NUM_RE.search(r["new_value"] or "")
            if not (m_sid and m_num):
                continue
            rows.append({"sid": m_sid.group(1), "to": m_num.group(1),
                         "name": m_num.group(2), "type": r["action_type"],
                         "at": r["action_timestamp"]})
        return rows
    finally:
        conn.close()


def main(argv):
    flags = {a for a in argv if a.startswith("--")}
    nums = [a for a in argv if a.startswith("+")]
    days = 7
    for a in argv:
        if a.startswith("--days="):
            days = int(a.split("=", 1)[1])
    if "--days" in flags:
        i = argv.index("--days")
        days = int(argv[i + 1])
    if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN):
        print("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set in .env")
        return 2
    from twilio.rest import Client
    client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)

    rows = _recent(days, nums[0] if nums else None)
    if not rows:
        print(f"no texts with a SID in the last {days} day(s)")
        return 0
    print(f"{len(rows)} text(s) in the last {days} day(s); asking Twilio...\n")

    per = defaultdict(Counter)
    detail = defaultdict(list)
    for r in rows:
        try:
            m = client.messages(r["sid"]).fetch()
            status, code, err = m.status, m.error_code, m.error_message
        except Exception as e:                       # SID gone (>13 months) etc.
            status, code, err = "lookup-failed", None, str(e)[:80]
        key = (r["to"], r["name"])
        per[key][status] += 1
        if status not in ("delivered", "sent", "read") or "--all" in flags:
            detail[key].append((r["at"], r["type"], status, code, err))

    for (to, name), c in sorted(per.items(), key=lambda kv: kv[0][1]):
        total = sum(c.values())
        bad = total - c.get("delivered", 0) - c.get("sent", 0) - c.get("read", 0)
        line = ", ".join(f"{k} {v}" for k, v in c.most_common())
        print(f"{name:<12} {to}  {total:>3} sent  ->  {line}")
        if "--failed" in flags and bad == 0:
            continue
        for at, typ, status, code, err in detail[(to, name)][-12:]:
            print(f"    {at:%m-%d %H:%M}  {typ:<28} {status:<12} "
                  f"{code or ''} {err or ''}")
    print("\nStatuses: delivered = handset confirmed; sent = carrier accepted, no "
          "receipt; undelivered / failed = look at the code (30006 landline, "
          "30007 carrier filtered, 21610 replied STOP).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
