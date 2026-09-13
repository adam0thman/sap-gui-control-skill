#!/usr/bin/env python3
"""Channel 3 — ABAP Development Tools (ADT) over HTTP. Headless, no GUI.

ADT is the REST API behind Eclipse ABAP tooling: source code, transports, object
search, ABAP Unit. Use it for developer and transport questions that RFC answers
badly or not at all.

    creds exec <id> -- python3 sap_adt.py discovery
    creds exec <id> -- python3 sap_adt.py transports
    creds exec <id> -- python3 sap_adt.py transports --user BPINST
    creds exec <id> -- python3 sap_adt.py search "ZCL_*"
    creds exec <id> -- python3 sap_adt.py source programs/programs/RSPARAM

Read-only by design. ADT writes need a CSRF token and are deliberately not
implemented here — activating or releasing objects is not something to do by
accident.

Two things commonly make this fail, and they are worth checking before debugging
anything else:
  * ADT services must be activated in SICF (/sap/bc/adt/*). Many systems have
    them switched off; `discovery` tells you.
  * ADT is HTTP, so it does NOT travel through a SAProuter the way RFC does. A
    system reachable by RFC may be unreachable here unless the ICM host/port is
    directly routable or a proxy exists.
"""
from __future__ import annotations

import argparse
import base64
import os
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


def base_url(port: str | None, use_https: bool) -> str:
    host = os.environ.get("CREDS_HOST")
    if not host:
        sys.exit("missing CREDS_HOST — run under: creds exec <system-id> -- ...")
    if port is None:
        # ICM defaults follow the instance number: 80<nn> / 443<nn>.
        nn = (os.environ.get("CREDS_SYSNR") or "00").zfill(2)
        port = f"443{nn}" if use_https else f"80{nn}"
    scheme = "https" if use_https else "http"
    return f"{scheme}://{host}:{port}/sap/bc/adt"


def get(path: str, port: str | None, use_https: bool, accept: str = "application/xml") -> str:
    try:
        user, pwd = os.environ["CREDS_USER"], os.environ["CREDS_PASSWORD"]
    except KeyError as e:
        sys.exit(f"missing {e} — run under: creds exec <system-id> -- ...")
    url = f"{base_url(port, use_https)}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode(),
        "Accept": accept,
        "sap-client": os.environ.get("CREDS_CLIENT", ""),
    })
    ctx = ssl._create_unverified_context() if use_https else None
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        if e.code == 401:
            sys.exit(f"401 unauthorized at {url}\nCheck the user has ADT authorization (S_ADT_RES).")
        if e.code == 403:
            sys.exit(f"403 forbidden at {url}\nADT service is likely not activated in SICF.")
        if e.code == 404:
            sys.exit(f"404 not found at {url}\nADT may not be activated, or the path is wrong.\n{body}")
        sys.exit(f"HTTP {e.code} at {url}\n{body}")
    except urllib.error.URLError as e:
        sys.exit(f"cannot reach {url}: {e.reason}\n"
                 "ADT is plain HTTP — it does not traverse a SAProuter. If this system is only\n"
                 "reachable via SAProuter, use channel 1 (RFC) instead.")


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="ICM port (default 80<sysnr>, or 443<sysnr> with --https)")
    ap.add_argument("--https", action="store_true", help="use HTTPS (certificate not verified)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discovery", help="is ADT reachable and activated?")
    sub.add_parser("ping", help="separate reachability / auth / ADT-activation problems")
    t = sub.add_parser("transports", help="list transport requests")
    t.add_argument("--user", default=os.environ.get("CREDS_USER", ""))
    se = sub.add_parser("search", help="repository object search")
    se.add_argument("query")
    se.add_argument("--max", type=int, default=25)
    so = sub.add_parser("source", help="fetch source, e.g. programs/programs/RSPARAM")
    so.add_argument("objpath")
    a = ap.parse_args()

    if a.cmd == "ping":
        # Three probes that isolate which layer is failing. Without this a bare 403
        # looks like "ADT is off" when the real cause is that the system does not
        # accept basic auth at all.
        import base64, ssl, urllib.request, urllib.error
        host = os.environ.get("CREDS_HOST", "")
        user, pwd = os.environ.get("CREDS_USER", ""), os.environ.get("CREDS_PASSWORD", "")
        root = base_url(a.port, a.https).rsplit("/sap/bc/adt", 1)[0]

        def probe(path: str, auth: bool) -> str:
            h = {"Accept": "*/*"}
            if auth and pwd:
                h["Authorization"] = "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()
            req = urllib.request.Request(root + path, headers=h)
            ctx = ssl._create_unverified_context() if a.https else None
            try:
                with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                    return f"{r.status} OK"
            except urllib.error.HTTPError as e:
                return f"HTTP {e.code}"
            except Exception as e:
                return f"unreachable ({type(e).__name__})"

        pub = probe("/sap/public/ping", False)
        auth = probe("/sap/bc/ping", True)
        adt = probe("/sap/bc/adt/discovery", True)
        print(f"  ICM reachable (/sap/public/ping, no auth) : {pub}")
        print(f"  authenticated ICF (/sap/bc/ping)          : {auth}")
        print(f"  ADT (/sap/bc/adt/discovery)               : {adt}")
        print()
        if pub.startswith("unreachable"):
            print("  -> host/port not reachable. Check VPN, or use channel 1 (RFC) via SAProuter.")
        elif auth.startswith("HTTP 40"):
            print("  -> ICM is up but basic auth is rejected for authenticated services,")
            print("     not just ADT. Typical when the system accepts only SNC/SSO or the")
            print("     user lacks ICF authorization. Channel 3 is unusable here; use channel 1.")
        elif adt.startswith("HTTP 40"):
            print("  -> auth works but ADT specifically is refused: activate /sap/bc/adt/* in")
            print("     SICF, and check the user has S_ADT_RES.")
        else:
            print("  -> channel 3 is usable.")
        return

    if a.cmd == "discovery":
        xml = get("/discovery", a.port, a.https)
        root = ET.fromstring(xml)
        cols = [w.get("href") for w in root.iter() if strip_ns(w.tag) == "collection"]
        print(f"ADT reachable — {len(cols)} collections advertised. Examples:")
        for c in [c for c in cols if c][:15]:
            print("  ", c)
    elif a.cmd == "transports":
        xml = get(f"/cts/transportrequests?user={a.user}&targets=true", a.port, a.https)
        root = ET.fromstring(xml)
        rows = [e for e in root.iter() if strip_ns(e.tag) in ("request", "task")]
        if not rows:
            print("(no transport requests returned)")
        for e in rows:
            print(f"  {e.get('number','?'):12} {e.get('owner','?'):10} "
                  f"{e.get('status','?'):3} {e.get('desc') or e.get('description') or ''}")
    elif a.cmd == "search":
        xml = get(f"/repository/informationsystem/search?operation=quickSearch"
                  f"&query={a.query}&maxResults={a.max}", a.port, a.https)
        root = ET.fromstring(xml)
        for e in root.iter():
            if strip_ns(e.tag) == "objectReference":
                print(f"  {e.get('type','?'):18} {e.get('name','?')}")
    else:
        print(get(f"/{a.objpath.strip('/')}/source/main", a.port, a.https, accept="text/plain"))


if __name__ == "__main__":
    main()
