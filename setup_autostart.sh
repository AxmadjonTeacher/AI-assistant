#!/usr/bin/env bash
# Enables or disables starting Swan at Mac login

PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/com.axmadjon.swan.plist"

mkdir -p "$PLIST_DIR"

if [ "$1" == "disable" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    osascript -e 'tell application "System Events" to delete (every login item whose name is "Swan")' 2>/dev/null || true
    echo "Swan autostart disabled."
    exit 0
fi

cat << PLIST > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.axmadjon.swan</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>/Applications/Swan.app</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH" 2>/dev/null || true
osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Swan.app", name:"Swan", hidden:false}' 2>/dev/null || true

echo "Swan is now configured to start automatically in the background at login."
echo "To disable: ./setup_autostart.sh disable"
