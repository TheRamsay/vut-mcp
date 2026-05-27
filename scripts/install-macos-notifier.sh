#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_APP="$ROOT/build/VUT Studis Notifier.app"
TARGET_DIR="$HOME/Applications"
TARGET_APP="$TARGET_DIR/VUT Studis Notifier.app"

if [[ ! -d "$SOURCE_APP" ]]; then
  "$ROOT/scripts/build-macos-notifier.sh" >/dev/null
fi

mkdir -p "$TARGET_DIR"
rsync -a --delete "$SOURCE_APP" "$TARGET_DIR/"

/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$TARGET_APP"

echo "$TARGET_APP"
