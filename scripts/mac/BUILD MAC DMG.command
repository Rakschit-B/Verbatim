#!/bin/bash
# Builds dist/VERBATIM-<version>-mac-arm64.dmg on an Apple Silicon Mac. Double-click to run.
set -euo pipefail
cd "$(dirname "$0")/../.."
echo "=== VERBATIM — Mac app + DMG builder ==="
[[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]] || { echo "Needs an Apple Silicon Mac."; read -n1 -p "Press a key"; exit 1; }
PY=""
for c in /opt/homebrew/bin/python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.12; do
  [[ -x "$c" ]] && { PY="$c"; break; }
done
[[ -n "$PY" ]] || { echo "Install Python 3.12 from python.org (or: brew install python@3.12), then run again."; read -n1 -p "Press a key"; exit 1; }
"$PY" -m venv .buildvenv
source .buildvenv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements-dev.txt
echo "--- running tests"
python -m pytest -q tests || { echo "Tests failed — not building."; read -n1 -p "Press a key"; exit 1; }
VERSION=$(python -c "import verbatim;print(verbatim.__version__)")
echo "--- building VERBATIM $VERSION"
rm -rf build dist/VERBATIM dist/VERBATIM.app
pyinstaller --noconfirm --clean packaging/VERBATIM.spec
APP=dist/VERBATIM.app
if [[ -n "${MAC_SIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp -s "$MAC_SIGN_IDENTITY" "$APP"
else
  codesign --force --deep -s - "$APP"   # ad-hoc signature (required on Apple Silicon)
fi
echo "--- smoke test"
"$APP/Contents/MacOS/VERBATIM" --version
STAGE=$(mktemp -d); cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
cp "scripts/mac/Update VERBATIM.command" "scripts/mac/Schedule Weekly Updates.command" "$STAGE/" 
cp docs/READ_ME_FIRST.txt "$STAGE/READ ME FIRST.txt" 2>/dev/null || true
DMG="dist/VERBATIM-$VERSION-mac-arm64.dmg"
rm -f "$DMG"
hdiutil create -volname "VERBATIM $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
if [[ -n "${MAC_SIGN_IDENTITY:-}" && -n "${NOTARY_PROFILE:-}" ]]; then
  codesign -s "$MAC_SIGN_IDENTITY" --timestamp "$DMG"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait && xcrun stapler staple "$DMG"
fi
shasum -a 256 "$DMG"
open dist
echo "DMG ready: $PWD/$DMG"
read -n1 -p "Press a key to close"
