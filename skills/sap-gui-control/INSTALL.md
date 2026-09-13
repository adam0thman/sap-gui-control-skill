# Installing the sap-gui-control skill

This directory is the versioned source. Claude reads skills from `~/.claude/skills/`:

```bash
cp -r skills/sap-gui-control ~/.claude/skills/
```

User-level (`~/.claude/skills/`) rather than project-level on purpose: SAP work happens in many
sessions and directories, not just this repo. A user-level skill loads everywhere.

Skills load at session start — **restart Claude** after installing.

## Requirements

**For the GUI scripts** (`ax_okcode.swift`, `gui_preflight.sh`):

- macOS with SAP GUI for Java
- Swift (Xcode Command Line Tools)
- Accessibility permission granted to the process that runs them

**For the RFC script** (`sap_rfc.py`) — optional but preferred, since it avoids the GUI entirely:

- `pyrfc`, which is **not on PyPI** (yanked) and must be built against the SAP NW RFC SDK:

  ```bash
  SAPNWRFC_HOME=/path/to/nwrfcsdk pip install "pyrfc @ git+https://github.com/SAP/PyRFC.git"
  ```

  The SDK is a separate download from SAP under your own licence. The script copies the SDK's
  dylibs next to the pyrfc extension on first use, because macOS strips `DYLD_*` across process
  spawns (including `creds exec`) and the extension resolves them at `@loader_path`.

- Credentials come only from `creds exec <system-id> -- ...`. Nothing is stored here.

## Verify

```bash
bash ~/.claude/skills/sap-gui-control/scripts/gui_preflight.sh
creds exec <system-id> -- python3 ~/.claude/skills/sap-gui-control/scripts/sap_rfc.py info
```
