#!/bin/bash
# VERBATIM — Infinite Story LLP. Clears the macOS download quarantine flag and opens VERBATIM.
# Use this if macOS says VERBATIM "is damaged", "cannot be opened", or it bounces once and closes.
APP="/Applications/VERBATIM.app"
if [ ! -d "$APP" ]; then echo "Drag VERBATIM into Applications first."; read -r -p "Press Enter to close"; exit 1; fi
echo "Allowing VERBATIM to run on this Mac (you may be asked for your password)…"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || sudo xattr -dr com.apple.quarantine "$APP"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
open "$APP"
echo "Done. If it still does not open, send ~/Library/Logs/VERBATIM.log to Infinite Story."
sleep 3
