#!/usr/bin/env python3
"""Channel 2 — direct database query, READ-ONLY. Bypasses the ABAP stack entirely.

    creds exec <hana-id> -- python3 sap_db.py ping
    creds exec <hana-id> -- python3 sap_db.py sql "SELECT TOP 10 MANDT, MTEXT FROM SAPABAP1.T000"
    creds exec <hana-id> -- python3 sap_db.py table T000 --schema SAPABAP1 --rows 10

Use only when channel 1 (RFC) genuinely cannot answer: joins, aggregations, very
large result sets, rows wider than RFC_READ_TABLE's ~512-byte limit, or when the
ABAP stack is down and the database is still up.

READ-ONLY IS ENFORCED, not merely advised: anything that is not a single SELECT
is refused. Writing behind the application server is unsupported by SAP, corrupts
state that ABAP believes it owns, and voids support.

Correctness traps — these are why this channel ranks BELOW RFC despite being
faster, and why casual use is wrong:
  * No client handling. Filter MANDT yourself or you silently read another client.
  * Pool and cluster tables are not plain tables. Classic ECC keeps BSEG inside
    cluster RFBLG; reading it directly yields compressed binary, not rows. S/4HANA
    converted many to transparent — verify per table rather than assuming.
  * SAP table buffering means the database can disagree with the application server.
  * In S/4HANA many "tables" are CDS or compatibility views.
  * Often prohibited by DBA or audit policy. Check before touching production.

Requires the SAP HANA client (`hdbcli`).
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# One statement, must start with SELECT. No semicolons chaining, no CTE-with-DML.
_SELECT_ONLY = re.compile(r"^\s*select\b", re.I)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|merge|upsert|grant|revoke|call)\b", re.I)


def guard_read_only(sql: str) -> None:
    if ";" in sql.rstrip().rstrip(";"):
        sys.exit("REFUSED: multiple statements. This channel runs one SELECT at a time.")
    if not _SELECT_ONLY.match(sql):
        sys.exit("REFUSED: only SELECT is permitted on this channel.")
    if _FORBIDDEN.search(sql):
        sys.exit("REFUSED: statement contains a data-modifying keyword.\n"
                 "Writing behind the application server is never correct — use channel 1 (RFC).")


def connect():
    try:
        from hdbcli import dbapi
    except ImportError:
        sys.exit("hdbcli (the SAP HANA client) is not installed for this interpreter.\n"
                 "Install the SAP HANA client, or use channel 1 (RFC) instead.")
    try:
        host, user, pwd = (os.environ["CREDS_HOST"], os.environ["CREDS_USER"],
                           os.environ["CREDS_PASSWORD"])
    except KeyError as e:
        sys.exit(f"missing {e} — run under: creds exec <hana-system-id> -- ...")
    port = int(os.environ.get("CREDS_PORT") or 30015)
    kw = {"address": host, "port": port, "user": user, "password": pwd}
    # A tenant DB is reached either by its own port or by databaseName on the
    # SYSTEMDB nameserver port; creds entries carry `tenant` for the latter.
    if tenant := os.environ.get("CREDS_TENANT"):
        kw["databaseName"] = tenant
    try:
        return dbapi.connect(**kw)
    except Exception as e:
        sys.exit(f"cannot connect to {host}:{port}: {str(e)[:200]}\n"
                 "Check VPN, the port (tenant vs SYSTEMDB nameserver), and any `requires` on the\n"
                 "creds entry. If the database is unreachable but the ABAP stack is up, use channel 1.")


def run(conn, sql: str, limit: int) -> None:
    guard_read_only(sql)
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(limit)
        if not rows:
            print("  (no rows)")
            return
        vals = [[("" if v is None else str(v)) for v in r] for r in rows]
        w = [max(len(c), *(len(r[i]) for r in vals)) for i, c in enumerate(cols)]
        print("  " + "  ".join(c.ljust(w[i]) for i, c in enumerate(cols)))
        print("  " + "  ".join("-" * w[i] for i in range(len(cols))))
        for r in vals:
            print("  " + "  ".join(r[i].ljust(w[i])[:60] for i in range(len(cols))))
        print(f"\n  {len(rows)} row(s)")
    finally:
        cur.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=50)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", help="connect and report database identity")
    q = sub.add_parser("sql", help="run one SELECT")
    q.add_argument("statement")
    t = sub.add_parser("table", help="read a table")
    t.add_argument("table")
    t.add_argument("--schema", default=os.environ.get("CREDS_SCHEMA", "SAPABAP1"))
    t.add_argument("--where", default="")
    a = ap.parse_args()

    conn = connect()
    try:
        if a.cmd == "ping":
            run(conn, "SELECT DATABASE_NAME, VERSION, HOST FROM M_DATABASE", 5)
        elif a.cmd == "sql":
            run(conn, a.statement, a.rows)
        else:
            where = f" WHERE {a.where}" if a.where else ""
            run(conn, f'SELECT TOP {a.rows} * FROM "{a.schema}"."{a.table}"{where}', a.rows)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
