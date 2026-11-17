#!/usr/bin/env bash
# Vectiq installer for macOS (12+) and Linux (Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE, Alpine). Safe to re-run.
# On Windows use install.ps1 in PowerShell.
#
#   ./install.sh                 interactive: asks for the bot's key, installs, starts it at login/boot
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
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

OS="$(uname -s)"
PY=""

prereqs_macos() {
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
}

prereqs_linux() {
  local sudo=""
  [[ $EUID -eq 0 ]] || { command -v sudo >/dev/null 2>&1 && sudo="sudo"; }
  local pm="" pkgs=""
  if command -v apt-get >/dev/null 2>&1; then
    pm="apt"; pkgs="git curl ca-certificates build-essential cmake pkg-config libssl-dev python3 python3-venv python3-pip"
  elif command -v dnf >/dev/null 2>&1; then
    pm="dnf"; pkgs="git curl gcc gcc-c++ make cmake pkgconf-pkg-config openssl-devel python3 python3-pip"
  elif command -v pacman >/dev/null 2>&1; then
    pm="pacman"; pkgs="git curl base-devel cmake openssl python python-pip"
  elif command -v zypper >/dev/null 2>&1; then
    pm="zypper"; pkgs="git curl gcc gcc-c++ make cmake pkg-config libopenssl-devel python3 python3-pip"
  elif command -v apk >/dev/null 2>&1; then
    pm="apk"; pkgs="git curl build-base cmake pkgconf openssl-dev python3 py3-pip"
  fi
  if [[ -n "$pm" ]]; then
    say "Installing system packages with $pm (may ask for your password)"
    case "$pm" in
      apt) $sudo apt-get update -qq && $sudo apt-get install -y -qq $pkgs ;;
      dnf) $sudo dnf install -y -q $pkgs ;;
      pacman) $sudo pacman -Sy --noconfirm --needed $pkgs ;;
      zypper) $sudo zypper --non-interactive install $pkgs ;;
      apk) $sudo apk add --no-cache $pkgs ;;
    esac || warn "couldn't install some packages; continuing in case they are already there"
  else
    warn "unknown package manager: make sure git, a C compiler, cmake, pkg-config, OpenSSL headers and Python 3.10+ are installed"
  fi
  if ! command -v cargo >/dev/null 2>&1; then
    [[ -x "$HOME/.cargo/bin/cargo" ]] || { say "Installing Rust with rustup (the Vector SDK compiles a Rust core)"
      curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal; }
    export PATH="$HOME/.cargo/bin:$PATH"
  fi
  PY="$(command -v python3)"
}

case "$OS" in
  Darwin) prereqs_macos ;;
  Linux) prereqs_linux ;;
  *) die "unsupported system: $OS (on Windows run install.ps1 in PowerShell)" ;;
esac
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10 or newer is needed (found $("$PY" -V 2>&1))"

say "Creating the virtualenv and installing Vectiq (the first build takes a few minutes)"
[[ -d .venv ]] || "$PY" -m venv .venv
set +u; source .venv/bin/activate; set -u
python -m pip install -q --upgrade pip
python -m pip install -q -e ".[webhooks,dashboard]"

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

if [[ $ASK -eq 1 ]]; then
  read -r -p "Run the setup wizard now? It asks about features, channels and verification. [Y/n] " WIZ
  [[ "$WIZ" =~ ^[Nn] ]] || python -m vectiq --setup || true
fi

say "Checking config.yaml"
python -m vectiq --check

install_service_macos() {
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
}

install_service_linux() {
  if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
    warn "no systemd user session here, so no service was installed. Start it with ./run.sh (see docs/deployment.md for other options)"
    return 1
  fi
  local dir="$HOME/.config/systemd/user"
  mkdir -p "$dir" "$ROOT/data"
  cat >"$dir/vectiq.service" <<UNIT
[Unit]
Description=Vectiq community bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/python -m vectiq
Restart=always
RestartSec=15

[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now vectiq.service
  loginctl enable-linger "$USER" 2>/dev/null || warn "couldn't enable lingering, so the bot stops when you log out (run: sudo loginctl enable-linger $USER)"
  say "Vectiq is running and starts at boot. Logs: journalctl --user -u vectiq -f"
}

if [[ $SERVICE -eq 1 ]]; then
  if [[ "$OS" == "Darwin" ]]; then install_service_macos; else install_service_linux || say "Installed. Start it with ./run.sh"; fi
else
  say "Installed. Start it with ./run.sh"
fi

cat <<'MSG'

Next steps
  1. In your Vector community, give the bot's account a role with the permissions it needs
     (Manage Roles, Manage Channels, Manage Messages, Moderate Members, Kick/Ban as you like).
  2. Edit config.yaml (modules, economy, onboarding, webhooks) and restart: ./run.sh, `launchctl kickstart -k gui/$(id -u)/com.vectiq.bot` (macOS) or `systemctl --user restart vectiq` (Linux).
  3. Type !help in any channel.
MSG
