#!/bin/sh
# Fit, emit paper orders, check the Python fill matches Aura, print the
# portfolio gap. Does not log in to FXCM.
set -eu
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
mkdir -p out
aura run --quiet
aura run advantage.aura --quiet
aura run hot.aura --quiet
python3 bridge/fc_adapter.py probe
python3 bridge/fc_adapter.py paper --session out/session.json
