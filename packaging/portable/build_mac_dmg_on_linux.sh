#!/bin/bash
# Cross-build the Apple Silicon DMG on Linux (no Mac needed) — how the 2.1.0 DMG was produced.
#   1) bundled Python 3.12 (python-build-standalone, aarch64-apple-darwin)
#   2) macOS arm64 wheels installed with pip --platform (single pass, then mlx-whisper --no-deps)
#   3) universal binaries thinned to arm64, unused Qt modules removed, bytecode precompiled
#   4) HFS+ image made by mkhfsplus.py + libdmg-hfsplus `hfsplus`, compressed to UDIF by `dmg`
# Requires: python3, llvm-lipo, cmake+gcc (to build libdmg-hfsplus once), internet.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$HERE/../.."; W="${WORK:-$PWD/macbuild}"
VER=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');import verbatim;print(verbatim.__version__)")
PBS="https://github.com/astral-sh/python-build-standalone/releases/download/20251014"
mkdir -p "$W" && cd "$W"
[ -d libdmg-hfsplus ] || git clone -q --depth 1 https://github.com/fanquake/libdmg-hfsplus.git
[ -d planetbeing ] || git clone -q --depth 1 https://github.com/planetbeing/libdmg-hfsplus.git planetbeing
(cd libdmg-hfsplus && cmake -B build -DCMAKE_BUILD_TYPE=Release >/dev/null && make -C build -j4 dmg-bin >/dev/null)
(cd planetbeing && cmake -B build -DCMAKE_BUILD_TYPE=Release >/dev/null && make -C build -j4 hfsplus >/dev/null || true)
DMGTOOL=$W/libdmg-hfsplus/build/dmg/dmg; HFS=$W/planetbeing/build/hfs/hfsplus
APP="$W/VERBATIM.app"; R="$APP/Contents/Resources"; rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$R"
curl -sSL "$PBS/cpython-3.12.12+20251014-aarch64-apple-darwin-install_only.tar.gz" | tar xz -C "$R"
TAGS=(--platform macosx_14_0_arm64 --python-version 3.12 --implementation cp --abi cp312 --abi abi3 --abi none --only-binary=:all:)
pip install -q --target "$R/site-packages" "${TAGS[@]}" -r "$HERE/requirements-mac-arm64.txt"
pip install -q --target "$W/tmpw" --no-deps "${TAGS[@]}" mlx-whisper && cp -rn "$W/tmpw/"* "$R/site-packages/" && rm -rf "$W/tmpw"
find "$R" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) -exec file {} + | grep "universal binary" | cut -d: -f1 |
  while IFS= read -r f; do llvm-lipo "$f" -thin arm64 -output "$f.t" && mv "$f.t" "$f"; done
SP="$R/site-packages"; ( cd "$SP/PySide6/Qt/lib" && for fw in *.framework; do case $fw in QtCore.*|QtGui.*|QtWidgets.*|QtDBus.*|QtSvg.*) ;; *) rm -rf "$fw";; esac; done )
rm -rf "$SP"/PySide6/{Assistant.app,Designer.app,Linguist.app,Qt/qml,include,typesystems,glue,doc} "$SP"/mlx/include "$SP"/bin
mkdir -p "$R/app" && cp -r "$ROOT"/{verbatim,assets,run.py} "$R/app/" && cp "$ROOT/assets/VERBATIM.icns" "$R/"
mkdir -p "$R/models/sherpa" && curl -sSL --retry 5 "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2" | tar xj -C "$R/models/sherpa" && rm -rf "$R"/models/sherpa/*/test_wavs
cp "$HERE/mac/launcher.sh" "$APP/Contents/MacOS/VERBATIM" && chmod 755 "$APP/Contents/MacOS/VERBATIM"
sed "s/2\.1\.0/$VER/g" "$HERE/mac/Info.plist" > "$APP/Contents/Info.plist"; printf 'APPL????' > "$APP/Contents/PkgInfo"
"$R/../Resources/python/bin/python3.12" -V 2>/dev/null || true   # (mac binary; skipped on Linux)
STAGE="$W/stage"; rm -rf "$STAGE" "$W/flat"; mkdir "$STAGE"; cp -a "$APP" "$STAGE/"
cp "$ROOT/scripts/mac/"{"Update VERBATIM.command","Schedule Weekly Updates.command"} "$STAGE/"; cp "$ROOT/docs/READ_ME_FIRST.txt" "$STAGE/READ ME FIRST.txt"
ln -s /Applications "$STAGE/Applications"; cp -a "$STAGE" "$W/flat"; find "$W/flat" -type l -delete
python3 "$HERE/mkhfsplus.py" "$W/raw.img" $(( $(du -sm "$W/flat" | cut -f1) * 13 / 10 + 120 )) "VERBATIM ${VER%.*}"
"$HFS" "$W/raw.img" addall "$W/flat" >/dev/null
find "$STAGE" -type f -perm -u+x | while read -r f; do "$HFS" "$W/raw.img" chmod 755 "${f#$STAGE}" >/dev/null; done
find "$STAGE" -type l | while read -r l; do "$HFS" "$W/raw.img" symlink "${l#$STAGE}" "$(readlink "$l")" >/dev/null; done
"$DMGTOOL" "$W/raw.img" "$W/VERBATIM-$VER-mac-arm64.dmg" && sha256sum "$W/VERBATIM-$VER-mac-arm64.dmg"
