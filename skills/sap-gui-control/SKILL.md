---
name: "sap-gui-control"
description: "Connect to and interact with SAP systems efficiently — choosing the right channel for each step: RFC/BAPI, ADT, OData, sapcontrol/OS, background GUI control via the Accessibility API, SAP GUI scripting, WebGUI, or vision as a last resort. Use for ANY SAP task: reading tables or user/job/transport data, running a transaction or OK-code (SE16, SE37, SNOTE, SPAM, STMS, SM50), checking system or job status, importing transports or Support Packages, driving SAP GUI for Java on macOS, or when SAP GUI input appears blocked, typing does nothing, or an action silently fails."
user-invocable: true
disable-model-invocation: false
---

# Interacting with SAP efficiently

SAP can be reached through many channels. Most SAP work does **not** need a GUI, and reaching for
the GUI first is the single most common and most expensive mistake. Route **each step** of a task
to the cheapest channel that can do that step.

```bash
SK=~/.claude/skills/sap-gui-control/scripts
```

## Choosing a channel

| # | Channel | Cost | Takes over screen | Status here |
|---|---------|------|-------------------|-------------|
| 0 | **OS / SAPControl** | ~free | no | **`sap_control.py`** |
| 1 | **RFC / BAPI** | ~free | no | **`sap_rfc.py`** |
| 2 | **Direct DB, read-only** | ~free | no | **`sap_db.py`** |
| 3 | **ADT / sapcli** (HTTP) | ~free | no | **`sap_adt.py`** |
| 4 | OData / RAP | ~free | no | guidance |
| 5 | **AX background GUI control** | low | **no** | **`ax_okcode.swift`** |
| 6 | **SAP GUI scripting** (`GuiStartS.jar`) | low | no | **`sap_script.sh`** |
| 7 | WebGUI / HTML (browser) | low–med | browser only | guidance |
| 8 | Vision + mouse (computer-use) | **high** | **yes** | last resort |

0–4 are headless, 5–7 need a session, 8 needs the screen. The order is
**preference, not raw speed** — channel 2 is often the fastest thing on the list and
still ranks below RFC, because cheap is not the same as correct or safe.

Pick by what the step actually is:

| The step is… | Use | Note |
|---|---|---|
| Is the system up? work processes, syslog, dispatcher queues | **0** | Needs no SAP login — works when SAP GUI cannot even log on |
| Read table contents, check a data state | **1** | `sap_rfc.py table` |
| A read RFC can't do — joins, aggregations, very large result sets | **2** | read-only; see the traps below |
| ABAP stack is down but you still need data | **2** or **0** | the DB is usually still up |
| User, roles, authorizations | **1** | `BAPI_USER_GET_DETAIL` |
| Which transport is imported where | **1** or **0** | `E070`/`E071`, or `tp`/STMS at OS level |
| Job status / scheduling | **1** | `TBTCO`, or the XBP BAPIs |
| Put a file on the SAP server (SAR/PAT, data file) | **0** | `scp` — **not** a GUI upload |
| ABAP source, dev objects, transports, ABAP Unit | **3** | sapcli / ADT |
| Published S/4 business API | **4** | where an OData service exists |
| A transaction with no headless equivalent | **5** | background, no screen takeover |
| The same GUI routine, repeatedly | **6** | record once, replay deterministically |
| Screen only exists in HTML GUI, or AX cannot address it | **7** | |
| Nothing above works | **8** | say so explicitly before using it |

### Route each step, not the whole task

Do not pick one channel because the *hardest* step needs it. Decompose. A Support Package import:

| Step | Channel |
|---|---|
| Check current component / SP levels | **1** (`CVERS`, `PAT03`) |
| Check disk space in `/usr/sap/trans` | **0** (ssh) |
| Get the `.SAR`/`.PAT` onto the server | **0** (`scp` into `EPS/in`) |
| Define and import the queue in SPAM | **5** |
| Watch import progress | **1** / **0** — *not* the SPAM screen |
| Verify final SP levels | **1** |

Note the file step: SPAM's *"Load Packages from **Front End**"* goes through SAP's frontend-services
path, which is exactly what SAP GUI for Java implements poorly (see *Silent frontend gaps* below).
Copy the file to the server and use *"Load Packages from **Application Server**"* instead.

**Two rules that matter more than the table:**

