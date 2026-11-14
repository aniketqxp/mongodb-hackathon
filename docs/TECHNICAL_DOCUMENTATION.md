# Governed Memory Core: Technical Documentation

Snapshot of the team design doc, 14 Nov 2026. `OPS/CONTRACT.md` is the source of truth for schemas and routes; if the two disagree, the contract wins.

## 1. Overview

We are building a domain-agnostic governed-memory core on MongoDB Atlas: an agent memory where any stored fact can be traced, retracted, expired or blocked, and every decision that depended on it is repaired automatically.

Track: **Memory You Can Govern**, Agents in Context Toronto Hackathon (Sat 14 Nov 2026, submissions due 5:00 PM ET, judging from 5:15).

**The claim:** restricted content never enters memory or queued slates, and retracting one memory recalls only the decisions that depended on it. Decisions with independent support are preserved. **A retracted memory stays retracted:** it cannot be re-derived from the evidence that produced it (section 4.1).

**Two-part demo**

1. *Generalization* (about 1 minute): Prompt → Pack → Conformance. A builder describes a domain in one sentence, an LLM fills a data-only domain pack, and a domain-neutral test suite must pass 5/5 before the pack activates.
2. *Hero use case:* a parental-monitoring video recommender with a "right to un-recommend" and "parent prompt → policy". The judge plays the parent.

**How it answers the track questions**

| Track question | Where it is answered |
| --- | --- |
| Leakage between clients or teams | Every record carries `pack_id` + `scope_id`; vector search pre-filters on scope; conformance check 3 |
| Fix or drop wrong or expired memory | Retraction planner (delete, retract, quarantine, invalidate, replay, preserve); expiry sweep and decay |
| Prove memory changed behavior | Receipt/diff view and LangSmith with/without-memory eval (D3) |
| Who reads, how long it lives, how forgotten | Scope rules, expiry on every directive, audit ledger, "why" API |

**Judging map:** Technical Demo 35% (end-to-end recall and the retract-one diff), Difficulty 30% (provenance graph, support check, pack compiler, conformance), Creativity 15% (plain-language parent policy, pack-from-a-sentence), Impact 20% (parents and children, plus any domain a judge names).

**Hard constraints:** finalists use the provided Atlas Sandbox; the repo is public; only work built during the event is shown; synthetic data only; none of the banned project types (Streamlit apps, basic RAG, dashboard-as-main-feature, sports analyzers or coaches, and the others in the participant guide).

## 2. Architecture

```mermaid
flowchart TB
  subgraph H["Harness (swappable, talks only to the API)"]
    UI["Typed UI<br/>feed, parent box, diff, why-this"]
    GE["Gate evaluator<br/>applies pack gate and directives"]
    SG["Slate generator<br/>vector search over scoped memory"]
  end
  subgraph C["Compilers (LLM)"]
    C1["Sentence → directive"]
    C2["Sentence → pack"]
  end
  API["Core API · JSON over HTTP · pack_id + scope_id on every call"]
  subgraph CORE["Core (generic, no domain words)"]
    ES["Event store<br/>append-only, gated"]
    PG["Provenance graph<br/>$graphLookup edges"]
    SC["Support check<br/>independent support"]
    PL["Planner<br/>5 rule actions"]
    RP["Selective replay<br/>only dependents"]
    LG["Ledger + why<br/>audit, provenance"]
  end
  PACK["Domain pack (data only, about 8 slots)<br/>node and edge types, gate predicate, decay curve,<br/>scope field, directive vocabulary, UI labels"]
  ATLAS[("MongoDB Atlas sandbox<br/>events, nodes, edges, decisions, directives, history, packs<br/>Vector Search · $graphLookup · schema validation")]
  H --> API
  C --> API
  API --> CORE
  PACK --> CORE
  CORE --> ATLAS
  PACK --> ATLAS
```

Harnesses and compilers reach the core only through the API, and the pack is plain data the core reads, so a new domain needs no core change. Enforcement (the gate, the planner, expiry) is code in the core; the LLM only fills pack and directive slots.

## 3. Data model

