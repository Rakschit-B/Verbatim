#!/bin/bash
# Installs a macOS LaunchAgent that checks for VERBATIM updates every Monday at 10:00
# (and at login if the Mac was asleep). Run again with --remove to turn it off.
LABEL="in.infinitestory.verbatim.updater"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null; rm -f "$PLIST"; echo "Automatic updates turned off."; exit 0
fi
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/Applications/VERBATIM.app/Contents/MacOS/VERBATIM</string><string>--update</string><string>--auto</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/VERBATIM-updater.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/VERBATIM-updater.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "Weekly update check scheduled (Mondays 10:00). Log: ~/Library/Logs/VERBATIM-updater.log"
read -n1 -p "Press a key to close"
