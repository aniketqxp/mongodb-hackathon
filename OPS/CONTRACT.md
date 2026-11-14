# CONTRACT v0.2 (changes via PR from Greatness)

Version: 0.2.1
Changes in 0.2.1: the audit collection is named `history` (matches the Atlas sandbox); the API keeps `GET /ledger` and the `ledger` field in `/why` responses.
Changes since 0.1: scope profile, target vocabulary, GET /directives, compiler routes (port 8002), directive trust header, 422 for not_confirmed.
All bodies are JSON. IDs are strings. Timestamps are ISO 8601 UTC. Every request carries `pack_id` and `scope_id`.
The core has no domain words: domain meaning lives only in pack data.

## 1. Collections (MongoDB Atlas)

| Collection | Key fields | Indexes |
| --- | --- | --- |
| `events` | `pack_id`, `scope_id`, `type`, `payload`, `ts`, `source` | `(pack_id, scope_id, ts)` |
| `nodes` | `pack_id`, `scope_id`, `kind`, `text`, `embedding`, `status`, `expires_at`, `support[]` | Vector Search on `embedding` (filter: `pack_id`, `scope_id`); TTL on `expires_at` |
| `edges` | `pack_id`, `scope_id`, `from`, `to`, `rel` | `from`, `to` |
| `decisions` | `pack_id`, `scope_id`, `inputs[]`, `output`, `status`, `replay_of`, `ts` | `(scope_id, ts)` |
| `directives` | `pack_id`, `scope_id`, `type`, `target`, `expires_at`, `cap`, `confirmed_by`, `status` | `(scope_id, type)`; TTL on `expires_at` |
| `history` | `actor`, `action`, `target`, `before`, `after`, `ts`, `pack_id`, `scope_id` | `(scope_id, ts)` |
| `packs` | `pack_id`, `slots`, `status` (`draft`/`active`), `conformance` | `pack_id` unique |

The `history` collection is the audit log; it backs `GET /ledger` and the `ledger` field of `GET /why`. Route and field names do not change.

Node `status`: `active` | `quarantined` | `invalidated` | `expired`. Decision `status`: `active` | `invalidated` | `replayed`.
Embeddings: Voyage `voyage-4-lite`. Every query filters on `pack_id` and `scope_id`.

## 2. Pack schema (data only, 8 slots)

```json
{
  "pack_id": "string",
  "scope_field": "string",
  "node_types": ["string"],
  "edge_types": [{"rel": "string", "from": "node_type", "to": "node_type|decision"}],
  "gate": [{"field": "string", "op": "eq|ne|gt|gte|lt|lte|in|not_in", "value": "any", "value_from_scope": "string|null"}],
  "decay": {"kind": "none|ttl|linear", "seconds": 0},
  "directive_vocab": ["suppress", "prioritize", "retract"],
  "labels": {"item": "string", "scope": "string", "directive": "string"}
}
```
A pack activates only when conformance returns 5/5 (see section 5).

**Scope profile.** A scope's attributes live in an event: `{type:"scope_profile", payload:{...attrs}}` (latest wins). A gate rule's `value_from_scope` names a key in that payload (video pack: `max_maturity`). Gate and scope fields can never be targeted by a directive: only the scope profile changes them.

**Target vocabulary** (what a directive `target.kind` may be) is pack data in `data/taxonomy.json` plus catalog tags, not a pack slot. Video pack kinds: `topic` (matches `item.topic == value`) and `tag` (matches `value in item.tags`). `retract` targets a node id in the same scope.

## 3. Directive schema (three primitives)

```json
{
  "type": "suppress|prioritize|retract",
  "target": {"kind": "string", "value": "string"},
  "expires_at": "ISO8601|null",
  "cap": 0,
  "confirmed_by": "pin|builder|null",
  "source_text": "string"
}
```
- `suppress` requires `expires_at`. `prioritize` requires `cap` (max boosted items per slate). `retract` targets one node or directive id.
- Precedence when they collide: **gate > block (suppress) > boost (prioritize)**.
- A directive is stored only after `confirmed_by` is set. Validation rejects extra fields, missing fields, unknown targets.

## 4. Routes