Seven generic collections hold everything. None has a domain word in its name or fields; domain meaning lives only in the pack's `types` and `slots` values. The exact field list is in `OPS/CONTRACT.md`, and that file wins over this table.

| Collection | Holds | Key fields | Indexes |
| --- | --- | --- | --- |
| `events` | Append-only raw observations (a view, a skip, a parent sentence) | `pack_id`, `scope_id`, `type`, `payload`, `ts`, `source` | `(pack_id, scope_id, ts)` |
| `nodes` | Memory items: facts, preferences, derived beliefs, plus a vector | `pack_id`, `scope_id`, `kind`, `text`, `embedding`, `status`, `expires_at`, `support[]` | Atlas Vector Search on `embedding` with `pack_id` and `scope_id` as filter fields; plain index on `expires_at` (expiry sweep, no TTL) |
| `edges` | Typed dependencies, memory → decision | `from`, `to`, `rel`, `pack_id`, `scope_id` | `from`, `to` (for `$graphLookup`) |
| `decisions` | Actions the agent took (a slate, a ranking) with the node ids they used | `pack_id`, `scope_id`, `inputs[]`, `output`, `status`, `replay_of` | `(scope_id, ts)` |
| `directives` | Typed policies: suppress, prioritize, retract | `pack_id`, `scope_id`, `type`, `target`, `expires_at`, `cap`, `confirmed_by` | `(scope_id, type)`; plain index on `expires_at` (expiry sweep, no TTL) |
| `history` | Audit record of every governance action (served by `GET /ledger`) | `actor`, `action`, `target`, `before`, `after`, `ts` | `(scope_id, ts)` |
| `packs` | Domain packs: data-only config | `pack_id`, `slots`, `status` (`draft` / `active`), `conformance` result | `pack_id` unique |

**Rules**

- Every read and write is filtered by `pack_id` and `scope_id`. The vector search pre-filters on scope, so a query never sees another scope's vectors.
- Memory states are `active`, `quarantined`, `invalidated`, `expired`, plus `retracted` for evidence nodes (contract v0.3). Nothing is hard-deleted without a `history` entry. Events are never modified.
- Embeddings use Voyage `voyage-4-lite`. The sandbox's token allowance is for Voyage embedding and rerank only, not for chat LLMs.
- **Expiry is a status change, not a TTL delete (contract v0.3).** A Mongo TTL index deletes documents silently and on its own schedule (about every 60 s), so the planner could never see what expired, and the expired node could not be audited. Instead the core runs an expiry sweep at the start of each request: anything past `expires_at` is set to `expired` and goes through the same recall path as a manual retraction. `expires_at` keeps a plain index.

## 4. Recall mechanism

When one memory is wrong, expired or unwanted, recall finds every decision that depended on it, rolls back only those that lack independent support, and replays them. It follows the dependency-guided rollback repair from the arXiv paper the team attached. This is the Technical Demo centerpiece and package A2.

**Pipeline (all steps are code; the LLM takes no part):**

