# ui/ (J1, Jasmine)

Plain JavaScript UI with no build step and no Node, served by a stdlib Python server that runs the J2 harness and proxies read-only core routes.

## Run

```bash
.venv/bin/uvicorn mock.app:app --port 8001   # terminal 1: mock API
python3 ui/server.py                          # terminal 2: UI on http://127.0.0.1:8080
```

Env (all optional): `API_BASE` (default `http://127.0.0.1:8001`; point at the real A3 API to switch), `UI_PORT` (8080), `DEMO_PIN` (default `1234`; a demo gate, not real auth), `HARNESS_MEMORY` (`seed`|`api`).

## What it does

| UI action | Server route | Core route(s) |
| --- | --- | --- |
| Feed for the chosen child | `GET /ui/feed` (harness) | `POST /memory/search` (api mode), `POST /decisions` per item |
| Watch / restricted probe | `POST /ui/watch` (harness gate first) | `POST /events` only if the gate admits it |
| Parent rule + PIN | `POST /ui/confirm-directive` (PIN checked server-side, sets `confirmed_by:"pin"`) | `POST /directives` |
| Un-recommend / remove a memory | `POST /ui/retract` | `POST /retract`, `GET /diff` |
| Why this? | `GET /api/why/{decision_id}` | `GET /why/{decision_id}` |
| API status chip | `GET /api/ledger` | `GET /ledger` |

Every core request carries `pack_id` and `scope_id`. The UI enforces nothing; the gate and gate > block > boost run in `harness/`.

The parent box fills the directive slots by hand until D1's compiler has a route (`OPS/BLOCKERS.md`).
