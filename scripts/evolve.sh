#!/bin/sh
# P1-P5: walk-forward evolution with gates, risk invariants, parallel
# candidates + online selection, live loop with heal, offline LLM proposals.
# Runs on seeded fixture tapes; does not log in to FXCM and sends no orders.
# P5 runs only when MINIMAX_API_KEY is set (the key is never printed).
set -eu
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
mkdir -p out

# Run a command and print wall time, CPU time, effective cores and the peak
# RSS of its child processes.
meter() {
  name="$1"; shift
  python3 - "$name" "$@" <<'PY'
import resource, subprocess, sys, time
name, cmd = sys.argv[1], sys.argv[2:]
t0 = time.time()
p = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
rc = p.returncode
sys.stdout.write(p.stdout)
open(f"out/log-{name}.txt", "w").write(p.stdout)
wall = time.time() - t0
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
cpu = ru.ru_utime + ru.ru_stime
print(f"METER {name} rc={rc} wall={wall:.1f}s cpu={cpu:.1f}s cores={cpu / max(wall, 1e-9):.2f} peak_rss={ru.ru_maxrss / 1024:.0f}MB")
sys.exit(rc)
PY
}

# Fail unless the phase printed its OK marker.
ok() { grep -q "^$2\$" "out/log-$1.txt" || { echo "$1 did not print $2"; exit 1; }; }

echo "host: $(nproc) cores, $(awk '/MemTotal/ {printf "%.1f GB", $2/1048576}' /proc/meminfo)"

# P1 twice: the same seed must give the same report.
meter p1 aura run p1-evolve.aura --quiet
cp out/p1.json out/p1-first.json
meter p1-again aura run p1-evolve.aura --quiet
ok p1-again P1_OK
cmp -s out/p1.json out/p1-first.json || { echo "P1 not deterministic"; exit 1; }
echo "P1_DETERMINISTIC"

meter p2 aura run p2-risk.aura --quiet
ok p2 P2_OK
# The adapter's own risk check must refuse the adversarial sessions (rc 3).
for s in out/p2-oversize-session.json out/p2-flip-session.json; do
  set +e
  python3 bridge/fc_adapter.py paper --session "$s" >/dev/null
  rc=$?
  set -e
  [ "$rc" -eq 3 ] || { echo "adapter did not block $s (rc $rc)"; exit 1; }
  echo "ADAPTER_BLOCKED $s"
done

meter p3 aura run p3-adapt.aura --quiet
ok p3 P3_OK
meter p4 aura run p4-live.aura --quiet
ok p4 P4_OK
python3 bridge/fc_adapter.py paper --session out/live-session.json
python3 bridge/fc_adapter.py live --offline --session out/live-session.json

if [ -n "${MINIMAX_API_KEY:-}" ]; then
  LLM_API_KEY="$MINIMAX_API_KEY" \
  LLM_BASE_URL="${LLM_BASE_URL:-https://api.minimaxi.com/v1}" \
  LLM_MODEL="${LLM_MODEL:-MiniMax-M3.1-Flash}" \
    meter p5 aura run p5-llm.aura --grant net --quiet
  ok p5 P5_OK
else
  echo "P5_SKIPPED (no MINIMAX_API_KEY)"
fi

echo "EVOLVE_OK"
