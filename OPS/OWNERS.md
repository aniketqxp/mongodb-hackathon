# OWNERS

| Directory | Owner | Packages |
| --- | --- | --- |
| `core/` | Aniket | A1, A2, A3 |
| `rust/`, `data/`, `OPS/`, `scripts/`, `mock/`, `shared/` | Greatness | G1, G2, G3 |
| `compiler/`, `eval/` | David | D1, D2, D3 |
| `harness/`, `ui/` | Jasmine | J1, J2, J3 |

Assignments are proposed until the team approves them. Swap owners by editing this file in a PR.

## Packages
| ID | Scope | Waits on |
| --- | --- | --- |
| G1 | Repo hygiene, scaffold, CLAUDE.md and OPS, env + `get_llm()`, contract v0, mock API | none |
| G2 | 200-video catalog, taxonomy, scripted user curves, seed loader | G1 scaffold |
| G3 | Rust `recall-core` crate (go/no-go 3:00 PM) | A2 fixtures |
| A1 | Atlas collections, indexes, scoped vector search, ledger and TTL | G2 for seeding only |
| A2 | Provenance graph, support check, planner, replay (Python) + JSON fixtures | none |
| A3 | Real core API replacing the mock (~3:00 PM) | A1, A2 |
| D1 | Directive compiler (3 types), PIN-gated writes, injection tests | G1 contract |
| D2 | Pack compiler with cached fallback, 5-check conformance suite | G1 contract; A3 for live runs |
| D3 | LangSmith tracing, 25-prompt dataset, with/without eval, retract-one diff | A2 |
| J1 | Typed UI: feed, parent box + PIN card, receipt/diff, why-this | G1 mock, A3; D1 for parent box (~3:15 PM) |
| J2 | Gate evaluator, quarantine, slate generator | G2 catalog |
| J3 | Demo script, 1-min video, README, submission form | everything, late |

## Gates
~2:00 PM contract frozen · ~3:00 PM recall end to end · ~3:45 PM compiler, UI, PIN · ~4:15 PM feature freeze · submit by ~4:45 PM.
