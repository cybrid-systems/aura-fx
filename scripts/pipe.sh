#!/bin/sh
# Fit, emit paper orders, check the Python fill matches Aura, print the
# portfolio gap. Does not log in to FXCM.
set -eu
cd "$(dirname "$0")/.."
# Use the aura on PATH if there is one (e.g. a self-built main), else the nightly install.
command -v aura >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"
mkdir -p out
aura run --quiet
aura run advantage.aura --quiet
aura run hot.aura --quiet
python3 bridge/fc_adapter.py probe
python3 bridge/fc_adapter.py paper --session out/session.json
