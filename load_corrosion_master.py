#!/usr/bin/env python3
"""
load_corrosion_master.py — bulk-load corrosion_master.csv into
dbo.corrosion_compatibility (migration 106 must be applied first).

TRUNCATE-AND-RELOAD: safe to re-run after a better extraction; the
table is replaced in one transaction (nothing else writes to it).

Needs a login that can DELETE/INSERT on the table (the service login
is read-only by design) — use the one you apply migrations with.

  venv\\Scripts\\python load_corrosion_master.py ^
      --csv C:\\corrosion-out\\corrosion_master.csv ^
      --server <NEXUS_SERVER> --database <NEXUS_DATABASE> ^
      --user <admin user>            (password prompted, not echoed)

  pip install pymssql  (already in the titan-ai-service venv)
"""
import argparse
import csv
import getpass
import sys

import pymssql

COLS = ["chemical", "category", "material", "rating", "rating_meaning",
        "temp_from_f", "temp_to_f", "temp_from_c", "temp_to_c",
        "footnotes", "confidence", "notes", "source", "source_file",
        "pdf_page"]
INT_COLS = {"temp_from_f", "temp_to_f", "temp_from_c", "temp_to_c",
            "pdf_page"}
RATINGS = {"E", "G", "S", "U", "R", "ND"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--server", required=True)
    ap.add_argument("--database", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", help="omit to be prompted")
    args = ap.parse_args()
    pw = args.password or getpass.getpass(f"password for {args.user}: ")

    rows = []
    bad = 0
    with open(args.csv, newline="", encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            if r["rating"] not in RATINGS:
                print(f"  line {i}: unknown rating {r['rating']!r} — skipped")
                bad += 1
                continue
            vals = []
            for c in COLS:
                v = (r.get(c) or "").strip()
                if c in INT_COLS:
                    vals.append(int(float(v)) if v else None)
                else:
                    vals.append(v or None)
            rows.append(tuple(vals))
    n0 = len(rows)
    rows = list(dict.fromkeys(rows))   # drop exact duplicates
    print(f"CSV: {len(rows)} rows parsed ({n0 - len(rows)} exact "
          f"duplicates dropped), {bad} skipped")
    if not rows:
        sys.exit("nothing to load")

    conn = pymssql.connect(server=args.server, user=args.user,
                           password=pw, database=args.database,
                           port="1433", autocommit=False)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM dbo.schema_migrations "
                "WHERE migration_id = 106")
    if cur.fetchone()[0] == 0:
        sys.exit("migration 106 not applied — run "
                 "106_corrosion_compatibility.sql first")

    cur.execute("SELECT COUNT(*) FROM dbo.corrosion_compatibility")
    before = cur.fetchone()[0]
    print(f"table currently holds {before} rows — replacing")
    cur.execute("DELETE FROM dbo.corrosion_compatibility")
    sql = (f"INSERT INTO dbo.corrosion_compatibility "
           f"({', '.join(COLS)}) VALUES ({', '.join(['%s'] * len(COLS))})")
    for i in range(0, len(rows), 500):
        cur.executemany(sql, rows[i:i + 500])
    cur.execute("SELECT COUNT(*) FROM dbo.corrosion_compatibility")
    after = cur.fetchone()[0]
    if after != len(rows):
        conn.rollback()
        sys.exit(f"VERIFY FAILED: inserted {after} != parsed {len(rows)} "
                 "— rolled back, nothing changed")
    conn.commit()

    cur.execute("SELECT rating, COUNT(*) FROM dbo.corrosion_compatibility "
                "GROUP BY rating ORDER BY rating")
    summary = ", ".join(f"{r}:{n}" for r, n in cur.fetchall())
    cur.execute("SELECT COUNT(DISTINCT chemical) "
                "FROM dbo.corrosion_compatibility")
    n_chem = cur.fetchone()[0]
    print(f"LOADED {after} rows, {n_chem} chemicals  [{summary}]")
    conn.close()


if __name__ == "__main__":
    main()
