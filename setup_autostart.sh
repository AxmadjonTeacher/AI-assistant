#!/usr/bin/env bash
# Enables or disables starting Swan at Mac login

PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/com.swan.assistant.plist"

mkdir -p "$PLIST_DIR"

if [ "$1" == "disable" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "Swan autostart disabled."
    exit 0
fi

cat << PLIST > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.swan.assistant</string>
    <key>ProgramArguments</key>
    <array>
        <string>$HOME/gemini-live-assistant/.venv/bin/python</string>
        <string>$HOME/gemini-live-assistant/app.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>$HOME/gemini-live-assistant</string>
    <key>StandardOutPath</key>
    <string>$HOME/gemini-live-assistant/swan.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/gemini-live-assistant/swan.log</string>
</dict>
</plist>
PLIST

launchctl load "$PLIST_PATH"
echo "Swan is now configured to start automatically at login."
echo "To disable: ./setup_autostart.sh disable"
