#!/usr/bin/env bash
# Run Vectiq in the foreground (Ctrl-C stops it). Extra arguments go to vectiq, e.g. ./run.sh --check
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -m vectiq "$@"
