#!/bin/bash
# VERBATIM launcher: runs the bundled Python 3.12 (no system Python needed).
CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
R="$CONTENTS/Resources"
export PYTHONHOME="$R/python"
export PYTHONPATH="$R/app:$R/site-packages"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
LOG="$HOME/Library/Logs/VERBATIM.log"
mkdir -p "$HOME/Library/Logs"
if [[ -n "$1" ]]; then   # command-line use: --cli / --update / --version
  exec "$R/python/bin/python3.12" -s "$R/app/run.py" "$@"
fi
"$R/python/bin/python3.12" -s "$R/app/run.py" >>"$LOG" 2>&1
status=$?
if [[ $status -ne 0 ]]; then
  /usr/bin/osascript -e "display dialog \"VERBATIM could not start (code $status).\n\nDetails were saved to ~/Library/Logs/VERBATIM.log\" buttons {\"OK\"} with icon caution with title \"VERBATIM\"" >/dev/null 2>&1
fi
exit $status
