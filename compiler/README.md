# compiler/ (owner: David). D1: directive compiler

Text from the user becomes one contract directive (CONTRACT §3). The LLM fills only `DirectiveDraft`
(`type`, `target`, `duration_seconds`, `cap`). Code does everything else:

- checks the type against the pack's `directive_vocab`, and checks the target against the vocab (unknown values and wildcards are rejected)
- rejects any target on a gate or scope field (`maturity`, `max_maturity`, the scope field), even if it is in the vocab. The maturity ceiling comes from each scope's `scope_profile` event, and gate beats suppress beats prioritize
- for retract, checks the id against the scope's own nodes and shows the LLM those ids with their text
- bounds `cap` (1 to 10) and duration (1 minute to 365 days), then computes `expires_at` (suppress requires it)
- sets `source_text` to the real input and `confirmed_by` to `null`, always
- `PinGate` sets `confirmed_by` only after a server-side PIN check: env `DIRECTIVE_PIN` / `BUILDER_PIN`. It fails closed if unset and locks the scope for 5 min after 3 misses
- `submit_directive` refuses unconfirmed directives with no network call, re-validates, then POSTs to core `/directives`

## Use
```python
from compiler.directive import compile_directive, describe, PinGate, submit_directive
d = compile_directive("no scary stuff for a week", pack, vocab)   # unconfirmed
card = describe(d, pack)                                           # text for the PIN card
d = PinGate().confirm(d, pin, scope_id)
submit_directive(d, pack, scope_id, vocab)                         # CORE_API_URL, default :8001 (mock)
```

## Service for the UI (port 8002)
`uvicorn compiler.app:app --port 8002`
- `POST /directives/compile` `{pack_id, scope_id, text}` → `{directive, summary}`
- `POST /directives/confirm` `{pack_id, scope_id, directive, pin}` → core `/directives` response

Errors use the contract shape `{"error": {"code", "detail"}}`.

## Data (`compiler/packs.py`, reads G2's `data/`, override with `COMPILER_DATA_DIR`)
- pack: `data/pack_*.json` with a matching `pack_id` (demo: `pack_video_demo`)
- target vocab: `topic` (from `taxonomy.json` topics) and `tag` (all catalog tags). The planner applies `{kind:"topic"}` as `item.topic == value` and `{kind:"tag"}` as `value in item.tags`
- scopes come from `scopes.json` and `scope_profile` events. An unknown scope returns `not_found`
- retractable ids are the scope's active nodes in `graph.json` (swap for core reads once A3 lands)

## Tests
`pytest` from the repo root runs `compiler/tests` plus `eval/tests`. The 25-prompt dataset is `eval/directive_prompts.json`: 18 expected drafts across the 3 types and 7 adversarial prompts, each with the hostile draft that code must reject. The injection tests use a stub that acts like a fully compromised LLM, so they run offline.
`test_live_llm.py` runs only when `GROQ_API_KEY` or `OPENROUTER_API_KEY` is set.

---

# D2: pack compiler and conformance suite

## Pack compiler (`compiler/pack.py`)
A builder sentence becomes a data-only pack (CONTRACT §2). The LLM fills `PackDraft`. Code then:
- builds `pack_id` (`pack_<slug>`), slugifies names and dedupes `directive_vocab`
- validates the schema (extra or missing fields are rejected) and referential rules: edges name declared types, at least one edge reaches `decision`, gate ops fit their values, exactly one of `value` / `value_from_scope`, no reserved fields, the gate is satisfiable, and decay values are sane
- **fallback:** an exact cached sentence is served with no LLM call. If the LLM fails, its output is invalid, or the budget (`PACK_LLM_MAX_CALLS`, default 20 per process) is spent, the closest cached validated pack is served, preferring packs that passed 5/5. The result always says `source: llm | cache | fallback` plus a `reason`
- the cache is `compiler/pack_cache/` (`PACK_CACHE_DIR`), plus `data/pack_*.json`. It is seeded with the hand-written `pack_team_notes` (a second domain for the floor tier). Only validated packs are written; corrupt files are skipped

## Conformance suite (`compiler/conformance.py`)
Five domain-neutral checks over the contract HTTP routes only. It builds its own items from the pack's gate (`compiler/gate.py`) in fresh scopes `conf_<run>_<x>`.
```
python -m compiler.conformance --pack data/pack_video.json --core http://localhost:8001
```
Returns the contract shape `{passed, total: 5, checks: [{id, name, passed, detail}]}`. For core (A3): `POST /packs/{id}/conformance` can call `run_conformance(pack, Core(<own base url>))`.

`compiler/tests/fake_core.py` is a correct in-memory reference core. Its `broken` flags (`lazy_retract`, `greedy_retract`, `leaky_search`, `no_expiry`, `no_gate`) each fail exactly their matching check, for both packs. Against the canned mock the suite reports 1/5, as it should.
