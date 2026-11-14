# KICKOFF: how to start (everyone)

1. `git clone https://github.com/aniketqxp/mongodb-hackathon && cd mongodb-hackathon`
2. `cp .env.example .env` and fill in keys (ask Greatness/Aniket). Never commit `.env`.
3. `python -m venv .venv && source .venv/bin/activate` (Python work) and `pip install -r mock/requirements.txt`
4. Run the mock API: `uvicorn mock.app:app --port 8001`
5. Open Claude Code in the repo and paste your kickoff prompt below.
6. Branch, commit (Conventional Commits), `/precommit-check`, push, open a PR. One teammate glances, then merge.

## Kickoff prompt (replace <ID> and <name>)

```
You are working on package <ID> as <name>. Read CLAUDE.md, OPS/CONTRACT.md and OPS/OWNERS.md first. Edit only your own directories. Build against the contract, using the mock API until the real one lands. If blocked, append to OPS/BLOCKERS.md and move to your next task. At each milestone, update OPS/STATUS.md and run /handoff.
```

## Per-person first tasks
- **Aniket (A1, A2):** Atlas collections and indexes per CONTRACT section 1, then provenance graph, support check, planner and fixtures in `core/`.
- **Greatness (G1, G2):** merge this bundle, then 200-video catalog, taxonomy, scripted curves and seed loader in `data/`.
- **David (D1, D2, D3):** draft the 25 eval prompts and the directive/pack JSON schemas in `compiler/` against CONTRACT sections 2 and 3; use `shared/llm.py`.
- **Jasmine (J1, J2, J3):** wireframe the typed UI in `ui/` against the mock API; gate evaluator and slate generator in `harness/` once the catalog lands.
