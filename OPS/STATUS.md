# STATUS

One line per package. Update at each milestone. Format: `ID | owner | state | note | updated`.
States: `todo`, `doing`, `blocked`, `done`.

G1 | Greatness | done | merged to main; get_llm() verified on Groq gpt-oss-120b | 14:30
G2 | Greatness | done | catalog(200), pack, scopes, seed graph + scenario in data/; live load waits on A1 indexes (audit collection is `history`, decided 15:20) | 14:45
G3 | Greatness | todo | go/no-go 15:00; waits on A2 fixtures | 
A1 | Aniket | todo | | 
A2 | Aniket | todo | | 
A3 | Aniket | todo | target ~15:00 | 
D1 | David | done | directive compiler on real data/ pack (pack_video_demo); gate fields (maturity) not directable; PIN gate; 25-prompt set in eval/directive_prompts.json; 100 tests pass offline; :8002 UI routes pending contract; live LLM untested (no key) | 14:45
D2 | David | todo | | 
D3 | David | todo | | 
J1 | Jasmine | doing | parent box wired to D1 compiler (:8002 compile + PIN confirm), manual-slot fallback, ui/run_demo.sh; live LLM needs GROQ key; waits on A3 | 15:40
J2 | Jasmine | doing | harness: gate>block>boost, slates, decisions per item, GET /directives source (HARNESS_DIRECTIVES=api), 15 tests. Seed memory until real /memory/search | 15:40
J3 | Jasmine | todo | | 

Contract: v0.2 at 15:05 (Greatness).
