# harness/ (J2, Jasmine)

Gate evaluator, directive precedence and slate generator for the video pack. Stdlib only; talks to the core through `OPS/CONTRACT.md` routes (`client.py`).

| File | Role |
| --- | --- |
| `data.py` | Reads `data/` (catalog, pack, scopes, seed graph). Scope values for the gate come from the `scope_profile` event, falling back to `scopes.json`. |
| `gate.py` | Generic pack-gate evaluator (`eq/ne/gt/gte/lt/lte/in/not_in`, `value_from_scope`), directive expiry and target matching. Fails closed. |
| `memory.py` | Scoped memory: `ApiMemory` (`POST /memory/search`) or `SeedMemory` (seed graph, one scope only). |
| `slate.py` | Memory -> candidates -> **gate > block > boost** -> slate. Keeps previous items that still have support. |
| `service.py` | Records each slate item with `POST /decisions` (inputs = supporting memory ids), sends watch events, runs retraction. |

Rules enforced in code:
- An item that fails the gate never becomes a candidate, a decision or a memory-forming event (`watch()` does not send it; `feed()` refuses to record it).
- `suppress` removes an item even when a `prioritize` names it; `prioritize` adds at most `cap` items.
- Expired directives are ignored.

Run tests: `python3 -m unittest discover -s harness/tests -t .`

Env: `API_BASE` (core API), `HARNESS_MEMORY=seed|api` (default `seed` until the real `/memory/search` lands).

Stand-ins until the contract grows (see `OPS/BLOCKERS.md`): directives the core accepted are cached in-process because there is no route to read them back; memory comes from the seed graph while the mock search is canned.
