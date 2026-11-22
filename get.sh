#!/bin/sh
# One-line install of Vectiq on macOS and Linux:
#
#   curl -fsSL https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.sh | sh
#
# It gets git if it's missing, puts Vectiq in ~/vectiq (or $VECTIQ_DIR), and runs its installer, which asks for the
# bot's key and sets everything up. Options for the installer go after "sh -s --":
#
#   curl -fsSL .../get.sh | sh -s -- --no-service     install only; start it with ~/vectiq/run.sh
#   curl -fsSL .../get.sh | VECTOR_NSEC=nsec1... sh -s -- --yes     no questions (for scripts and AI agents)
#
# Run it again to update: it pulls the latest Vectiq and re-runs the installer, keeping your config and data.
set -eu

REPO="${VECTIQ_REPO:-https://github.com/lucky-edgelord/aio-vector-bot}"
DIR="${VECTIQ_DIR:-$HOME/vectiq}"

say() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

sudo_() { if [ "$(id -u)" = 0 ]; then "$@"; elif command -v sudo >/dev/null 2>&1; then sudo "$@"; else die "need root to install $*; install git yourself and run this again"; fi; }

need_git() {
  command -v git >/dev/null 2>&1 && command -v bash >/dev/null 2>&1 && return
  say "Installing git"
  case "$(uname -s)" in
    Darwin)
      xcode-select -p >/dev/null 2>&1 || { xcode-select --install || true; die "Finish the Xcode command line tools install that just opened, then run this again."; } ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then sudo_ apt-get update -qq && sudo_ apt-get install -y -qq git bash curl
      elif command -v dnf >/dev/null 2>&1; then sudo_ dnf install -y -q git bash curl
      elif command -v pacman >/dev/null 2>&1; then sudo_ pacman -Sy --noconfirm git bash curl
      elif command -v zypper >/dev/null 2>&1; then sudo_ zypper -q install -y git bash curl
      elif command -v apk >/dev/null 2>&1; then sudo_ apk add -q git bash curl
      else die "install git with your package manager, then run this again"; fi ;;
    *) die "this is for macOS and Linux; on Windows run in PowerShell: irm https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.ps1 | iex" ;;
  esac
}

need_git
if [ -d "$DIR/.git" ]; then
  say "Updating Vectiq in $DIR"
  git -C "$DIR" pull --ff-only -q || die "couldn't update $DIR (local changes?). Fix it, or set VECTIQ_DIR to install elsewhere."
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
  die "$DIR exists and isn't a Vectiq checkout. Set VECTIQ_DIR to another folder."
else
  say "Downloading Vectiq to $DIR"
  git clone -q --depth 1 "$REPO" "$DIR"
fi

# The installer asks questions; when this script is piped into sh, answers come from the terminal, not the pipe.
if [ -r /dev/tty ] && [ -w /dev/tty ] && ( : </dev/tty ) 2>/dev/null; then
  exec bash "$DIR/install.sh" "$@" </dev/tty
fi
case " $* " in *" --yes "*|*" -y "*) exec bash "$DIR/install.sh" "$@" ;; esac
die "no terminal to ask questions on. Run: bash $DIR/install.sh   (or pass --yes with VECTOR_NSEC set)"
