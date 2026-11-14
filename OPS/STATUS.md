# STATUS

One line per package. Update at each milestone. Format: `ID | owner | state | note | updated`.
States: `todo`, `doing`, `blocked`, `done`.

G1 | Greatness | done | merged to main; get_llm() verified on Groq gpt-oss-120b | 14:30
G2 | Greatness | done | catalog(200), pack, scopes, seed graph + scenario in data/; live load waits on A1 indexes (audit collection is `history`, decided 15:20) | 14:45
G3 | Greatness | done | rust/recall-core: stdin {graph,fault} -> stdout plan (arg: provenance|label_only); cargo test passes on core/fixtures/plan_*.json; 78/78 identical to core/planner.py on every seed node x both policies | 15:55
A1 | Aniket | done (merged) | core/db.py: 7 collections, $jsonSchema validators (v0.3), indexes, no TTL (expiry sweep), vector index nodes_embedding; audit collection is `history` (verified in core/db.py); seed loads | 15:30
A2 | Aniket | done (merged) | core/planner.py + engine.py: provenance trace, evidence retract, derivation, support check, replay, RETRACTION_POLICY; fixtures core/fixtures/plan_*.json ready for G3 | 15:30
A3 | Aniket | done (merged) | core/api.py: every mock route, same shapes, port 8001 (`uvicorn core.api:app --port 8001`); X-Compiler-Key enforced | 15:30
A4 | Aniket | done (merged) | core/conformance.py: 5/5 provenance on pack_video_demo + pack_team_docs; label_only 4/5 (fails check 1) | 15:30
D1 | David | done | directive compiler on real data/ pack (pack_video_demo); gate fields (maturity) not directable; PIN gate; 25-prompt set in eval/directive_prompts.json; 100 tests pass offline; :8002 UI routes pending contract; live LLM eval 25/25; CONTRACT v0.2 header + 422 done | 15:23
D2 | David | done | pack compiler + cached fallback (compiler/pack.py), 5-check conformance suite (compiler/conformance.py), second pack pack_team_notes; suite 5/5 on reference core, each injected bug caught; mock scores 1/5 (canned); live LLM: 4/4 sentences -> valid packs, 5/5 on reference core; live A3 run pending (conventions in BLOCKERS) | 15:22
D3 | David | done | retract-one: dec_02/03 recalled, dec_08 preserved, slate drops only spooky-only items (eval/retract_one.py); with/without-memory eval on 25 prompts: gate + effect 100% both modes, personalized 98% vs 0% (live LLM same); evidence in eval/evidence/; LangSmith traced (project memory-governance-eval, dataset governed-memory-25); live directive eval 24-25/25; --core run pending live data | 16:04
J1 | Jasmine | doing | parent-only feed UI: bottom prompt -> D1 compiler (auto slots, manual fallback), Save rule (server passes DIRECTIVE_PIN), ⋮ Why this?/Don't recommend, child avatars, What changed diff; ui/run_demo.sh (--core/--reseed); live run on real core waits on MONGODB_URI | 16:16
J2 | Jasmine | doing | harness: gate>block>boost, slates, decisions per item, GET /directives + /memory/search via HARNESS_*=api (set by run_demo.sh --core), 15 tests | 16:16
J3 | Jasmine | todo | | 

Contract: v0.2 at 15:05 (Greatness).
