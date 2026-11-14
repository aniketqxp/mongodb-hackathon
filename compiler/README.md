# compiler/ (owner: David). D1: directive compiler

Text from the user becomes one contract directive (CONTRACT §3). The LLM fills only `DirectiveDraft`
(`type`, `target`, `duration_seconds`, `cap`). Code does everything else:

- checks the type against the pack's `directive_vocab`, and checks the target against the vocab (unknown values and wildcards are rejected)
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

Errors use the contract shape `{"error": {"code", "detail"}}`. Packs load from `COMPILER_PACK_DIR`
(`<pack_id>.pack.json` + `<pack_id>.vocab.json`, default `compiler/fixtures/`, synthetic data).

## Tests
`pytest compiler`. The injection tests use a stub that acts like a fully compromised LLM, so they run offline.
`test_live_llm.py` runs only when `GROQ_API_KEY` or `OPENROUTER_API_KEY` is set.
