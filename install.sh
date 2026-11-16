#!/usr/bin/env bash
# Vectiq installer for a Mac mini (Apple silicon, macOS 12+). Safe to re-run.
#
#   ./install.sh                 interactive: asks for the bot's key, installs, starts it at login
#   ./install.sh --no-service    install only; start it yourself with ./run.sh
#   ./install.sh --yes           no prompts (reads VECTOR_NSEC / VECTIQ_INVITE_URLS from the environment)
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
SERVICE=1
ASK=1
for a in "$@"; do
  case "$a" in
    --no-service) SERVICE=0 ;;
    --yes|-y) ASK=0 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "this installer is for macOS (on Linux: python -m venv .venv && .venv/bin/pip install -e . )"

if ! xcode-select -p >/dev/null 2>&1; then
  say "Installing the Xcode command line tools (a dialog will open; re-run this script when it finishes)"
  xcode-select --install || true
  exit 0
fi

if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [[ -x "$b" ]] && eval "$("$b" shellenv)" && break; done
fi
if ! command -v brew >/dev/null 2>&1; then
  say "Installing Homebrew"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

say "Installing Python, Rust and cmake with Homebrew (the Vector SDK compiles a Rust core)"
brew install python@3.12 rust cmake pkg-config openssl@3 >/dev/null
PY="$(brew --prefix python@3.12)/bin/python3.12"
[[ -x "$PY" ]] || PY="$(command -v python3)"

say "Creating the virtualenv and installing Vectiq (the first build takes a few minutes)"
[[ -d .venv ]] || "$PY" -m venv .venv
set +u; source .venv/bin/activate; set -u
python -m pip install -q --upgrade pip
python -m pip install -q -e ".[webhooks]"

set_env() { # set_env KEY VALUE: replace or append in .env
  local k="$1" v="$2"
  if grep -q "^$k=" .env 2>/dev/null; then
    python - "$k" "$v" <<'PY'
import sys, re
k, v = sys.argv[1:3]
s = open(".env").read()
open(".env", "w").write(re.sub(rf"(?m)^{re.escape(k)}=.*$", lambda m: f"{k}={v}", s))
PY
  else
    echo "$k=$v" >> .env
  fi
}
[[ -f .env ]] || { cp .env.example .env; chmod 600 .env; }
NSEC="${VECTOR_NSEC:-}"
INVITES="${VECTIQ_INVITE_URLS:-}"
if [[ $ASK -eq 1 ]]; then
  if ! grep -Eq '^VECTOR_NSEC=nsec1[0-9a-z]{20,}' .env && [[ -z "$NSEC" ]]; then
    read -r -p "The bot's Vector key (nsec1..., blank to generate a new one): " NSEC
  fi
  if ! grep -Eq '^VECTIQ_INVITE_URLS=.{10,}' .env && [[ -z "$INVITES" ]]; then
    read -r -p "Community invite link(s) to join, space-separated (blank to skip): " INVITES
  fi
fi
if ! grep -Eq '^VECTOR_NSEC=nsec1[0-9a-z]{20,}' .env && [[ -z "$NSEC" ]]; then
  NSEC="$(python -c 'import vector; print(vector.generate_nsec())')"
  say "Generated a new Vector identity (saved in .env; back it up, it is the bot's account)"
fi
[[ -n "$NSEC" ]] && set_env VECTOR_NSEC "$NSEC"
[[ -n "$INVITES" ]] && set_env VECTIQ_INVITE_URLS "$INVITES"
chmod 600 .env

say "Checking config.yaml"
python -m vectiq --check

if [[ $SERVICE -eq 1 ]]; then
  LABEL="com.vectiq.bot"
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data"
  cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/.venv/bin/python</string><string>-m</string><string>vectiq</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$ROOT/data/vectiq.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/vectiq.log</string>
</dict></plist>
PLIST
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  say "Vectiq is running and will start at login. Logs: $ROOT/data/vectiq.log"
else
  say "Installed. Start it with ./run.sh"
fi

cat <<'MSG'

Next steps
  1. In your Vector community, give the bot's account a role with the permissions it needs
     (Manage Roles, Manage Channels, Manage Messages, Moderate Members, Kick/Ban as you like).
  2. Edit config.yaml (modules, economy, onboarding, webhooks) and restart: ./run.sh or `launchctl kickstart -k gui/$(id -u)/com.vectiq.bot`.
  3. Type !help in any channel.
MSG
