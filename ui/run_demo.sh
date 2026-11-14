#!/usr/bin/env bash
# One command to run the demo locally: mock core API (:8001), directive compiler (:8002), UI (:8080).
#
#   ui/run_demo.sh             start all three, open the browser, Ctrl+C stops everything
#   ui/run_demo.sh --restart   first stop whatever is already listening on those ports
#   ui/run_demo.sh --no-open   do not open the browser
#
# Needs: .venv on Python 3.10+ with mock/ and compiler/ requirements, and a .env (copy .env.example).
# Set API_BASE in .env to point the UI at the real core API instead of the mock (the mock is then skipped).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
LOGS="$ROOT/.demo-logs"
RESTART=0
OPEN=1
for arg in "$@"; do
  case "$arg" in
    --restart) RESTART=1 ;;
    --no-open) OPEN=0 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[31mx %s\033[0m\n' "$*" >&2; exit 1; }

# ---------- checks ----------
[ -x "$PY" ] || die "No .venv. Run: python3.12 -m venv .venv && .venv/bin/pip install -r mock/requirements.txt -r compiler/requirements.txt"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die ".venv is $("$PY" -V); it needs Python 3.10+ (rebuild it with python3.12)"
"$PY" -c 'import fastapi, uvicorn, pydantic, httpx' 2>/dev/null || die "Missing packages. Run: .venv/bin/pip install -r mock/requirements.txt -r compiler/requirements.txt"
[ -f .env ] || die "No .env. Run: cp .env.example .env  (then fill in DIRECTIVE_PIN and keys)"

set -a; . ./.env; set +a
# Empty values in .env would override the services' defaults; fill the ones that need a value.
: "${COMPILER_DATA_DIR:=$ROOT/data}"
: "${CORE_API_URL:=http://localhost:8001}"
: "${API_BASE:=$CORE_API_URL}"
export COMPILER_DATA_DIR CORE_API_URL API_BASE
[ -n "${DIRECTIVE_PIN:-}" ] || die "DIRECTIVE_PIN is empty in .env; the compiler would reject every PIN"
export DEMO_PIN="${DEMO_PIN:-$DIRECTIVE_PIN}"   # UI fallback PIN matches the compiler's
[ -n "${GROQ_API_KEY:-}${OPENROUTER_API_KEY:-}" ] || warn "No GROQ_API_KEY/OPENROUTER_API_KEY: sentence parsing will fail; use the manual slots"

USE_MOCK=0
case "$API_BASE" in http://localhost:8001*|http://127.0.0.1:8001*) USE_MOCK=1 ;; esac

PORTS="8002 8080"; [ $USE_MOCK = 1 ] && PORTS="8001 $PORTS"
for p in $PORTS; do
  pid=$(lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null || true)
  [ -z "$pid" ] && continue
  if [ $RESTART = 1 ]; then
    warn "stopping process on :$p (pid $pid)"; kill $pid 2>/dev/null || true; sleep 1
  else
    die "Port $p is already in use (pid $pid). Re-run with --restart to stop it."
  fi
done

# ---------- start ----------
mkdir -p "$LOGS"
PIDS=()
cleanup() {
  trap - INT TERM EXIT
  echo; say "Stopping demo services…"
  for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

start() { # name, log, command...
  local name=$1 log=$2; shift 2
  "$@" > "$LOGS/$log" 2>&1 &
  PIDS+=($!)
  echo "  started $name (pid $!), log: .demo-logs/$log"
}

say "Starting demo services"
[ $USE_MOCK = 1 ] && start "mock core API :8001" mock.log "$PY" -m uvicorn mock.app:app --port 8001
start "directive compiler :8002" compiler.log "$PY" -m uvicorn compiler.app:app --port 8002
start "UI + harness :8080" ui.log "$PY" ui/server.py

wait_up() { # name, url
  for _ in $(seq 1 30); do
    curl -s -o /dev/null "$2" && { echo "  ok  $1"; return 0; }
    sleep 0.5
  done
  die "$1 did not start; see .demo-logs/"
}
[ $USE_MOCK = 1 ] && wait_up "mock core API" "http://127.0.0.1:8001/ledger"
wait_up "directive compiler" "http://127.0.0.1:8002/docs"
wait_up "UI" "http://127.0.0.1:8080/ui/config"

echo
say "Demo is running → http://127.0.0.1:8080   (parent PIN: from DIRECTIVE_PIN in .env)"
echo "  core API: $API_BASE$([ $USE_MOCK = 1 ] && echo ' (mock)')"
echo "  Press Ctrl+C to stop everything."
[ $OPEN = 1 ] && command -v open >/dev/null && open "http://127.0.0.1:8080"

wait
