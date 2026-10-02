#!/bin/zsh
# Builds EqualEd.app around the demo. macOS only gives camera and microphone access
# to apps, not to scripts run from Terminal, so this wrapper is needed.
#   ./make_app.sh            build EqualEd.app in this folder
#   ./make_app.sh --install  also copy it into /Applications (Spotlight, Launchpad, Dock)
set -e
cd "$(dirname "$0")"
PROJECT="$(pwd -P)"
PYHOME=$(.venv/bin/python -c "import sys; print(sys.base_prefix)")
INC=$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['include'])")
APP="EqualEd.app"
BUNDLE_ID=${BUNDLE_ID:-org.equaled.demo}   # reuse an existing ID to keep camera/mic permissions
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# icon: brain over a desk (assets/icon.svg -> assets/icon_1024.png -> AppIcon.icns)
ICONSET=$(mktemp -d)/AppIcon.iconset; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s assets/icon_1024.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) assets/icon_1024.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>EqualEd</string>
  <key>CFBundleDisplayName</key><string>EqualEd</string>
  <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSCameraUsageDescription</key><string>EqualEd watches the classroom for sensory triggers and the student's reactions. Video stays on this Mac unless Cosmos live reasoning is turned on.</string>
  <key>NSMicrophoneUsageDescription</key><string>EqualEd hears sudden loud sounds and transcribes the lecture for the ADHD rewind.</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
clang -O2 -DPYHOME="\"$PYHOME\"" -DPROJECT_DIR="\"$PROJECT\"" -I"$INC" -L"$PYHOME/lib" -lpython3.11 \
  -Wl,-rpath,"$PYHOME/lib" -o "$APP/Contents/MacOS/launcher" launcher.c
codesign --force --sign - "$APP"
echo "Built $APP."
if [[ "$1" == "--install" ]]; then
  rm -rf "/Applications/$APP"; cp -R "$APP" /Applications/
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "/Applications/$APP"
  echo "Installed to /Applications/$APP. Open it from Spotlight or Launchpad."
fi

# Second app: "EqualEd Teacher" opens the teacher dashboard (starts EqualEd first if needed).
rm -rf "EqualEd Teacher.app"
osacompile -o "EqualEd Teacher.app" teacher_app.applescript
cp "$APP/Contents/Resources/AppIcon.icns" "EqualEd Teacher.app/Contents/Resources/applet.icns"
codesign --force --deep --sign - "EqualEd Teacher.app"
if [[ "$1" == "--install" ]]; then
  rm -rf "/Applications/EqualEd Teacher.app"; cp -R "EqualEd Teacher.app" /Applications/
fi
echo "Built EqualEd Teacher.app (opens the teacher dashboard)."

# Third app: "EqualEd Camera" opens the camera view in its own window (separate from the teacher dashboard).
rm -rf "EqualEd Camera.app"
osacompile -o "EqualEd Camera.app" camera_app.applescript
CSET=$(mktemp -d)/c.iconset; mkdir -p "$CSET"
for s in 16 32 128 256 512; do
  sips -z $s $s assets/icon_camera_1024.png --out "$CSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) assets/icon_camera_1024.png --out "$CSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$CSET" -o "EqualEd Camera.app/Contents/Resources/applet.icns"
codesign --force --deep --sign - "EqualEd Camera.app"
if [[ "$1" == "--install" ]]; then
  rm -rf "/Applications/EqualEd Camera.app"; cp -R "EqualEd Camera.app" /Applications/
fi
echo "Built EqualEd Camera.app (camera view, separate window)."