1. **Verify through a different channel than you acted on.** Drove something in the GUI? Confirm it
   over RFC. Re-reading the same screen mostly proves the screen still renders.
2. **The channel that can *act* is rarely the best one to *watch*.** Long-running work — client
   copies, SP imports, transports — should be monitored on 0/1 even when launched on 5.

**Anti-patterns:** using the GUI to read something a table read answers; watching progress on the
screen you launched from; picking one channel for an entire task.

---

## Channel 0 — SAPControl (no SAP login at all)

`sapstartsrv` runs beside every instance and exposes SAPControl over SOAP on **5<nn>13** (HTTP) /
**5<nn>14** (HTTPS). It is a separate OS process from the ABAP stack, so it still answers when the
stack is jammed, every work process is busy, or SAP GUI cannot log on — which is when you need it
most. **Start here when the question is "is the system even up?"**

```bash
python3 $SK/sap_control.py --host <host> --instance 00 instances   # no credentials needed
python3 $SK/sap_control.py --host <host> --instance 00 processes   # no credentials needed
creds exec <id> -- python3 $SK/sap_control.py wp                   # SM50  (protected)
creds exec <id> -- python3 $SK/sap_control.py syslog --lines 40     # SM21  (protected)
creds exec <id> -- python3 $SK/sap_control.py queue                 # dispatcher queues
```

**Read-only by construction.** SAPControl can also start, stop and restart instances; none of that
is implemented here and none of it should be added casually.

**The credential trap, measured here:** protected calls authenticate against the **operating system
user (`<sid>adm`), not a SAP logon**. A perfectly valid SAP user returns `Invalid Credentials`,
which reads like a wrong password but is not — it is the wrong *kind* of account. `instances` and
`processes` are normally unprotected and need nothing at all.

## Channel 1 — RFC / BAPI (preferred)

Headless, deterministic, no session or screen needed.

```bash
creds exec <system-id> -- python3 $SK/sap_rfc.py info
creds exec <system-id> -- python3 $SK/sap_rfc.py table T000 MANDT,MTEXT --rows 5
creds exec <system-id> -- python3 $SK/sap_rfc.py table MARA MATNR,MTART --where "MTART = 'FERT'"
creds exec <system-id> -- python3 $SK/sap_rfc.py call BAPI_USER_GET_DETAIL --args '{"USERNAME":"X"}'
```

**Writes are opt-in and guarded.** Without `--commit` a call is validate-only and always rolled
back. A BAPI returning an `E`/`A` message is rolled back and never committed — BAPIs report
failure in `RETURN` rather than raising, and committing past that is how half-written data appears.
Committing against `CREDS_ENV=prd` is refused unless `--allow-prod` is passed, which requires
confirming with the user first.

## Channel 2 — direct database, read-only

```bash
creds exec <hana-id> -- python3 $SK/sap_db.py ping
creds exec <hana-id> -- python3 $SK/sap_db.py table T000 --schema SAPABAP1 --rows 10
creds exec <hana-id> -- python3 $SK/sap_db.py sql "SELECT TOP 5 MANDT, MTEXT FROM SAPABAP1.T000"
```

`creds find hana` lists the entries, which carry tenant, ports and a `connect` hint, and often a
`requires: vpn:...` prerequisite. Needs the SAP HANA client (`hdbcli`).

**Read-only is enforced in code, not merely advised** — anything that is not a single `SELECT` is
refused, including statement chaining. The guard is deliberately conservative: a `SELECT` that
merely mentions a DML keyword is rejected rather than parsed, because a false refusal costs
nothing and a false permit corrupts a system.

**Use it when RFC genuinely cannot cope:** joins and aggregations (`RFC_READ_TABLE` does neither),
very large result sets, or rows wider than `RFC_READ_TABLE`'s ~512-byte limit. It is also the
fallback when the **ABAP stack is down but the database is up**.

**Read-only. Never write.** Writing behind the application server is unsupported by SAP, corrupts
state that ABAP believes it owns, and voids support. There is no case where it is the right call.

Correctness traps that disqualify it for casual use — this is why it ranks below RFC despite being
faster:

- **No client handling.** You must filter `MANDT` yourself; forget it and you silently read another
  client's data.
- **Pool and cluster tables are not plain tables.** Classic ECC keeps `BSEG` inside cluster `RFBLG`;
  reading it directly yields compressed binary, not rows. S/4HANA converted many to transparent —
  verify per table rather than assuming.
