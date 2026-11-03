#!/bin/bash
# Build Magpiary-<version>.dmg: the app, a shortcut to Applications and a backdrop that says what to do.
# Usage: packaging/app/build-dmg.sh <app folder> <output folder>   (the .app comes from build-app.sh)
# Unsigned: the disk image carries only the app's ad-hoc signature, so downloaders see macOS's "unidentified developer" step.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
APP="${1:?path to Magpiary.app}"; OUT="${2:?output folder}"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$APP/Contents/Info.plist")"
NAME="Magpiary-$VERSION"
mkdir -p "$OUT"
WORK="$(mktemp -d)"; MOUNT="/Volumes/Magpiary $VERSION"
trap 'hdiutil detach "$MOUNT" -quiet -force 2>/dev/null || true; rm -rf "$WORK"' EXIT

echo "== Staging"
mkdir -p "$WORK/stage/.background"
ditto "$APP" "$WORK/stage/Magpiary.app"   # ditto keeps the signature, links and permissions intact
ln -s /Applications "$WORK/stage/Applications"
uv run --with pillow python "$HERE/dmg-backdrop.py" "$WORK/backdrop.tiff" "$ROOT/assets"
tiffutil -cathidpicheck "$WORK/backdrop.png" "$WORK/backdrop@2x.png" -out "$WORK/stage/.background/backdrop.tiff"

echo "== Disk image"
hdiutil create -quiet -srcfolder "$WORK/stage" -volname "Magpiary $VERSION" -fs HFS+ -format UDRW -ov "$WORK/rw.dmg"
hdiutil attach -quiet -readwrite -noverify -noautoopen "$WORK/rw.dmg"
# Window size, icon places and the backdrop are Finder settings; if Finder will not take them (no permission), the
# image still works, it just opens as a plain folder.
LAYOUT="$(cat <<OSA
tell application "Finder"
  tell disk "Magpiary $VERSION"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 960, 648}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 128
    set background picture of opts to file ".background:backdrop.tiff"
    set position of item "Magpiary.app" of container window to {215, 195}
    set position of item "Applications" of container window to {545, 195}
    close
    open
    update without registering applications
    delay 2
    close
  end tell
end tell
OSA
)"
for try in 1 2 3; do   # Finder is sometimes busy the first time
  osascript -e "$LAYOUT" >/dev/null 2>"$WORK/osa.err" && break
  [ "$try" = 3 ] && echo "   (Finder layout skipped: $(head -c 300 "$WORK/osa.err"))"
  sleep 3
done
# the disk's own icon on the desktop is the app's icon (needs Xcode's command line tools; skipped without them)
cp "$APP/Contents/Resources/Magpiary.icns" "$MOUNT/.VolumeIcon.icns" 2>/dev/null && { SetFile -a C "$MOUNT" 2>/dev/null || true; }
sync; chflags hidden "$MOUNT/.background" "$MOUNT/.VolumeIcon.icns" 2>/dev/null || true
hdiutil detach "$MOUNT" -quiet
hdiutil convert -quiet "$WORK/rw.dmg" -format UDZO -imagekey zlib-level=9 -ov -o "$OUT/$NAME.dmg"
( cd "$OUT" && shasum -a 256 "$NAME.dmg" >> SHA256SUMS )
echo "== Done: $(du -h "$OUT/$NAME.dmg" | cut -f1)  $OUT/$NAME.dmg"
