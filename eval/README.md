# eval/ (owner: David). D3: proof that memory changed behaviour, and that one retraction is surgical

| Command | What it proves | Evidence |
| --- | --- | --- |
| `python -m eval.retract_one` | Retracting `node_child_7_interest_spooky` recalls exactly `dec_child_7_02/03`, preserves `dec_child_7_08` (independent support), and leaves every other decision alone. On the slate, only items backed solely by that memory leave; *Haunted Zoo Night* stays. | `evidence/retract_one.json` |
| `python -m eval.retract_one --core URL` | The same checks against the real planner (A3 `POST /retract`) | same file |
| `python -m eval.memory_eval` | 25 prompts, each run with memory and without, on the harness slate: the gate always holds, every directive has its effect, and rejected prompts change nothing. Memory backs ~98% of the slate, against 0% without memory. | `evidence/memory_eval.json` |
| `python -m eval.memory_eval --live` | The same, with the real LLM compiling each sentence | `evidence/memory_eval_live.json` |
| `python -m eval.run_directive_eval` | Live directive accuracy on the 25 prompts | stdout |

The offline `retract_one` uses a reference support rule (A2 owns the real planner), and the output labels it `planner: reference_support_rule`. Run with `--core` once A3 is up.

## Data
`directive_prompts.json` holds 25 synthetic prompts: 18 with an expected directive and 7 adversarial ones (raising maturity, wildcards, a fake "already confirmed", a cross-scope retract, cap 1000, an unknown topic, a scope switch).

## LangSmith (optional)
Put `LANGSMITH_API_KEY` in `.env` and leave `LANGSMITH_TRACING=false` (free-tier quota). Only D3 runs trace, and only when you add `--trace`:
```
set -a; source .env; set +a
python -m eval.run_directive_eval --trace                          # 25-prompt directive eval, live LLM
python -m eval.memory_eval --live --trace                          # with/without memory
python -m eval.retract_one --core http://localhost:8001 --trace    # real core, once live data is loaded
```
Runs go to project `memory-governance-eval` (override with `LANGSMITH_PROJECT`), LLM calls are traced through LangChain, and the prompts upload as dataset `governed-memory-25`. Without a key everything still runs and writes the same evidence locally, so the proof does not depend on LangSmith's 14-day retention. Against the mock, `--core` fails the scenario check on purpose, because the mock returns canned ids.
