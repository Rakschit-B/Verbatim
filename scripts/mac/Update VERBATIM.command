#!/bin/bash
# Checks for a newer VERBATIM, verifies it (SHA-256 + signature) and installs it.
APP="/Applications/VERBATIM.app/Contents/MacOS/VERBATIM"
HERE="$(cd "$(dirname "$0")" && pwd)"
if [[ -x "$APP" ]]; then
  "$APP" --update "$@"
elif [[ -x "$HERE/../../.venv/bin/python" ]]; then   # source install
  "$HERE/../../.venv/bin/python" "$HERE/../../run.py" --update "$@"
else
  echo "VERBATIM is not installed in /Applications."
fi
[[ " $* " == *" --auto "* ]] || read -n1 -p "Press a key to close"
