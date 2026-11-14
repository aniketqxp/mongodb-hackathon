# STATUS

One line per package. Update at each milestone. Format: `ID | owner | state | note | updated`.
States: `todo`, `doing`, `blocked`, `done`.

G1 | Greatness | done | merged to main; get_llm() verified on Groq gpt-oss-120b | 14:30
G2 | Greatness | done | catalog(200), pack, scopes, seed graph + scenario in data/; live load waits on A1 indexes (audit collection is `history`, decided 15:20) | 14:45
G3 | Greatness | todo | go/no-go 15:00; waits on A2 fixtures | 
A1 | Aniket | done (local, uncommitted) | core/db.py: 7 collections, $jsonSchema validators (v0.3), indexes, no TTL (expiry sweep), vector index nodes_embedding; ledger is `ledger` (not history); seed loads | 15:30
A2 | Aniket | done (local, uncommitted) | core/planner.py + engine.py: provenance trace, evidence retract, derivation, support check, replay, RETRACTION_POLICY; fixtures core/fixtures/plan_*.json ready for G3 | 15:30
A3 | Aniket | done (local, uncommitted) | core/api.py: every mock route, same shapes, port 8001 (`uvicorn core.api:app --port 8001`); X-Compiler-Key enforced | 15:30
A4 | Aniket | done (local, uncommitted) | core/conformance.py: 5/5 provenance on pack_video_demo + pack_team_docs; label_only 4/5 (fails check 1) | 15:30
D1 | David | done | directive compiler on real data/ pack (pack_video_demo); gate fields (maturity) not directable; PIN gate; 25-prompt set in eval/directive_prompts.json; 100 tests pass offline; :8002 UI routes pending contract; live LLM untested (no key) | 14:45
D2 | David | todo | | 
D3 | David | todo | | 
J1 | Jasmine | doing | UI on J2 harness + G2 data vs mock: child switch, feed, PIN rule (block/boost), gate probe, un-recommend keeps independently supported items, why-this. Needs D1 compile route, A3 | 14:51
J2 | Jasmine | doing | harness/: generic gate, gate>block>boost, slate gen, decisions per item, 13 unit tests. Seed memory until real /memory/search | 14:51
J3 | Jasmine | todo | | 

Contract: v0.2 at 15:05 (Greatness).