1. **Trace.** From the faulty node, walk `edges` with `$graphLookup` both ways: upstream to the evidence nodes that support it, downstream to every dependent node and decision (the fault's provenance set).
2. **Retract evidence.** Evidence nodes upstream of the fault are set to `retracted` (never deleted). Other derived nodes that lose all active support are invalidated too, and those that keep support of their own are kept.
3. **Independent-support check.** For each affected decision, ask whether it still has at least one supporting node outside the provenance set. If yes, it is *preserved*. If no, it is a rollback candidate. The check is deliberately lenient, as the paper's own limits suggest.
4. **Plan.** Rules map each affected item to one action: `delete` (the faulty node; implemented as status `invalidated` plus a `history` entry, no hard delete), `retract` (its upstream evidence, contract v0.3), `quarantine` (derived beliefs awaiting review), `invalidate` (decisions that lost all support), `replay` (decisions to recompute), or `preserve`.
5. **Replay.** Recompute only the invalidated decisions, with the faulty node excluded, and write new decisions with `replay_of` pointing at the old ones.
6. **Ledger.** Every action is written to `history`, and the "why" API can answer "why was this recommended?" and "what did retracting X change?" from it.

**Output of a plan** (JSON, identical for the Python reference and the Rust crate):

```json
{
  "fault": "node_123",
  "actions": [
    {"id": "node_123", "action": "delete"},
    {"id": "node_201", "action": "quarantine"},
    {"id": "dec_77",  "action": "invalidate"},
    {"id": "dec_77",  "action": "replay"},
    {"id": "dec_80",  "action": "preserve", "reason": "independent_support"}
  ]
}
```

### 4.1 Why step 2 exists: forgotten memories creep back

Derived nodes (for example an interest built from several observed facts) are recomputed whenever new events arrive. If retraction only marks the derived node and leaves its evidence active, the next recompute derives it again under the same id, and the forgotten memory returns. Its sibling nodes, built from the same evidence, never notice. Nobody has to script this failure: it follows from recompute.

**Derivation rule (core, no pack change):** a derived node's status is a pure function of its active supporters. It is `active` if and only if at least one parent (an edge whose source is a node) is active. Derived ids are deterministic (`node_{scope}_{kind}_{key}`), so a re-derivation lands on the same id and can be measured. **The core writes the provenance edges itself.** `POST /events` creates one evidence node (kind = the pack's first node-to-node `edge_types.from`), a `provenance` edge from the event to it, and an edge to every existing derived node whose key appears among the payload's string values. `payload.derives: [{"kind", "key"}]` is optional and only needed to create a *new* derived node. Seed graphs that already contain evidence-to-derived edges (like `data/graph.json`) work unmodified.

**The experiment switch:** `RETRACTION_POLICY=label_only|provenance` (env, core). `label_only` skips step 2 and is the naive baseline. `provenance` is the governed default. Everything else is identical.

**Measured on the team seed** (`python -m core.demo`: Atlas Sandbox, `pack_video_demo`, scenario `node_child_7_interest_spooky`, real routes, lexical search; `core/fixtures/runs/creep_back_seed.json`). Each session is one `POST /memory/search` for the target's text, which runs the same recompute under both policies:

| policy | before retract | +1 session | +2 | +3 | evidence retracted | scenario match |
|---|---|---|---|---|---|---|
| `label_only` | active, rank 1 | active, rank 1 | active, rank 1 | active, rank 1 | 0 | yes |
| `provenance` | active, rank 1 | invalidated, not returned | invalidated, not returned | invalidated, not returned | 4 | yes |

Both policies invalidate and replay `dec_child_7_02` and `dec_child_7_03` and preserve `dec_child_7_08`, so the decision repair alone looks correct under the naive policy. The difference is that under `label_only` the forgotten node is re-derived (1 ledger `rederived` entry) and is back in memory from the first session.

Earlier, on Aniket's prototype (synthetic fixture, local hash embeddings):

| condition | before retract | +1 session | +2 | +3 |
|---|---|---|---|---|
| no memory | 0% | 0% | 0% | 0% |
| `label_only` | 40% | 40% | 40% | 40% |
| `provenance` | 40% | 0% | 0% | 0% |

Share of a 10-item decision taken up by the retracted target. With 20 evidence events traced, `label_only` re-derived the node in 3 of 3 sessions and kept all 3 sibling memories marked as still justified; `provenance` invalidated them. A second, hand-written pack gave the same pattern with zero lines of core changed.

**Known limits (from the paper, to say out loud in the demo):** recall needs instrumented provenance (we write edges at decision time), an upstream fault detector (the parent, a directive or TTL supplies it), resettable side effects (recommendations are recomputable), and a lenient support check. Stale-fault repair works best when the fault recurs, so the demo uses a scripted curve.

## 5. Compilers

One LLM compiler pattern is used twice. The LLM only fills typed slots. A validator checks the output, a human confirms it, and code (never the LLM) enforces the gate and the planner.

**Compiler 1: parent sentence → directive (David, D1)**