| Route | Body in | Body out |
| --- | --- | --- |
| `POST /packs` | `{pack}` | `{pack_id, status:"draft"}` |
| `POST /packs/{id}/conformance` | `{}` | `{passed:int, total:5, checks:[{id,name,passed,detail}]}` |
| `POST /packs/{id}/activate` | `{}` | `{pack_id, status:"active"}` or error `conformance_failed` |
| `POST /events` | `{pack_id, scope_id, type, payload}` | `{admitted:bool, reason:string|null, node_id:string|null}` |
| `POST /memory/search` | `{pack_id, scope_id, query, k}` | `{results:[{node_id,text,score,kind}]}` |
| `POST /decisions` | `{pack_id, scope_id, inputs:[node_id], output}` | `{decision_id}` (writes edges) |
| `POST /directives` | `{pack_id, scope_id, directive}` | `{directive_id, status}` or error `not_confirmed` |
| `GET /directives` | query: `pack_id, scope_id, active_only` (default true) | `{directives:[{directive_id, ...directive, status}]}` |
| `POST /retract` | `{pack_id, scope_id, target_id, reason}` | `{plan, replayed:[decision_id]}` |
| `GET /why/{decision_id}` | query: `pack_id, scope_id` | `{decision, provenance:[...], ledger:[...]}` |
| `GET /diff` | query: `pack_id, scope_id, retract` | `{before:[...], after:[...], changed:[...], preserved:[...]}` |
| `GET /ledger` | query: `pack_id, scope_id, limit` | `{entries:[...]}` |

A gated event returns HTTP 200 with `admitted:false`. Nothing is written to `nodes` or `edges`.
Errors: HTTP 4xx/5xx with `{"error": {"code": "string", "detail": "string"}}`. Stable codes: `bad_request`, `not_found`, `conformance_failed`, `not_confirmed` (HTTP 422), `forbidden` (HTTP 403), `scope_violation`, `internal`.

### Compiler service (David, port 8002)
| Route | Body in | Body out |
| --- | --- | --- |
| `POST /directives/compile` | `{pack_id, scope_id, text}` | `{directive, summary}` (unconfirmed, `confirmed_by:null`) |
| `POST /directives/confirm` | `{pack_id, scope_id, directive, pin}` | the core `POST /directives` response |

The compiler checks the PIN server-side (`DIRECTIVE_PIN` / `BUILDER_PIN`), sets `confirmed_by`, then calls the core. The UI and harness server (`ui/`, `harness/`) are Jasmine's and documented in `ui/README.md` and `harness/README.md`; they are not core routes.

## 5. Conformance checks (domain-neutral)

1. `retraction_recalls_dependents`
2. `independent_support_preserved`
3. `no_cross_scope_reads`
4. `expiry_removes_memory_and_dependents`
5. `gated_content_never_enters_memory`

## 6. Retraction plan JSON (shared by Python and Rust planners)

```json
{
  "fault": "node_id",
  "actions": [
    {"id": "node_id", "action": "delete|quarantine|invalidate|replay|preserve", "reason": "string|null"}
  ]
}
```
Rust CLI: reads `{graph, fault}` JSON on stdin, writes the plan JSON on stdout. Fixtures live in `core/fixtures/` (owner: Aniket) and are the shared tests.

## 7. LLM access

`shared/llm.py::get_llm()` returns a LangChain chat model from `LLM_PROVIDER` (`groq`|`openrouter`), `LLM_MODEL` and the matching key. Compilers must use structured output and validate against sections 2 and 3.

## 8. Directive trust (security)

The core must not trust `confirmed_by` from arbitrary callers, or the PIN can be bypassed by calling the core directly. `POST /directives` requires header `X-Compiler-Key` equal to env `COMPILER_SHARED_SECRET`; otherwise HTTP 403 `forbidden`. Only the compiler service holds the secret. (Owner: Aniket, A3.)

## 9. Mock API

`mock/app.py` serves canned responses for every core route above on port 8001 (the compiler routes are served by `compiler/app.py` on 8002). It enforces `X-Compiler-Key` only when `COMPILER_SHARED_SECRET` is set. Real API (A3) must match these shapes. Run: `uvicorn mock.app:app --port 8001`.
