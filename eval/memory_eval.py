"""With/without-memory eval over the 25 prompts (eval/directive_prompts.json).

  python -m eval.memory_eval            offline: the LLM is replaced by each row's known answer
  python -m eval.memory_eval --live     the real LLM compiles each sentence (rate-limited pacing)

Each prompt runs twice: once with the scope's memory and once with none. In both runs the
compiled directive (or the retraction) is applied to the slate from harness/slate.py. Per run:
  gate_respected    no slate item breaks the pack gate for that scope
  effect_correct    suppress: no matching item; prioritize: boosted <= cap; retract: nothing cites
                    the node; rejected: slate identical to baseline
  personalized      share of slate items backed by memory (the "memory changed behaviour" number)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from compiler.directive import DirectiveError, compile_directive
from compiler.packs import load_bundle
from eval.tracing import traceable, upload_dataset, write_evidence

DS = json.loads((Path(__file__).parent / "directive_prompts.json").read_text())
SIZE = 8


def _harness():
    from harness import data
    from harness.gate import check_gate, target_matches
    from harness.memory import SeedMemory
    from harness.slate import build_slate

    return data, check_gate, target_matches, SeedMemory(), build_slate


def slate_for(scope, nodes, directives=()):
    _, _, _, _, build = _harness()
    return build(scope, nodes, directives=list(directives), size=SIZE)


def score_run(row, scope, nodes, outcome):
    data, check_gate, target_matches, _, _ = _harness()
    base = slate_for(scope, nodes)["slate"]
    if outcome["kind"] == "directive":
        d = {**outcome["directive"], "directive_id": f"eval_{row['id']}"}
        res = slate_for(scope, nodes, [d])
    elif outcome["kind"] == "retract":
        res = slate_for(scope, [n for n in nodes if n["node_id"] != outcome["node"]])
    else:
        res = slate_for(scope, nodes)
    slate = res["slate"]
    rules, prof = data.pack().get("gate", []), data.scope_profile(scope)
    cat = data.catalog_by_id()
    gate_ok = all(check_gate(cat[i["video_id"]], rules, prof)[0] for i in slate)

    if outcome["kind"] == "directive":
        d = outcome["directive"]
        hits = [i for i in slate if target_matches(cat[i["video_id"]], d["target"], "video_id")]
        effect = not hits if d["type"] == "suppress" else len(res["receipt"]["boosted"]) <= d["cap"]
    elif outcome["kind"] == "retract":
        effect = not any(outcome["node"] in i["supports"] for i in slate)
    else:
        effect = [i["video_id"] for i in slate] == [i["video_id"] for i in base]
    personal = sum(1 for i in slate if i["supports"]) / len(slate) if slate else 0.0
    return {"gate_respected": gate_ok, "effect_correct": effect, "personalized": round(personal, 3),
            "slate": [i["video_id"] for i in slate], "baseline": [i["video_id"] for i in base]}


def compile_row(row, bundle, live: bool):
    draft = row.get("expect") or row.get("hostile_draft")
    try:
        d = compile_directive(row["text"], bundle.pack, bundle.vocab, known_ids=bundle.known_ids(row["scope_id"]),
                              llm=None if live else (lambda _: draft), use_cache=False)
    except DirectiveError as e:
        return {"kind": "rejected", "code": e.code, "detail": e.detail[:120]}
    if d.type == "retract":
        return {"kind": "retract", "node": d.target.value, "directive": d.model_dump()}
    return {"kind": "directive", "directive": d.model_dump()}


@traceable("memory_eval_row")
def run_row(row, bundle, live: bool):
    _, _, _, mem, _ = _harness()
    outcome = compile_row(row, bundle, live)
    nodes = mem.search(bundle.pack.pack_id, row["scope_id"], k=20)
    return {"id": row["id"], "text": row["text"], "outcome": outcome,
            "with_memory": score_run(row, row["scope_id"], nodes, outcome),
            "without_memory": score_run(row, row["scope_id"], [], outcome)}


def run(live: bool = False, pause: float = 0.0) -> dict:
    bundle = load_bundle(DS["pack_id"])
    rows = []
    for r in DS["prompts"]:
        rows.append(run_row(r, bundle, live))
        if live:
            time.sleep(pause)
    def agg(mode, key):
        vals = [r[mode][key] for r in rows]
        return round(sum(vals) / len(vals), 3)
    summary = {m: {k: agg(m, k) for k in ("gate_respected", "effect_correct", "personalized")}
               for m in ("with_memory", "without_memory")}
    upload_dataset("governed-memory-25", [{"inputs": {"text": r["text"], "scope_id": r["scope_id"]},
                                           "outputs": {k: r[k] for k in ("expect", "expect_reject") if k in r}}
                                          for r in DS["prompts"]])
    return {"mode": "live" if live else "offline", "n": len(rows), "summary": summary, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--pause", type=float, default=2.5)
    args = ap.parse_args()
    out = run(args.live, args.pause)
    path = write_evidence("memory_eval_live" if args.live else "memory_eval", out)
    s = out["summary"]
    print(f"memory eval ({out['mode']}, {out['n']} prompts)")
    for m in ("with_memory", "without_memory"):
        print(f"  {m:15} gate {s[m]['gate_respected']:.0%}  effect {s[m]['effect_correct']:.0%}  personalized {s[m]['personalized']:.0%}")
    print("  evidence:", path)
    ok = all(s[m]["gate_respected"] == 1 and s[m]["effect_correct"] == 1 for m in s)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
