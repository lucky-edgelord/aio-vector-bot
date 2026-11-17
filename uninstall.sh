#!/usr/bin/env bash
# Stop Vectiq and remove its login item / service (macOS launchd or Linux systemd user unit).
# Your data/ folder (database, identity) and .env are kept.
case "$(uname -s)" in
  Darwin)
    LABEL="com.vectiq.bot"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/$LABEL.plist" ;;
  Linux)
    systemctl --user disable --now vectiq.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/vectiq.service"
    systemctl --user daemon-reload 2>/dev/null || true ;;
esac
echo "Vectiq stopped and its service removed. Delete this folder to remove everything, including data/ and .env."
