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

**Channels 0, 3 and 6 implemented.** SAPControl over SOAP (no SAP login needed at all); ADT client
with a layered `ping` diagnosis; GUI-scripting runner with a verified object model.

## Not verified yet — do not assume these work

- **GUI-side prod guard** (`SAP_PROD_SIDS` in `ax_okcode.swift`). Written, never exercised: no
  session was logged on. It is also weaker by design — a window title carries a SID but not an
  environment, and this landscape contains a sandbox whose SID is literally `PRD`, so SID-based
  inference is unreliable. **With `SAP_PROD_SIDS` unset there is no protection on the GUI path.**
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
- **Channel 6 against a live session.** `probe` works and the object model is confirmed by
  reflection, but no script has driven a logged-on session, and
  `openConnectionByConnectionString` blocked when tried.

## Next

**M2 — write to any dynpro field.** The biggest functional gap: `ax_okcode.swift` can only write
the command field, so it can navigate but not fill in a screen. The mechanism is already proven
(`AXSelectedTextRange` + `AXSelectedText` on an `AXTextField`); it needs generalising to address
fields by label and verify after write. **Requires a logged-on session to develop against** —
worth doing live rather than shipping blind.

**M6 — multi-step sequencing.** Run a sequence of steps with verification between each, ideally
cross-channel (act on 5, verify on 1). Only worth doing after M2.

**M7 — close the verification gaps above**, as systems allowing them become available.

## Not planned

Channel 4 (OData) until a system here exposes services worth calling. Channel 7 needs no script —
it is the built-in computer-use tool, and the skill's job is to keep tasks away from it.
