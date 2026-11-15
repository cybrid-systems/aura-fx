#!/bin/sh
# P1 walk-forward + race + gates on several seeds (no commit). Prints one
# line per seed and how many seeds each search passed the gate on.
set -eu
cd "$(dirname "$0")/.."
# Use the aura on PATH if there is one (e.g. a self-built main), else the nightly install.
command -v aura >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"
mkdir -p out
aura run p1-seeds.aura --quiet | tee out/log-p1-seeds.txt
grep -q '^P1S_OK$' out/log-p1-seeds.txt
