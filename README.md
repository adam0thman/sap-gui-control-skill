# sap-gui-control

A Claude **skill** for interacting with SAP efficiently — by choosing the right **channel** for
each step of a task rather than reaching for the GUI by reflex.

Most SAP work does not need a screen at all. The skill routes each step to the cheapest channel
that can do it, and when the GUI genuinely is required it drives **SAP GUI for Java** in the
background: no screenshots, no coordinate clicking, no stealing focus. You keep using your machine.

## Channels

| # | Channel | Script | Status |
|---|---------|--------|--------|
| 0 | OS / SAPControl (no SAP login) | `sap_control.py` | unauthenticated calls verified live |
| 1 | **RFC / BAPI** | `sap_rfc.py` | verified live incl. write guards |
| 2 | Direct DB, **read-only** | `sap_db.py` | guard tested; connection unverified |
| 3 | ADT over HTTP | `sap_adt.py` | diagnosis verified; happy path unverified |
| 4 | OData / RAP | — | guidance |
| 5 | **AX background GUI control** | `ax_okcode.swift` | verified live |
| 6 | SAP GUI scripting | `sap_script.sh` | object model verified; live session unverified |
| 7 | Vision + mouse | (built-in) | last resort |

Plus `gui_preflight.sh`, which says *why* GUI input is failing instead of leaving you to guess.

The decision table for picking between them — and for splitting one task across several — is in
[SKILL.md](skills/sap-gui-control/SKILL.md).

## What it does

```bash
SK=~/.claude/skills/sap-gui-control/scripts

# headless first — no GUI involved at all
creds exec <system-id> -- python3 $SK/sap_rfc.py info
creds exec <system-id> -- python3 $SK/sap_rfc.py table T000 MANDT,MTEXT --rows 5

# GUI, driven in the background
swift $SK/ax_okcode.swift probe "ECD (2)"
swift $SK/ax_okcode.swift run   "ECD (2)" "/nSE16"
swift $SK/ax_okcode.swift press "ECD (2)" "Back (F3)"

# why is input failing? (never guess)
bash $SK/gui_preflight.sh
```

## Why it exists

Driving SAP GUI on macOS fails in ways that are invisible on screen, so an assistant tends to
invent an explanation. Three separate sessions independently reported *"a macOS Open/Save dialog
is attached to the SAP GUI, blocking input."* That dialog never existed. The real causes were:

- **the frontmost-app policy** — a browser in front blocks clicks *and* typing; a terminal or IDE
  blocks typing but allows clicks. That asymmetry is diagnostic: a modal dialog would block both.
- **a SAP dynpro popup owning input** — these are separate windows with `AXModal=false` and no
  attached sheet, so sheet/modal checks report "all clear" while the session is fully blocked.
- **sessions sharing identical geometry** — several SAP windows open full-screen at the same
  coordinates, so a click lands on the topmost one, not the one you meant.

`gui_preflight.sh` distinguishes all three, so the answer is measured instead of guessed.

## Install

```bash
cp -r skills/sap-gui-control ~/.claude/skills/
```

User-level on purpose — SAP work happens in many sessions and directories, not one repo.
See [INSTALL.md](skills/sap-gui-control/INSTALL.md).

**Requirements**: macOS, SAP GUI for Java, and Accessibility permission for the calling process.
The RFC script additionally needs `pyrfc` built against the SAP NW RFC SDK (it is not on PyPI).
Credentials come only from `creds exec`; nothing secret is stored or printed.

## What works, and what doesn't

Measured against SAP GUI for Java 8.10rev4 — not assumed:

**Works with SAP in the background** — reading the whole screen as text; writing text via
`AXSelectedTextRange` + `AXSelectedText`; `AXPress` on buttons, including ones that round-trip to
the SAP server; detecting a blocking popup via `AXFocusedWindow`; selecting text inside input fields.

**Does not work** — `AXValue` is settable nowhere and *silently discards writes while reporting
success* (the trap that makes AX look impossible); `AXFocused` is likewise accepted and discarded;
`CGEvent.postToPid` never arrives while the app is backgrounded; `AXEnhancedUserInterface` is not
implemented; classic SAP **list** output exposes almost nothing to accessibility, so list content
must come from RFC rather than screen-scraping.

Some SAP functions also call a **frontend component** that SAP GUI for Java does not implement —
they fail silently, with the preflight reporting clear. SCC3's *Monitor* button is one.

## History

This began as an MCP server with a cost-routing engine. That work is preserved at tag
[`v0.1.0`](../../releases/tag/v0.1.0) and was removed from `main`: the capability people actually
used was the skill, and the router had only one tier to route between. The genuinely hard-won
part — the pyrfc / NW RFC SDK wiring — survives as `sap_rfc.py`.

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with or endorsed by SAP SE. "SAP", "SAP GUI" and "S/4HANA" are trademarks of SAP SE.