- **Table buffering** means the database can disagree with what the application server is serving.
- **In S/4HANA many "tables" are CDS or compatibility views**, so the physical shape may not match
  what SE16 shows you.
- Often prohibited by DBA or audit policy. Check before touching production.

Prefer channel 1 for anything it can answer. Reach here for the reads it cannot.

## Channel 3 — ADT over HTTP

ABAP Development Tools REST API: source, transports, object search, ABAP Unit. Read-only here;
ADT writes need a CSRF token and are deliberately not implemented.

```bash
creds exec <id> -- python3 $SK/sap_adt.py ping          # start here — isolates the failure layer
creds exec <id> -- python3 $SK/sap_adt.py discovery
creds exec <id> -- python3 $SK/sap_adt.py transports --user <USER>
creds exec <id> -- python3 $SK/sap_adt.py search "ZCL_*"
creds exec <id> -- python3 $SK/sap_adt.py source programs/programs/RSPARAM
```

**Run `ping` first when anything fails.** A bare 403 looks like "ADT is switched off" when the real
cause is usually different, and `ping` separates the three layers:

| Symptom | Meaning |
|---|---|
| `/sap/public/ping` unreachable | host/port not routable — ADT is plain HTTP and does **not** traverse a SAProuter. Use channel 1. |
| `/sap/public/ping` 200 but `/sap/bc/ping` 403 | basic auth rejected for **all** authenticated services, not just ADT — typical where only SNC/SSO is accepted. Channel 3 is unusable; use channel 1. |
| `/sap/bc/ping` OK but ADT 403/404 | ADT specifically: activate `/sap/bc/adt/*` in SICF and check `S_ADT_RES`. |

Measured on a sandbox here: ICM answered 200 unauthenticated and 403 authenticated, i.e. the second
row — so on SNC/SSO systems expect to fall back to channel 1.

## Channel 5 — background GUI control (AX)

For transactions with no headless equivalent. No screenshots, no coordinates, no focus stealing.

```bash
swift $SK/ax_okcode.swift probe "ECD (2)"                 # read screen, list buttons, detect blockers
swift $SK/ax_okcode.swift run   "ECD (2)" "/nSE16"        # write OK-code + submit
swift $SK/ax_okcode.swift type  "ECD (2)" "/nSE16"        # write without executing
swift $SK/ax_okcode.swift press "ECD (2)" "Back (F3)"     # press a button by name
swift $SK/ax_okcode.swift press "Information" "Continue"  # clear a blocking popup
```

Always address a session by **window name**, never coordinates; the script warns rather than
guessing when a name matches several windows. Set `SAP_PROD_SIDS=S4P,ECP` to have state-changing
actions refuse those SIDs without `--allow-prod` — **with it unset there is no protection on this
path**, because a window title carries a SID but not an environment.

## Channel 6 — SAP GUI scripting (JavaScript)

SAP GUI for Java embeds a JavaScript engine with the GUI Scripting object model. Once a routine is
written down it replays deterministically, which beats channel 5 for anything done repeatedly.

```bash
bash $SK/sap_script.sh probe              # version + connections/sessions
bash $SK/sap_script.sh run  myflow.js     # run a script file (synchronous)
bash $SK/sap_script.sh eval '<javascript>'
```

**It starts its OWN SAP GUI instance — it does not attach to the SAP GUI you already have open.**
Measured: a script opening a connection produced no window in the running app, and the running
app's sessions are not visible to it. So channel 6 is for **self-contained** automation (open its
own connection, do the work, exit); to drive an **already-open** session use channel 5.

The object model is Java-flavoured, **not** the Windows VBScript spelling — verified by reflection
against `GuiApplicationWrapper`:

```js
application.getMajorVersion()
var conns = application.getConnections();   conns.getLength();   conns.elementAt(i)
var ses   = conn.getSessions();             ses.getLength();     ses.elementAt(j)
application.findById("...")
application.openConnectionByConnectionString("/H/host/S/32<nn>")
java.lang.System.out.println(x)             // this is how you print
```

`application.Children.Count` is undefined here. Two operational notes: the JVM does **not** exit
after the script finishes (runs are bounded by `SAP_SCRIPT_TIMEOUT`, default 60s — exit 124 is
normal, not a failure), and SAP GUI Scripting must be enabled on both sides
(`sapgui/user_scripting = TRUE` server-side plus the client setting) or the session objects stay
invisible.