- Input: "No scary stuff for my 7-year-old until the weekend."
- Output: a typed directive, one of three primitives: `suppress` (with expiry), `prioritize` (with a cap), `retract`.
- Precedence when directives collide: **gate > block > boost**.
- Writes need a PIN-gated confirm step: the UI shows the parsed directive in plain words, the parent approves with the PIN, and only then does it reach `directives`.
- Injection tests: a sentence that tries to disable the gate, widen scope or remove expiry must fail validation.

**Compiler 2: builder sentence → domain pack (David, D2)**

- Input: one sentence describing a domain (for example a different recommender or a team-memory assistant).
- Output: a pack of about 8 slots, as data only: node and edge `types`, the gate predicate, the decay curve, the scope field, the directive vocabulary, and labels for the UI.
- Fallback: a cached, previously validated pack is served if the LLM call fails or the token budget is spent.

**Validation, for both compilers**

1. JSON-schema validation against the contract. Reject on any extra or missing field.
2. Referential checks (every edge type names a declared node type; every directive target exists).
3. Human confirm: PIN for parents, an explicit "activate" for builders. The pack only activates if the conformance suite passes 5/5.

**LLM setup:** `get_llm()` (in `shared/llm.py`) reads provider, model and key from environment variables. Primary is Groq `openai/gpt-oss-120b`, with strict structured output via `method="json_schema"`. Fallback is OpenRouter through the OpenAI-compatible base URL. Details in section 9.

## 6. Conformance suite

A pack activates only when all 5 domain-neutral checks pass. The suite synthesises its fixture from the pack definition in throwaway scopes and uses no domain words, so the same code tests any pack with no test code per pack. **Owner: Aniket (core), proposed.** It runs inside `POST /packs/{id}/conformance` and needs core internals, so it lives in `core/`. D2 calls the route.

Measured (`python -m core.conformance`, `core/fixtures/runs/conformance_log.txt`): `pack_video_demo` and the hand-written `pack_team_docs` (`core/fixtures/pack_docs.json`) both pass 5/5 under `provenance`; under `label_only` both score 4/5 and fail only check 1 (target active in 3/3 sessions after retraction). The log records both runs, so the naive baseline is evidence too.

| # | Check | Passes when |
| --- | --- | --- |
| 1 | Retraction recalls dependents **and stays retracted** | Retracting a seeded node invalidates every decision that depended only on it, and the node is not re-derived and its target is absent from decisions over the next 3 sessions |
| 2 | Independent support preserved | A decision with a second supporting node outside the fault's provenance set survives retraction, and no node left active depends only on retracted evidence |
| 3 | No cross-scope reads | A query in scope A returns nothing from scope B, including through vector search |
| 4 | Expiry removes memory and dependents | After a node's `expires_at`, it and its dependent decisions are recalled |
| 5 | Gated content never enters memory | An item the gate rejects creates no node, no edge and no queued slate entry |

**Generalization tiers** (what we show, in order of risk):

- **Floor:** a second, hand-written pack passes 5/5 on the same core, proving the core holds no domain words.
- **Target:** the LLM generates a pack from one sentence and it passes 5/5 live, with a cached pack as fallback.
- **Bonus:** a judge names a domain and we generate and test it on stage.

## 7. API contract

The harness, compilers and UI talk to the core only through these routes. See `OPS/CONTRACT.md` for exact shapes; `mock/app.py` serves canned responses. Every body is JSON and every request carries `pack_id` and `scope_id`.

| Route | Purpose | Caller |
| --- | --- | --- |
| `POST /packs` | Register a draft pack (slots as data) | Pack compiler (D2) |
| `POST /packs/{id}/conformance` | Run the 5 checks, return per-check pass/fail | Pack compiler (D2) |
| `POST /packs/{id}/activate` | Activate only if the last conformance run was 5/5 | UI (J1) |
| `POST /events` | Append an observation; passes the gate first | Harness (J2) |
| `POST /memory/search` | Scope-filtered vector search over `nodes` | Harness (J2) |
| `POST /decisions` | Record a decision with its input node ids; writes edges | Harness (J2) |
| `POST /directives` | Create a confirmed directive (suppress, prioritize, retract). Accepted only with the compiler's shared-secret header, so `confirmed_by` cannot be forged by calling the core directly (`X-Compiler-Key`, contract v0.2) | Directive compiler (D1) |
| `POST /retract` | Retract a node or directive; returns the plan and the replay result | UI (J1) |
| `GET /why/{decision_id}` | Provenance and ledger entries for a decision | UI (J1) |
| `GET /diff?retract={id}` | With/without diff of slates after a retraction | UI (J1), eval (D3) |
| `GET /ledger` | Audit entries for a scope, newest first | UI (J1) |

