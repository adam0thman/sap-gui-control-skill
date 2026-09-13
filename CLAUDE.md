# sap-gui-control

A Claude skill for SAP on macOS. The deliverable is `skills/sap-gui-control/`, which is
installed to `~/.claude/skills/`. There is no server and no build step.

## Working rules

- **Headless before GUI.** Try `sap_rfc.py` first. Most questions — table contents, job status,
  system info — never need a screen.
- **Never screenshot SAP GUI to find out what is on it.** Read it through the accessibility tree.
- **Never guess why input failed.** Run `scripts/tier3_preflight.sh`; it names the actual cause.
- Credentials only via `creds exec <id>`; never echo `CREDS_PASSWORD`.
- Production writes need explicit authorization in-conversation.
- Prefer routes that don't take over the screen — the user is still using their machine.
- Report honestly: "it ran" and "I verified the result" are different claims.

## Editing the skill

`skills/sap-gui-control/` is the single canonical copy — it is installed verbatim, so it must
stay self-contained. Do not create a second copy elsewhere in the repo; an earlier duplicate
silently diverged within one session.

After changing it, reinstall and verify:

```bash
cp -r skills/sap-gui-control ~/.claude/skills/
diff -r skills/sap-gui-control ~/.claude/skills/sap-gui-control   # must be identical
swiftc -typecheck skills/sap-gui-control/scripts/ax_okcode.swift
bash -n skills/sap-gui-control/scripts/tier3_preflight.sh
python3 -c "import ast;ast.parse(open('skills/sap-gui-control/scripts/sap_rfc.py').read())"
```

Changes to the measured capability map must come from an actual test against a real SAP GUI,
never from assumption — several entries in it contradict what the APIs appear to promise.
