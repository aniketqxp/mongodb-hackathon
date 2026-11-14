# demo/: live split-screen demo and 1-minute film (Aniket)

Two things live here.

| Route | What it is | Data |
| --- | --- | --- |
| `/` | **Live split screen.** Left: Jasmine's feed UI (`ui/static`, served unmodified at `/left/`). Right: what the memory and feed did after each action. | Real: core (`core/api.py`) on Atlas, harness (`harness/`), compiler (`compiler/`), all in one process |
| `/film` | **Animated explainer**, about 1 min, self-playing at 1280×720. `R` or Space replays, `L` jumps to the live demo. | Real, offline: `demo/film_data.py` replays the team's slate generator (`harness.slate`) and planner (`core.planner`) on `data/` (no database, no LLM). Titles, watch counts, which videos are removed, which one is kept for independent support, the recalled/preserved decisions and the "stays forgotten" ticks are all computed |

`film.html` also opens directly from disk with the committed `film_data.js`. When served at `/film` it loads fresh data from `/film_data.js`. After changing `data/`, the planner or the slate code, run `python -m demo.film_data` to refresh the snapshot (a test fails if it is stale).

## Run it on the recording laptop

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r demo/requirements.txt
cp .env.example .env     # fill MONGODB_URI and GROQ_API_KEY; VOYAGE_API_KEY optional
demo/run.sh --reseed     # fresh demo data, then http://localhost:8090
```

Secrets stay in `.env` (git-ignored) or in a file outside the repo passed as `CORE_ENV_FILE=/path/to/file`. See
`OPS/DEMO_KEYS.md` for which values the demo laptop uses. The Atlas user needs the rights the core uses at startup
(`collMod`, search index creation). The laptop's IP must be in Atlas Network Access.

## What to do on screen

1. Open `http://localhost:8090`. The feed loads for one child scope.
2. Click **Why this?** on a video: the right panel shows the memory that put it there.
3. Type a parent sentence, e.g. *"No more spooky stuff, she gets nightmares"*, then **Save rule**. The LLM fills a typed
   directive; code validates it; the core retracts the memory's evidence and replays the decisions that depended on it.
4. Reload or watch more: the retracted memory does not come back.

`POST /demo/reset` restores the seed for this pack only and drops this pack's parent rules.

## Demo simplifications

- The parent PIN is dropped. The UI is parent-only, so the **Save rule** click is the confirmation
  (`confirmed_by: "pin"`, set server-side, never by the browser).
- `RETRACTION_POLICY` defaults to `provenance`. The naive `label_only` failure is never scripted; it only shows up if
  you run the core with that policy (see `core/fixtures/runs/conformance_log.txt`).

## Files

- `split.py`, `split.html`: the live split demo (current).
- `film.html`: the animation.
- `server.py`, `index.html`: an earlier single-page version (keyword fallback when the LLM is down). Kept as a backup:
  `python -m uvicorn demo.server:app --port 8090`.
- `run.sh`, `requirements.txt`: setup.