**Conventions**

- Errors return `{"error": {"code": "...", "detail": "..."}}` with a stable `code`.
- IDs are strings. Timestamps are ISO 8601 UTC.
- A gated event returns `200` with `{"admitted": false, "reason": "..."}`. Nothing is written to `nodes` or `edges`.
- `POST /retract` and `GET /diff` return the same plan JSON shown in section 4, so the Python and Rust planners are interchangeable.

## 8. Hero use case: parental-monitoring video recommender

A child's feed is built from watch memory. The parent can say, in plain words, what the feed should and should not do, and can un-recommend anything with a visible, provable effect. The judge plays the parent. This is a **harness** on the generic core, not part of it.

**Pieces (Jasmine's harness, using Greatness's data)**

- **Catalog:** about 200 synthetic videos with a taxonomy (topic, maturity level, tags). No real children's data; all watch history is scripted curves. (G2)
- **Gate evaluator:** a generic evaluator that reads the pack's gate predicate and the active directives. Restricted content is quarantined *before* it can create a memory or enter a queued slate. (J2)
- **Slate generator:** builds the next slate from `$vectorSearch` over scoped memory, then applies precedence gate > block > boost. (J2)
- **UI:** a light JavaScript front end, not Streamlit and not a dashboard. It has a child feed, a parent box with a PIN confirm card, a receipt/diff view and a "why this?" action. (J1)

**Demo beats (about 3 minutes)**

1. The child feed shows a slate shaped by watch history.
2. The parent types a sentence. The compiler shows the parsed directive; the PIN approves it; the next slate changes and a receipt lists what was blocked.
3. The parent hits "un-recommend" on a video. Recall runs: only the dependent slate items are replaced, and an independently supported item is shown as preserved.
4. The diff view shows the slate with and without the retracted memory.
5. "Why this?" shows the provenance chain and the ledger entries.

**Boundaries:** synthetic data only; the PIN is a demo gate, not real authentication; the system makes no claim about child safety beyond what the gate and directives enforce.

## 9. Stack, LLM providers and environment

**Stack**

| Layer | Choice | Notes |
| --- | --- | --- |
| Database | MongoDB Atlas (the hackathon Sandbox) | `$vectorSearch` with scope pre-filter, `$graphLookup`, `$jsonSchema` validation (contract v0.3 validators), change streams |
| Core language | Python (PyMongo, FastAPI) | The spine |
| Embeddings | Voyage `voyage-4-lite` | Covered by the sandbox's Voyage allowance |
| Orchestration | LangChain / LangGraph | LangChain is an adapter layer, not a model |
| Tracing | LangSmith | Free Developer plan: 1 seat, 5k base traces a month, 14-day retention |
| Voice | ElevenLabs | Stretch only; free plan has 10,000 credits a month and no commercial licence |
| Front end | Light JavaScript | Not Streamlit; not a dashboard |
| Rust | `recall-core` crate (G3) | Optional; see section 10 |

**Which LLM, and why not the sandbox:** the sandbox's token allowance covers Voyage embeddings and reranking only, so chat completions need another provider.

- **Primary: Groq** `openai/gpt-oss-120b`. Strict structured output works on gpt-oss models via `method="json_schema"` (langchain-groq 0.3.8 or newer); it does not combine with streaming or tool use. Free limits are per organisation and published figures conflict (1,000 vs 14,400 requests a day), so trust the limits page in the Groq console.
- **Fallback: OpenRouter.** OpenAI-compatible, so it is a base-URL swap. `:free` models are limited to 20 requests a minute and 50 a day, or 1,000 a day after a one-time purchase of at least $10 in credits. Free models can change or disappear without notice.
- **Tokens bind before requests do.** At the sampled Groq limit of 200,000 tokens a day and about 2 to 3k tokens per compiler call, plan on roughly 70 to 80 calls a day (our estimate). Keep prompts compact, cache validated outputs, and reserve a fresh budget before judging.

