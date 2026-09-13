#!/usr/bin/env python3
"""Channel 0 — SAPControl over SOAP. No SAP login, no GUI, no ssh.

`sapstartsrv` runs beside every instance and exposes SAPControl on 5<nn>13 (HTTP)
and 5<nn>14 (HTTPS). Because it is a separate OS process from the ABAP stack, this
still answers when the stack is jammed, work processes are all busy, or SAP GUI
cannot log on at all — which is exactly when you need it most.

    creds exec <id> -- python3 sap_control.py instances
    creds exec <id> -- python3 sap_control.py processes
    creds exec <id> -- python3 sap_control.py wp          # SM50 equivalent
    creds exec <id> -- python3 sap_control.py syslog --lines 40   # SM21 equivalent
    creds exec <id> -- python3 sap_control.py queue       # dispatcher queues

    # no creds needed for the unprotected calls:
    python3 sap_control.py --host 10.1.2.3 --instance 00 instances

READ-ONLY BY CONSTRUCTION. SAPControl can also start, stop and restart instances;
none of those are implemented here and none should be added casually. Some read
functions (wp, syslog) are protected and need credentials; `instances` and
`processes` are usually open.
"""
from __future__ import annotations

import argparse
import base64
import re
import os
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

NS = {"s": "http://schemas.xmlsoap.org/soap/envelope/"}


def endpoint(host: str | None, instance: str | None, https: bool) -> str:
    host = host or os.environ.get("CREDS_HOST")
    if not host:
        sys.exit("no host — pass --host or run under: creds exec <system-id> -- ...")
    nn = (instance or os.environ.get("CREDS_SYSNR") or "00").zfill(2)
    port = f"5{nn}14" if https else f"5{nn}13"
    return f"{'https' if https else 'http'}://{host}:{port}/"


def soap(url: str, func: str, body: str = "", auth: bool = False) -> ET.Element:
    env = ('<?xml version="1.0"?>'
           '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
           f'<SOAP-ENV:Body><ns1:{func} xmlns:ns1="urn:SAPControl">{body}</ns1:{func}>'
           '</SOAP-ENV:Body></SOAP-ENV:Envelope>')
    headers = {"Content-Type": 'text/xml; charset=utf-8', "SOAPAction": '""'}
    if auth:
        u, p = os.environ.get("CREDS_USER", ""), os.environ.get("CREDS_PASSWORD", "")
        if u and p:
            headers["Authorization"] = "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()
    req = urllib.request.Request(url, data=env.encode(), headers=headers)
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return ET.fromstring(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        m = re.search(r"<faultstring>(.*?)</faultstring>", detail, re.S)
        fault = m.group(1).strip() if m else f"HTTP {e.code}"
        # sapstartsrv authenticates against OS users, NOT SAP users — a perfectly
        # good SAP logon returns "Invalid Credentials" here, which is confusing
        # unless you know that.
        if e.code == 401 or "credential" in fault.lower() or "authoriz" in fault.lower():
            sys.exit(
                f"{func}: {fault}\n\n"
                "This call is protected. sapstartsrv authenticates against the OPERATING SYSTEM\n"
                "user (<sid>adm), not against a SAP logon — SAP credentials will be rejected here\n"
                "even when they are valid for RFC. Run under `creds exec <a sidadm ssh entry> --`,\n"
                "or use the unprotected calls (instances, processes), or channel 1 for ABAP data.")
        sys.exit(f"{func}: {fault}")
    except urllib.error.URLError as e:
        sys.exit(f"cannot reach {url}: {e.reason}\n"
                 "sapstartsrv listens on 5<nn>13; check the instance number, host and VPN.")


def rows(root: ET.Element) -> list[dict[str, str]]:
    """SAPControl replies are <item> lists; flatten each into a dict."""
    return [{c.tag.rsplit("}", 1)[-1]: (c.text or "") for c in item}
            for item in root.iter("item")]


def show(data: list[dict[str, str]], cols: list[str], limit: int | None = None) -> None:
    if not data:
        print("  (no rows)")
        return
    cols = [c for c in cols if any(c in r for r in data)] or list(data[0])
    widths = {c: max(len(c), *(len(r.get(c, "")) for r in data)) for c in cols}
    print("  " + "  ".join(c.ljust(widths[c]) for c in cols))
    print("  " + "  ".join("-" * widths[c] for c in cols))
    for r in (data[:limit] if limit else data):
        print("  " + "  ".join(r.get(c, "").ljust(widths[c])[:60] for c in cols))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host")
    ap.add_argument("--instance", help="instance number, default CREDS_SYSNR or 00")
    ap.add_argument("--https", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("instances", help="all instances of the system (usually unprotected)")
    sub.add_parser("processes", help="are the instance's processes running (usually unprotected)")
    sub.add_parser("wp", help="ABAP work process table — SM50 (protected)")
    sub.add_parser("queue", help="dispatcher queue statistics (protected)")
    sl = sub.add_parser("syslog", help="ABAP syslog — SM21 (protected)")
    sl.add_argument("--lines", type=int, default=25)
    a = ap.parse_args()

    url = endpoint(a.host, a.instance, a.https)
    if a.cmd == "instances":
        show(rows(soap(url, "GetSystemInstanceList")),
             ["hostname", "instanceNr", "features", "dispstatus"])
    elif a.cmd == "processes":
        data = rows(soap(url, "GetProcessList"))
        show(data, ["name", "description", "dispstatus", "textstatus", "starttime"])
        bad = [r for r in data if "GREEN" not in r.get("dispstatus", "")]
        print(f"\n  {len(data) - len(bad)}/{len(data)} processes GREEN"
              + (f" — not green: {', '.join(r.get('name','?') for r in bad)}" if bad else ""))
    elif a.cmd == "wp":
        data = rows(soap(url, "ABAPGetWPTable", auth=True))
        show(data, ["Typ", "Pid", "Status", "Reason", "Start", "Err", "Sem",
                    "Cpu", "Time", "Program", "Client", "User", "Action", "Table"])
        busy = [r for r in data if r.get("Status", "").lower() not in ("wait", "waiting")]
        print(f"\n  {len(busy)}/{len(data)} work processes busy")
    elif a.cmd == "queue":
        show(rows(soap(url, "GetQueueStatistic", auth=True)),
             ["Typ", "Now", "High", "Max", "Writes", "Reads"])
    else:
        data = rows(soap(url, "ABAPReadSyslog", auth=True))
        show(data[-a.lines:], ["Time", "Typ", "Nr", "Clt", "User", "Tcode", "Text"])


if __name__ == "__main__":
    main()
