#!/bin/zsh
# Builds a tiny Mac app around the demo. macOS only gives camera and microphone
# access to apps, not to scripts run from Terminal, so this wrapper is needed.
set -e
cd "$(dirname "$0")"
PYHOME=$(.venv/bin/python -c "import sys; print(sys.base_prefix)")
INC=$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['include'])")
APP="EqualEd.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>EqualEd</string>
  <key>CFBundleIdentifier</key><string>org.equaled.demo</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>NSCameraUsageDescription</key><string>Watches the classroom for sensory triggers and the student's reactions.</string>
  <key>NSMicrophoneUsageDescription</key><string>Hears sudden loud sounds and transcribes the lecture. Audio never leaves this Mac.</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
clang -O2 -DPYHOME="\"$PYHOME\"" -I"$INC" -L"$PYHOME/lib" -lpython3.11 -Wl,-rpath,"$PYHOME/lib" \
  -o "$APP/Contents/MacOS/launcher" launcher.c
codesign --force --sign - "$APP"
echo "Built $APP. Double-click it and click Allow for the camera and microphone."
