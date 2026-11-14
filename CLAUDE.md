# CLAUDE.md: rules for every Claude Code session in this repo

Project: governed-memory core on MongoDB Atlas (track: Memory You Can Govern).
Hackathon deadline: Sat 14 Nov 2026, 5:00 PM ET. Feature freeze 4:15 PM.

## Read first
1. `OPS/CONTRACT.md`: single source of truth for collections, routes, schemas.
2. `OPS/OWNERS.md`: who owns which directory and package.
3. `OPS/STATUS.md` and `OPS/BLOCKERS.md`: current state and what is blocked.

## Hard rules
1. **The core has no domain words.** Nothing in `core/` may mention videos, children, parents, slates, maturity, etc. Domain meaning lives only in pack data. `scripts/precommit_check.sh` greps for this.
2. **The LLM never enforces.** The LLM only fills typed slots (directives, packs). Code validates, a human confirms, and code enforces the gate, planner and expiry.
3. **Python is the spine.** Rust and JavaScript talk to it through the contract only.
4. **Secrets live in env vars only.** Never commit `.env`. Keep `.env.example` with empty values. If a key is pushed, say so in `OPS/BLOCKERS.md` and rotate it.
5. **Synthetic data only.** No real people, no real children's data.
6. **Respect the banned-project list** from the participant guide: no Streamlit, no basic RAG, no dashboard as the main feature, no sports analyzers or coaches.
7. **Edit only your own directories** (see `OPS/OWNERS.md`). Need a change elsewhere? Add a line to `OPS/BLOCKERS.md` or ask the owner.
8. **Contract changes** go through Greatness (OPS owner): edit `OPS/CONTRACT.md` in a small PR, bump its version line, announce in the team chat.
9. **Never force-push `main`.** Work on a branch, open a PR, one teammate glances at it.

## Git conventions
- Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`. Scope optional, e.g. `feat(core): add support check`.
- Branch names: `<type>/<package>-<short-name>`, e.g. `feat/a2-planner`.
- Small commits. Run `/precommit-check` before committing.

## Working agreement
- Build against the contract. Use the mock API (`mock/`) until the real one lands.
- Blocked? Append to `OPS/BLOCKERS.md`, then move to your next task. Do not wait.
- At each milestone: update your line in `OPS/STATUS.md`, then run `/handoff`.
- Keep prompts to the LLM short. Free-tier token budgets are small; cache validated outputs.
- Get the LLM through `get_llm()` (env: `LLM_PROVIDER`, `LLM_MODEL`, keys). Never hard-code a provider.
