#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/build/VUT Studis Notifier.app"
EXECUTABLE="$APP/Contents/MacOS/VUT Studis Notifier"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc \
  "$ROOT/notifier/macos/VUTStudisNotifier.swift" \
  -o "$EXECUTABLE" \
  -framework AppKit \
  -framework Foundation \
  -framework UserNotifications

cp "$ROOT/notifier/macos/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/raycast-extension/assets/extension-icon.png" \
  "$APP/Contents/Resources/extension-icon.png"

codesign --force --deep --sign - "$APP" >/dev/null
touch "$APP"
echo "$APP"