**Environment variables** (in `.env`, never committed; `.env.example` with empty values is committed)

```bash
MONGODB_URI=
VOYAGE_API_KEY=
LLM_PROVIDER=groq            # groq | openrouter
LLM_MODEL=openai/gpt-oss-120b
GROQ_API_KEY=
OPENROUTER_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_TRACING=true
ELEVENLABS_API_KEY=
RETRACTION_POLICY=provenance # provenance | label_only (eval baseline)
COMPILER_SHARED_SECRET=      # compiler -> core POST /directives
```

`get_llm()` returns a LangChain chat model from `LLM_PROVIDER`, `LLM_MODEL` and the matching key, so switching providers is an env change, not a code change.

## 10. Rust `recall-core` crate

Rust is optional and must never be on the critical path. Greatness (G3) builds a small pure-logic crate that implements the retraction planner, and the demo works without it.

- **Interface:** a CLI that reads the graph and fault as JSON on stdin and writes the plan JSON from section 4 on stdout. PyO3 bindings only if time allows.
- **Reference:** the Python planner (A2) is the source of truth. The two must produce identical plans on the shared fixture files; those fixtures double as the crate's tests.
- **Why it earns its place:** it shows the mechanism is language-neutral and fast on large graphs, which supports Difficulty without adding risk.
- **Go/no-go at 3:00 PM:** if the crate does not match the fixtures by then, drop it and keep the Python planner. Nothing else depends on it.
- **Layout:** `rust/recall-core/` (`Cargo.toml`, `src/`, `tests/fixtures/`); `target/` is gitignored.

## 11. Work packages and dependencies

```mermaid
flowchart LR
  G1["G1 Greatness<br/>contract, mock API"]:::main
  G2["G2 Greatness<br/>catalog + seed"]
  G3["G3 Greatness<br/>Rust crate"]
  A1["A1 Aniket<br/>indexes, search"]
  A2["A2 Aniket<br/>recall + fixtures"]
  A3["A3 Aniket<br/>real API, ~3:45"]
  A4["A4 Aniket<br/>conformance + 2nd pack"]
  D1["D1 David<br/>directive compiler"]
  D2["D2 David<br/>pack + conformance"]
  D3["D3 David<br/>eval + diff"]
  J1["J1 Jasmine<br/>typed UI"]
  J2["J2 Jasmine<br/>gate + slates"]
  J3["J3 Jasmine<br/>demo + submission"]
  G2 -->|seeding| A1
  G2 --> J2
  A2 --> G3
  A2 --> D3
  A3 --> D2
  A4 --> D2
  A2 --> A4
  A3 --> J1
  D1 --> J1
  classDef main stroke-width:3px
```

Arrow means "waits on". G1 gates integration for everyone. Drop G3 first if time slips; nothing depends on it.

