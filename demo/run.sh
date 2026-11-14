#!/usr/bin/env bash
# Run the live split-screen demo (one process, real core on Atlas) on :8090.
#
#   demo/run.sh            start on http://localhost:8090 (split) and /film (animation)
#   demo/run.sh --reseed   first reset the demo pack's data, then start
#   PORT=9000 demo/run.sh  another port
#
# Needs: .venv (Python 3.10+) with demo/requirements.txt, and a .env at the repo root with at least
# MONGODB_URI (Atlas user with collMod/createSearchIndex rights) and GROQ_API_KEY. VOYAGE_API_KEY is optional
# (without it the core falls back to keyword search). An env file outside the repo also works:
#   CORE_ENV_FILE=/path/to/secrets.env demo/run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY="$ROOT/.venv/Scripts/python.exe"
PORT="${PORT:-8090}"

die() { printf '\033[31mx %s\033[0m\n' "$*" >&2; exit 1; }
[ -x "$PY" ] || die "No .venv. Run: python3.12 -m venv .venv && .venv/bin/pip install -r demo/requirements.txt"
"$PY" -c 'import fastapi, uvicorn, httpx, pymongo, dotenv' 2>/dev/null || die "Missing packages. Run: .venv/bin/pip install -r demo/requirements.txt"
[ -f .env ] || [ -n "${CORE_ENV_FILE:-}" ] || die "No .env. Run: cp .env.example .env and fill MONGODB_URI and GROQ_API_KEY (or set CORE_ENV_FILE)"

export RETRACTION_POLICY="${RETRACTION_POLICY:-provenance}"

if [ "${1:-}" = "--reseed" ]; then
  "$PY" -c 'from core.demo import reseed; reseed(); print("reseeded")'
fi

printf '\033[1mSplit demo: http://localhost:%s   Film: http://localhost:%s/film\033[0m\n' "$PORT" "$PORT"
exec "$PY" -m uvicorn demo.split:app --host 127.0.0.1 --port "$PORT"
