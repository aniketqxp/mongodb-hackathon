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