| Package | Owner | Scope | Waits on |
| --- | --- | --- | --- |
| G1 | Greatness | Repo hygiene, scaffold, `CLAUDE.md` and OPS files, env and `get_llm()`, contract v0, mock API | Nothing |
| G2 | Greatness | 200-video catalog, taxonomy, scripted user curves, seed loader. **Add:** for events posted live, put the gate field (`maturity`) and the derived key (the topic) in the watch payload; the seed graph itself needs no change | G1 scaffold |
| G3 | Greatness | Rust `recall-core` crate, go/no-go at 3:00 PM. If kept, add the `retract` action | A2 fixtures |
| A1 | Aniket | Atlas collections, indexes, scoped vector search, ledger, expiry sweep (no TTL deletes) | G2 for seeding only |
| A2 | Aniket | Provenance graph (both directions), evidence retraction, derivation rule, support check, planner, replay, `RETRACTION_POLICY` switch, plus JSON fixtures | Nothing |
| A3 | Aniket | Real core API on the mock's shapes (revised target about 3:45 PM), compiler shared-secret check on `/directives` | A1, A2 |
| A4 | Aniket | **New:** 5-check conformance runner behind `POST /packs/{id}/conformance`; hand-written second pack in contract schema (floor tier), placed in `data/` with Greatness's review | A2 |
| D1 | David | Directive compiler (3 types), PIN-gated writes, confirm step, injection tests. **Add:** send the shared-secret header | G1 contract |
| D2 | David | Pack compiler with cached fallback; calls the conformance route (runner moved to A4) | G1 contract; A3 for live runs |
| D3 | David | LangSmith tracing, 25-prompt dataset, with/without-memory eval, retract-one diff. **Add:** creep-back table, 3 conditions (no memory, `label_only`, `provenance`) over 3 sessions after a retraction | A2 |
| J1 | Jasmine | Typed UI: child feed, parent box with PIN card, receipt/diff, why-this | G1 mock, A3; D1 for the parent box (about 3:15 PM) |
| J2 | Jasmine | Generic gate evaluator, restricted-content quarantine, slate generator | G2 catalog |
| J3 | Jasmine | Demo script, 1-minute video, README, submission form, fallbacks | Everything, late |

**Gates:** about 2:00 PM contract and pack schema frozen; 3:00 PM recall works end to end; 3:45 PM compiler, UI and PIN working; 4:15 PM feature freeze; submit by 4:45 PM, ahead of the 5:00 PM deadline.

## 12. Claude Code kit

Everyone works in their own Claude Code harness, so the repo carries the rules and the coordination files. See `CLAUDE.md`, `OPS/` and `.claude/skills/`.

**`CLAUDE.md` rules**

- The core has no domain words. Domain meaning lives only in pack data.
- The LLM never enforces the gate or the planner; code does.
- Python is the spine. Rust and JavaScript talk to it through the contract.
- Keys live in environment variables only. All data is synthetic.
- Respect the banned-project list from the participant guide.
- Edit only your own directories. Never force-push `main`.

**Directory ownership**

| Directory | Owner |
| --- | --- |
| `core/` | Aniket |
| `rust/`, `data/`, `OPS/`, `scripts/`, `mock/`, `shared/` | Greatness |
| `compiler/`, `eval/` | David |
| `harness/`, `ui/` | Jasmine |

**`OPS/` files:** `CONTRACT.md` (single source for collections, routes, schemas), `OWNERS.md`, `STATUS.md` (one line per package), `BLOCKERS.md` (append-only), `KICKOFF.md` (start steps and the kickoff prompt).

**Skills in `.claude/skills/`:** `handoff`, `precommit-check` (secret scan, domain-word grep in `core/`, tests), `contract-check`.

## 13. Evaluation, observability and demo script

The track asks us to prove memory changed behavior. D3 (David) produces that proof, and J3 (Jasmine) turns it into the demo.

**Evaluation (D3)**

- A LangSmith dataset of 25 prompts (parent sentences, retractions, gated items).
- Each run is traced twice, with memory and without, and the slate diff is stored as the evidence.
- The headline test is **retract one**: remove a single memory, then show that only its dependents changed and independently supported items did not.
- The second test is **creep-back**: the same retraction under three conditions (no memory, `label_only`, `provenance`), measured over the 3 sessions that follow. It shows that the retraction holds over time, not only right after it.
- Every governance action is also in `history`, so the evidence does not depend on LangSmith retention (14 days on the free plan).

**Demo script (J3), in order**

1. One sentence of framing: "Memory you can govern: fix it, expire it, prove it."
2. Generalization: type a domain sentence → pack appears → conformance 5/5 → activate (cached pack if the LLM is slow).
3. Hero: the five beats in section 8.
4. Close on the track questions: leakage (scope), fix or drop (recall), prove (diff), who reads and how long (ledger and expiry).

**Submission checklist:** public repo with README and `.gitignore`; sandbox-backed run; 1-minute video; submission form before 5:00 PM ET; backup recording in case the live demo fails.

