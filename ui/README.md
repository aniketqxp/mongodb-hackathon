# ui/ (J1, Jasmine)

Plain JavaScript UI with no build step and no Node, served by a stdlib Python server that runs the J2 harness and proxies read-only core routes.

## Run (one command)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r mock/requirements.txt -r compiler/requirements.txt   # once
cp .env.example .env    # once; set DIRECTIVE_PIN (the parent PIN) and GROQ_API_KEY
ui/run_demo.sh          # mock :8001 + compiler :8002 + UI :8080, opens the browser; Ctrl+C stops all
```

`--restart` stops anything already on those ports first; `--no-open` skips the browser. Logs go to `.demo-logs/`. The script loads `.env`, needs Python 3.10+, and fills empty `COMPILER_DATA_DIR`/`CORE_API_URL` with working defaults. Set `API_BASE` in `.env` to the real core API to skip the mock.

Env (all optional): `API_BASE` (core API, default the mock on :8001), `COMPILER_URL` (default :8002), `UI_PORT` (8080), `HARNESS_MEMORY` (`seed`|`api`), `HARNESS_DIRECTIVES` (`local`|`api`). `DIRECTIVE_PIN` must be set for both the compiler and the UI server (`run_demo.sh` loads it from `.env`).

## What it does

| UI action | Server route | Core route(s) |
| --- | --- | --- |
| Feed for the chosen child | `GET /ui/feed` (harness) | `POST /memory/search` (api mode), `POST /decisions` per item |
| Watch / restricted probe | `POST /ui/watch` (harness gate first) | `POST /events` only if the gate admits it |
| Parse parent sentence | `POST /ui/compile` | compiler `POST /directives/compile` (:8002) |
| Save rule | `POST /ui/confirm-directive` (adds `DIRECTIVE_PIN` from the server env) | compiler `POST /directives/confirm` (checks the PIN, then core `POST /directives`) |
| Un-recommend / remove a memory | `POST /ui/retract` | `POST /retract`, `GET /diff` |
| Why this? | `GET /api/why/{decision_id}` | `GET /why/{decision_id}` |
| API status chip | `GET /api/ledger` | `GET /ledger` |

Every core request carries `pack_id` and `scope_id`. The UI enforces nothing; the gate and gate > block > boost run in `harness/`.

The parent box sends the sentence to D1's compiler, which fills the typed slots; the parent can edit them before confirming. If the compiler is down or rejects the sentence, the slots stay manual and the same validation and PIN check apply on confirm. The UI is parent-only, so there is no PIN field: the parent's "Save rule" click is the confirmation, and `ui/server.py` passes `DIRECTIVE_PIN` from its own env to the compiler. The PIN never reaches the browser, and this server never sets `confirmed_by` or posts to the core's `/directives` itself (CONTRACT section 8).
