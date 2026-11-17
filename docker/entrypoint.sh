#!/bin/sh
# First start: drop the commented example config into the (empty) /config volume so it can be edited.
if [ ! -f "$VECTIQ_CONFIG" ]; then
  cp /opt/vectiq/config.example.yaml "$VECTIQ_CONFIG"
  echo "vectiq: created $VECTIQ_CONFIG from the example. Edit it, or run the setup wizard (see docs/docker.md)."
fi
exec "$@"