## 14. Risks, fallbacks and open items

| Risk | Likelihood / impact | Fallback |
| --- | --- | --- |
| G1 (contract, mock API, scaffold) runs late and blocks everyone | Medium / High | Others build against the contract draft; Greatness drops G3 first |
| LLM compiler output is invalid or the provider is down | Medium / High | Validator rejects it; cached validated directive and pack; switch `LLM_PROVIDER` |
| Free-tier token cap hit before judging | Medium / High | Compact prompts, cached outputs, reserved fresh budget, OpenRouter credit |
| Live pack generation fails conformance on stage | Medium / Medium | Cached pack; hand-written second pack proves the core is domain-free |
| Support check is too strict or too lenient on real graphs | Medium / Medium | Scripted seed curves with known answers; fixtures shared by Python and Rust |
| Rust crate does not match Python by 3:00 PM | Medium / Low | Drop it; no other package depends on it |
| Secret leaked into the public repo | Low / High | `.gitignore` first; `precommit-check` skill; rotate any key that is pushed |
| Scope creep into a dashboard | Medium / Medium | Feature freeze at 4:15 PM; UI limited to the five demo beats |

| Retracted memory re-derived from its own evidence (creep-back) | High / High | Evidence retraction plus the derivation rule (section 4.1); conformance check 1 tests it over 3 sessions |

**Open items**

- [x] Contract v0.3 (section 15) folded into `OPS/CONTRACT.md`; announce in team chat.
- [x] `.gitignore`, scaffold, contract v0.1 and mock API merged (G1).
- [x] Audit collection is named `history` (matches the Atlas sandbox); the API keeps `GET /ledger`.
- [ ] Buy the $10 OpenRouter credit with a spend cap (not blocking; before 3:00 PM).
- [ ] A teammate runs one `with_structured_output` call on Groq `gpt-oss-120b` to confirm strict JSON works.
- [ ] Check the participant guide's partner-resources section for extra credits.

## 15. Contract v0.3 (folded into `OPS/CONTRACT.md`)

Each change is additive except the TTL one. Contract v0.2 (Greatness) already added the trust header as `X-Compiler-Key` with HTTP 403 `forbidden`, so item 4 is done there.

| # | Change | Why | Affects |
| --- | --- | --- | --- |
| 1 | Node `status` adds `retracted` (evidence nodes only) | Retraction must disable the evidence, not only the derived label (section 4.1) | CONTRACT §1, core |
| 2 | Plan `action` adds `retract` | The plan has to show the evidence it retracted | CONTRACT §6, mock `PLAN`, Rust crate if kept |
| 3 | Drop TTL indexes on `nodes.expires_at` and `directives.expires_at`; use a plain index plus the core's expiry sweep | A TTL delete is silent, so expired nodes can't be recalled or audited | CONTRACT §1, A1 |
| 4 | `POST /directives` requires header `X-Compiler-Key` (env `COMPILER_SHARED_SECRET`); otherwise 403 `forbidden` (already in v0.2) | Closes the PIN bypass David raised in BLOCKERS 14:34 | CONTRACT §4, D1, `.env.example` |
| 5 | The core writes event-to-memory provenance edges itself; `payload.derives: [{kind, key}]` is optional, only to create a new derived node | Derivation without domain words; the seed works unmodified | CONTRACT §4 note, J2 harness |
| 6 | Conformance check 1 keeps its name; its definition adds "and stays retracted over 3 sessions" | Tests that the retraction holds over the next 3 sessions | CONTRACT §5, mock |
| 7 | Env `RETRACTION_POLICY` (`provenance` default, `label_only` for the eval baseline) | One switch for the ablation | `.env.example`, D3 |
| 8 | `$jsonSchema` validators on all 7 collections (`core/db.py`, `validationLevel: moderate`) | Schema validation is part of the governance story; the old prototype validators rejected the team seed | CONTRACT §1, A1 |

Unchanged: the pack's 8 slots, every route path and body, the directive schema, and the plan JSON shape. The gate reads `value_from_scope` from the latest `scope_profile` event, as D1 asked.
