#!/bin/bash
# Build Magpiary.app: the bundled Python 3.12 + Magpiary + its libraries (yt-dlp included) + the native menu-bar shell.
# Usage: packaging/app/build-app.sh [output folder]   (default: ../workbench/build beside the repo, outside git)
# Unsigned (ad-hoc signature only): downloaders see macOS's "unidentified developer" step, which the README explains.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="${1:-$ROOT/../workbench/build}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
ARCH="$(uname -m)"
APP="$OUT/Magpiary.app"
RES="$APP/Contents/Resources"

echo "== Magpiary $VERSION ($ARCH) -> $APP"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$RES"

echo "== Python 3.12 (python-build-standalone via uv)"
uv python install 3.12 >/dev/null
PYSRC="$(ls -d "$(uv python dir)"/cpython-3.12.*-macos-*-none | sort | tail -1)"
cp -R "$PYSRC" "$RES/python"
rm -f "$RES/python/lib/python3.12/EXTERNALLY-MANAGED"
PY="$RES/python/bin/python3"

echo "== Magpiary wheel + libraries"
WHEELS="$(mktemp -d)"
(cd "$ROOT" && uv build --wheel --out-dir "$WHEELS" >/dev/null)
uv pip install --quiet --python "$PY" --break-system-packages "$WHEELS"/magpiary-*.whl

echo "== Relocatable launchers (pip's scripts point at the build folder)"
for pair in "magpiary:magpiary.cli" "yt-dlp:yt_dlp"; do
  name="${pair%%:*}"; module="${pair##*:}"
  newer=""
  # Daily yt-dlp updates live outside the app (tools.ytdlp_updates_dir), so they never break its signature.
  [ "$name" = yt-dlp ] && newer='updates="${MAGPIARY_HOME:-$HOME/Magpiary}/tools/yt-dlp-updates"; [ -d "$updates/yt_dlp" ] && export PYTHONPATH="$updates"'
  cat > "$RES/python/bin/$name" <<LAUNCH
#!/bin/sh
here="\$(cd "\$(dirname "\$0")" && pwd)"
$newer
PYTHONDONTWRITEBYTECODE=1 MAGPIARY_PROGRAM="\$here/$name" exec "\$here/python3" -m $module "\$@"
LAUNCH
  chmod 755 "$RES/python/bin/$name"
done

echo "== Trim what the app never uses"
LIB="$RES/python/lib/python3.12"
rm -rf "$LIB/site-packages/PyObjCTest" "$RES/python/lib/libtcl"* "$RES/python/lib/libtk"* "$RES/python/lib/tcl"* "$RES/python/lib/tk"* "$RES/python/lib/itcl"* "$RES/python/lib/thread"*
rm -rf "$LIB/test" "$LIB/idlelib" "$LIB/tkinter" "$LIB/turtledemo" "$LIB/lib2to3" "$RES/python/share" "$RES/python/include"
rm -f "$RES/python/bin/idle3"* "$RES/python/bin/2to3"* "$RES/python/bin/python3-config" "$RES/python/bin/python3.12-config" "$RES/python/bin/pydoc3"*
find "$RES/python" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
# Compile everything now: at run time the app must not write into its own (signed) folder.
"$PY" -m compileall -q -j 0 "$RES/python/lib" || true

echo "== Scrub the build machine's folder names from the bundled Python"
# uv records where it installed Python (inside your home folder) in these files; none of it is used at run time.
sed -i '' "s#$PYSRC#/python#g" "$LIB/_sysconfigdata__darwin_darwin.py"
install_name_tool -id "@rpath/libpython3.12.dylib" "$RES/python/lib/libpython3.12.dylib"
"$PY" -m compileall -q -f "$LIB/_sysconfigdata__darwin_darwin.py"
if grep -rlaF "$HOME/" "$APP"; then echo "The app still contains this Mac's home path (files above); refusing to continue." >&2; exit 1; fi

echo "== Native shell (Swift)"
swiftc -O -target "$ARCH-apple-macos12.0" -o "$APP/Contents/MacOS/Magpiary" "$HERE"/main.swift "$HERE"/InstallerWindow.swift "$HERE"/Panel.swift -framework AppKit -framework WebKit
# The hub's launcher: launchd starts it and it runs the hub, so macOS permission prompts name Magpiary, not Python.
clang -O2 -target "$ARCH-apple-macos12.0" -o "$APP/Contents/MacOS/magpiary-hub" "$ROOT/src/magpiary/helper/hub.c"

cp -R "$HERE/installer" "$RES/installer"
cp -R "$HERE/panel" "$RES/panel"
echo "== Icon, logos, Info.plist"
for tone in white black; do cp "$ROOT/assets/magpiary-symbol-$tone-256.png" "$RES/symbol-$tone.png"; done
ICONSET="$(mktemp -d)/Magpiary.iconset"; mkdir -p "$ICONSET"
SRC="$ROOT/assets/magpiary-app-icon-1024.png"
for size in 16 32 128 256 512; do
  sips -z $size $size "$SRC" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z $((size*2)) $((size*2)) "$SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$RES/Magpiary.icns"
sed "s/@VERSION@/$VERSION/g" "$HERE/Info.plist" > "$APP/Contents/Info.plist"

echo "== Ad-hoc signature"
codesign --force --deep --sign - "$APP" 2>&1 | tail -2 || true

echo "== Done: $(du -sh "$APP" | cut -f1)  $APP"
