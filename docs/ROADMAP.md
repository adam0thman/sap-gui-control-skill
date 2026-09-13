# Roadmap

Status as of 2026-09-13. "Verified" means tested against a real SAP system, not merely written.

## Channels

| # | Channel | Script | State |
|---|---------|--------|-------|
| 0 | OS / SAPControl | `sap_control.py` | **partly verified** — unauthenticated calls live; protected calls need an OS `<sid>adm` account |
| 1 | RFC / BAPI | `sap_rfc.py` | **verified** — reads, writes, guards, all live |
| 2 | Direct DB (read-only) | `sap_db.py` | **guard verified**, connection unverified — no reachable HANA |
| 3 | ADT over HTTP | `sap_adt.py` | **partly verified** — see below |
| 4 | OData / RAP | — | guidance only |
| 5 | AX background GUI | `ax_okcode.swift` | **verified** — read, write, press, submit, popup guard |
| 6 | SAP GUI scripting | `sap_script.sh` | **partly verified** — see below |
| 7 | Vision + mouse | (built-in) | last resort |

## Done

**M1 — write safety.** `sap_rfc.py` writes are opt-in: without `--commit` a call is validate-only
and always rolled back; a BAPI returning `E`/`A` is rolled back and never committed; committing
against `CREDS_ENV=prd` is refused without `--allow-prod`. All three verified live.

**M3 — tests and CI.** 25 stdlib-only unit tests (`python3 -m unittest discover -s tests`) over
table parsing, BAPIRET2 detection, the prod guard, ADT URL derivation and skill integrity. CI on
macOS runs the tests plus shell, Python and Swift checks and asserts the skill stays
self-contained. No dependencies, no build step.

**M2 — dynpro field addressing.** `ax_okcode.swift` gained `fields` (list writable inputs) and
`set <label> <text>` (write one by label), so it can fill a screen, not merely navigate. Captions
and inputs share an `AXDescription` in SAP, and are told apart by the caption carrying its own
text as its value and the input sitting to its right. Verified live against a `PRX` logon screen
with SAP in the background. Every write is read back, because `AXValue` writes report success and
silently do nothing.

**GUI prod guard verified.** Refused a state-changing action on a SID listed in `SAP_PROD_SIDS`,
permitted it with `--allow-prod`, and left unlisted SIDs alone.

**Channels 0, 3 and 6 implemented.** SAPControl over SOAP (no SAP login needed at all); ADT client
with a layered `ping` diagnosis; GUI-scripting runner with a verified object model.

## Not verified yet — do not assume these work

- **ADT happy path.** Every system reached so far rejects basic auth for authenticated services
  (`/sap/public/ping` 200, `/sap/bc/ping` 403), consistent with SNC/SSO-only logon. The failure
  diagnosis is verified; a successful `discovery`/`transports`/`source` call is not.
- **SAPControl protected calls** (`wp`, `syslog`, `queue`). `instances` and `processes` are
  verified live and need no credentials. The protected calls authenticate against the OS
  `<sid>adm` account, not a SAP logon — neither the SAP user nor the two available OS accounts
  were accepted on the instance tested, so those paths remain unexercised.
- **Channel 2 against a real database.** The read-only guard is unit-tested, but no HANA was
  reachable (every SQL port closed on the reachable host; the `kind: hana` entries need the
  TNB VPN), so connect/query is unexercised.
- **Channel 6 driving a session.** Now resolved in the negative: with `PRX (1)` logged on in the
  running app, a script still reported `connections: 0`, confirming it runs its own instance.
  Channel 6 is for self-contained automation only; driving an open session stays with channel 5.

## Next

**M6 — multi-step sequencing.** Run a sequence of steps with verification between each, ideally
cross-channel (act on 5, verify on 1). Only worth doing after M2.

**M7 — close the verification gaps above**, as systems allowing them become available.

## Not planned

Channel 4 (OData) until a system here exposes services worth calling. Channel 7 needs no script —
it is the built-in computer-use tool, and the skill's job is to keep tasks away from it.
