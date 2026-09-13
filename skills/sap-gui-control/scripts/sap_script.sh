#!/usr/bin/env bash
# Channel 6 — SAP GUI for Java scripting (JavaScript, via GuiStartS.jar).
#
# SAP GUI for Java embeds a JavaScript engine and exposes the GUI Scripting object
# model to it. Once a routine is written down it replays deterministically, which
# makes this better than channel 5 (AX) for anything done repeatedly.
#
#   sap_script.sh probe                 # connections/sessions the engine can see
#   sap_script.sh run  <file.js>        # run a script file (synchronous)
#   sap_script.sh eval '<javascript>'   # run an inline snippet (synchronous)
#   sap_script.sh --async run <file.js> # fire and forget
#
# IMPORTANT — measured, not assumed: this starts its OWN SAP GUI instance. It does
# NOT attach to the SAP GUI you already have open (a script that opened a
# connection produced no window in the running app, and the running app's sessions
# are not visible to it). So:
#   * channel 6 is for SELF-CONTAINED automation — it opens its own connection,
#     does the work, and exits.
#   * to drive a session that is ALREADY open, use channel 5 (ax_okcode.swift).
# The JVM also does not exit by itself after the script finishes, so every run is
# wrapped in a timeout below.
#
# The object model is Java-flavoured, NOT the Windows VBScript spelling. Use
# getters, verified by reflection against GuiApplicationWrapper:
#
#   application.getMajorVersion()
#   var conns = application.getConnections();  conns.getLength();  conns.elementAt(i)
#   var ses   = conn.getSessions();            ses.getLength();    ses.elementAt(j)
#   application.findById("...")
#   java.lang.System.out.println(x)            // how you print
#
# `application.Children.Count` (the Windows spelling) is undefined here.
#
# PREREQUISITE: SAP GUI Scripting must be enabled on BOTH sides — server profile
# parameter sapgui/user_scripting = TRUE (RZ11), and the client's own scripting
# setting. Without it the engine runs but the session objects stay unavailable.
set -uo pipefail

ASYNC=0
if [ "${1:-}" = "--async" ]; then ASYNC=1; shift; fi
CMD="${1:-}"; shift || true

# Locate an install that actually contains the scripting jar. Several SAP GUI
# versions may be installed side by side; prefer an explicit override, then the
# highest version that has GuiStartS.jar.
TIMEOUT="${SAP_SCRIPT_TIMEOUT:-60}"
APP="${SAPGUI_APP:-}"
if [ -z "$APP" ]; then
  # NUL-delimited: SAP GUI install paths contain spaces ("SAPGUI 8.10rev4.app"),
  # so word-splitting a glob or ls here silently finds nothing.
  while IFS= read -r -d '' cand; do
    if [ -f "$cand/Contents/Resources/Java/GuiStartS.jar" ]; then APP="$cand"; break; fi
  done < <(find "/Applications/SAP Clients" -maxdepth 2 -name "*.app" -print0 2>/dev/null | sort -zVr)
fi
if [ -z "$APP" ]; then
  echo "SAP GUI for Java not found under /Applications/SAP Clients/" >&2; exit 3
fi
RES="$APP/Contents/Resources"
JAR="$RES/Java/GuiStartS.jar"
JAVA="$RES/jre/Contents/Home/bin/java"
[ -x "$JAVA" ] || JAVA=$(command -v java) || true
if [ ! -f "$JAR" ] || [ -z "${JAVA:-}" ]; then
  echo "GuiStartS.jar or a JRE is missing under $RES" >&2; exit 3
fi

run_js() {   # $1 = path to .js
  local flag="-F"; [ "$ASYNC" = "1" ] && flag="-f"
  # -n no logon window, -b no splash. The JVM lingers after the script completes,
  # so it is bounded by a timeout rather than waited on. Exit 124 means the script
  # ran but the JVM was reaped, which is normal, not a failure.
  timeout "$TIMEOUT" "$JAVA" -cp "$JAR" com.sap.platin.Gui -n -b "$flag" "$1" 2>&1 \
    | grep -v "MacOSXConnect.cpp" || true
}
eval_js() {  # $1 = javascript source
  local tmp; tmp=$(mktemp -t sapscript).js
  printf '%s\n' "$1" > "$tmp"
  run_js "$tmp"
  rm -f "$tmp"
}

case "$CMD" in
  probe)
    eval_js '
function out(s){ java.lang.System.out.println(s); }
try {
  out("SAP GUI version: " + application.getMajorVersion() + "." + application.getMinorVersion());
  var conns = application.getConnections();
  out("connections: " + conns.getLength());
  for (var i = 0; i < conns.getLength(); i++) {
    var c = conns.elementAt(i);
    out("  conn[" + i + "] id=" + c.getId() + " desc=" + c.getDescription());
    var ses = c.getSessions();
    for (var j = 0; j < ses.getLength(); j++) {
      out("    session[" + j + "] id=" + ses.elementAt(j).getId());
    }
  }
  if (conns.getLength() === 0) {
    out("");
    out("No connections visible. Either nothing is logged on, or SAP GUI Scripting");
    out("is disabled (server sapgui/user_scripting=TRUE, plus the client setting).");
  }
} catch (e) { out("ERR: " + e); }'
    ;;
  run)
    [ -f "${1:-}" ] || { echo "usage: sap_script.sh run <file.js>" >&2; exit 64; }
    run_js "$1" ;;
  eval)
    [ -n "${1:-}" ] || { echo "usage: sap_script.sh eval '<javascript>'" >&2; exit 64; }
    eval_js "$1" ;;
  *)
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 64 ;;
esac
