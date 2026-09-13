#!/usr/bin/env python3
"""Headless SAP access over RFC — no GUI, no screen, no session needed.

Always try this BEFORE driving the GUI. It is faster, deterministic, and does not
touch the user's screen at all.

    creds exec <system-id> -- python3 sap_rfc.py info
    creds exec <system-id> -- python3 sap_rfc.py call RFC_SYSTEM_INFO
    creds exec <system-id> -- python3 sap_rfc.py table T000 MANDT,MTEXT --rows 5

Writes are opt-in and guarded:

    # validate only — stages nothing, always rolls back (safe to run anywhere)
    creds exec <id> -- python3 sap_rfc.py call BAPI_X --args '{...}'

    # actually commit
    creds exec <id> -- python3 sap_rfc.py call BAPI_X --args '{...}' --commit

A BAPI returning an E/A message is ROLLED BACK and never committed. Committing
against a production system (CREDS_ENV=prd) is refused unless --allow-prod is
passed, which you should only do after confirming with the user.

Credentials come only from the environment `creds exec` injects; nothing is
stored here and nothing secret is printed.

Requires pyrfc built against the SAP NW RFC SDK:
    SAPNWRFC_HOME=/path/to/nwrfcsdk pip install "pyrfc @ git+https://github.com/SAP/PyRFC.git"
(PyPI's pyrfc is yanked, so it must come from source.)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# macOS strips DYLD_* across process spawns (including `creds exec`), and pyrfc's
# extension resolves the SDK libs at @loader_path. Colocating them next to the
# extension makes it load with no environment reliance. Idempotent, best effort.
_LIBS = ("libsapnwrfc.dylib", "libsapucum.dylib",
         "libicudata57.dylib", "libicui18n57.dylib", "libicuuc57.dylib")


def _ensure_sdk() -> None:
    import importlib.util
    spec = importlib.util.find_spec("pyrfc")
    if not spec or not spec.origin:
        return
    pkg = Path(spec.origin).parent
    if all((pkg / lib).exists() for lib in _LIBS):
        return
    candidates = []
    if home := os.environ.get("SAPNWRFC_HOME"):
        candidates.append(Path(home) / "lib")
    candidates += [Path.home() / ".cidb-sap-monitor" / "nwrfcsdk" / "lib",
                   Path("/usr/local/sap/nwrfcsdk/lib"), Path("/usr/local/lib")]
    src = next((d for d in candidates if (d / "libsapnwrfc.dylib").is_file()), None)
    if src is None:
        return
    for lib in _LIBS:
        target, source = pkg / lib, src / lib
        if not target.exists() and source.is_file():
            try:
                shutil.copy2(source, target)
            except OSError:
                pass


def connect():
    _ensure_sdk()
    try:
        from pyrfc import Connection
    except ImportError:
        sys.exit(
            "pyrfc is not installed for this interpreter.\n"
            "It is not on PyPI (yanked) and needs the SAP NW RFC SDK at build time:\n"
            "  SAPNWRFC_HOME=/path/to/nwrfcsdk \\\n"
            '    pip install "pyrfc @ git+https://github.com/SAP/PyRFC.git"')
    try:
        params = {
            "user": os.environ["CREDS_USER"],
            "passwd": os.environ["CREDS_PASSWORD"],
            "client": os.environ["CREDS_CLIENT"],
            "ashost": os.environ["CREDS_HOST"],
            "sysnr": os.environ["CREDS_SYSNR"],
            "lang": os.environ.get("CREDS_LANG", "EN"),
        }
    except KeyError as e:
        sys.exit(f"missing {e} — run this under: creds exec <system-id> -- ...")
    if router := os.environ.get("CREDS_ROUTER"):
        params["saprouter"] = router
    return Connection(**params)


def is_prod() -> bool:
    """`creds exec` injects CREDS_ENV; it is the authoritative source for this."""
    return os.environ.get("CREDS_ENV", "").strip().lower() == "prd"


def guard_prod(allow_prod: bool) -> None:
    """Refuse to commit against production unless explicitly authorized."""
    if is_prod() and not allow_prod:
        sys.exit(
            f"REFUSED: {os.environ.get('CREDS_SID', '?')} is a production system "
            f"(CREDS_ENV=prd) and this would commit a change.\n"
            "Confirm with the user first, then re-run with --allow-prod.")


def bapi_error(out: dict) -> str | None:
    """First E/A message in a BAPIRET2 RETURN structure, if any."""
    ret = out.get("RETURN")
    items = ret if isinstance(ret, list) else ([ret] if ret else [])
    for r in items:
        if isinstance(r, dict) and r.get("TYPE") in ("E", "A"):
            return f"{r.get('TYPE')} {r.get('ID', '')}{r.get('NUMBER', '')}: {r.get('MESSAGE', '')}".strip()
    return None


def rollback(conn) -> None:
    try:
        conn.call("BAPI_TRANSACTION_ROLLBACK")
    except Exception:
        pass  # best effort — nothing was committed either way


def parse_table(out: dict) -> list[dict]:
    fields = [f["FIELDNAME"] for f in out.get("FIELDS", [])]
    rows = []
    for entry in out.get("DATA", []):
        cells = (c.strip() for c in entry["WA"].split("|"))
        rows.append(dict(zip(fields, cells)))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="connectivity check + system info")
    c = sub.add_parser("call", help="call a function module")
    c.add_argument("fm")
    c.add_argument("--args", default="{}", help="JSON object of import parameters")
    c.add_argument("--commit", action="store_true",
                   help="commit the change; without this the call is validate-only and rolled back")
    c.add_argument("--allow-prod", action="store_true",
                   help="permit a commit against a production system (ask the user first)")
    t = sub.add_parser("table", help="read a table")
    t.add_argument("table")
    t.add_argument("fields", help="comma-separated field names")
    t.add_argument("--rows", type=int, default=20)
    t.add_argument("--where", default="", help="WHERE clause, e.g. \"MANDT = '100'\"")
    a = ap.parse_args()

    conn = connect()
    try:
        if a.cmd == "info":
            i = conn.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]
            print(json.dumps({k: i.get(k, "").strip() for k in
                              ("RFCSYSID", "RFCSAPRL", "RFCDBSYS", "RFCOPSYS", "RFCHOST")}, indent=2))
        elif a.cmd == "call":
            if a.commit:
                guard_prod(a.allow_prod)
            out = conn.call(a.fm, **json.loads(a.args))
            # A BAPI reports failure in RETURN, not by raising. Committing past an
            # E/A message is how half-written data gets created.
            if err := bapi_error(out):
                rollback(conn)
                print(json.dumps(out, indent=2, default=str))
                sys.exit(f"\n{a.fm} FAILED: {err}\nRolled back — nothing was committed.")
            if a.commit:
                conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
                print(json.dumps(out, indent=2, default=str))
                print("\nCOMMITTED.", file=sys.stderr)
            else:
                rollback(conn)
                print(json.dumps(out, indent=2, default=str))
                print("\nvalidate-only: rolled back, nothing committed. "
                      "Re-run with --commit to apply.", file=sys.stderr)
        else:
            out = conn.call("RFC_READ_TABLE", QUERY_TABLE=a.table, DELIMITER="|",
                            FIELDS=[{"FIELDNAME": f} for f in a.fields.split(",")],
                            OPTIONS=[{"TEXT": a.where}] if a.where else [],
                            ROWCOUNT=a.rows)
            print(json.dumps(parse_table(out), indent=2))
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