## Channels 4, 7 — no script here yet

Use them directly; they are still usually the right answer.

- **4 — OData / RAP**: published S/4 APIs. Note S/4HANA **Cloud** blocks RFC entirely, so there
  channel 4 replaces channel 1.
- **7 — WebGUI**: the same dynpros rendered as HTML, drivable through a browser.

## When input fails, never guess

If an action on SAP GUI does nothing, **do not speculate.** There is almost never a "macOS
Open/Save dialog attached to the window" — three separate sessions reported exactly that and it was
false every time. Run:

```bash
bash $SK/gui_preflight.sh     # exit 0 clear · 1 warnings · 2 blocked
```

It distinguishes the real causes:

1. **Frontmost-app policy** — a browser in front blocks clicks *and* typing; a terminal/IDE blocks
   typing but *allows* clicks. **That asymmetry is diagnostic**: a modal dialog would block both, so
   "clicks work, typing doesn't" rules a dialog out entirely.
2. **A SAP dynpro popup owning input** — rendered as separate windows with `AXModal=false` and no
   attached sheet, so sheet/modal checks report all clear while the session is fully blocked.
   `AXFocusedWindow` is the only reliable signal.
3. **Geometry-ambiguous sessions** — several sessions full-screen at identical coordinates; a
   coordinate click lands on the topmost, not the one you meant.
4. **Retained off-screen dialogs** — SAP leaks dismissed dialog windows (observed climbing 10→28 in
   one session). Usually stale; restart the SAP session if it grows and input misbehaves.

## Measured AX capability map — do not re-derive

Tested against SAP GUI for Java 8.10rev4.

**Works with the app in the background:** reading the whole screen as text; writing text via
`AXSelectedTextRange` + `AXSelectedText`; `AXPress` on buttons, including ones that round-trip to
the SAP server; detecting a blocking popup via `AXFocusedWindow`; selecting text inside input fields.

**Does not work — do not retry:**

- `AXValue` — settable nowhere, and it **reports `.success` while silently discarding the write**.
  This is the trap that makes AX look impossible. Always verify a write landed.
- `AXFocused` — likewise accepted and silently discarded; focus is not steerable from outside.
- `CGEvent.postToPid` while the app is backgrounded — never delivered.
- `AXEnhancedUserInterface` / `AXManualAccessibility` — not implemented.
- Selecting text in `AXStaticText` (ordinary screen content) — readable, not selectable.
- `screencapture` of an occluded SAP window — returns a blank buffer.

**Current limitation:** only the **command field** is writable. Filling arbitrary dynpro fields is
not implemented yet, though the mechanism is the same.

## Silent frontend gaps in SAP GUI for Java

Some SAP functions call a **frontend component** instead of drawing a normal screen. SAP GUI for
Java implements only a subset, and an unimplemented one **fails silently** — ABAP accepts the
click, no error is raised, nothing renders.

Observed: SCC3's **Monitor** button does nothing on Java (press registers, screen unchanged 9s
later) while it opens a self-refreshing monitor on Windows. The session reported its running
program as `SAPLGRAP`, SAP's frontend-services function group — which also sits behind frontend
file dialogs.

- A button that does nothing **while the preflight reports clear** is a missing frontend component,
  not blocked input.
- This is the nearest real thing to the phantom "save/open dialog": a screen waiting on a frontend
  call that never renders. Describe it as that, not as a macOS dialog.
- Prefer plain-dynpro or headless equivalents: `SM50`/`SM66`, `SM37`, or a table read.

**Classic SAP list output is unreadable via AX.** One SCC3 log screen — every statistic visible on
screen — exposed 9 static texts and none of the numbers. AX reads **dynpro** screens well and
**list** output not at all. Take list content from channel 1 instead of screen-scraping.

## Requirements

macOS with SAP GUI for Java, and Accessibility permission for the calling process, for channel 5.
Channel 1 needs `pyrfc` built against the SAP NW RFC SDK (it is not on PyPI) — see `INSTALL.md`.
Sessions must already be logged on; these scripts drive existing sessions, they do not log on.
Credentials come only from `creds exec`; nothing is stored here and nothing secret is printed.

Full background and how each entry above was measured:
https://github.com/adam0thman/sap-gui-control-skill
