#!/usr/bin/env bash
# Stop Vectiq and remove its launchd agent. Your data/ folder (database, identity) and .env are kept.
LABEL="com.vectiq.bot"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Vectiq stopped and its login item removed. Delete this folder to remove everything, including data/ and .env."
