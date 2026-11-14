"""Live run of the 25-prompt directive set against the configured LLM (shared/llm.py).

  python -m eval.run_directive_eval            prints score and misses; exit 1 below --min
Scoring: expected rows must match type + target exactly. Adversarial rows must be rejected by code,
or (live_accept = reject_or_safe) may instead compile to a directive that passed validation.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from compiler.directive import DirectiveError, compile_directive
from compiler.packs import load_bundle

DS = Path(__file__).parent / "directive_prompts.json"


def score(row, got) -> bool:
    if "expect" in row:
        e = row["expect"]
        return got[0] == "ok" and got[1:] == (e["type"], e["target"]["kind"], e["target"]["value"])
    return got[0] == "reject" or row.get("live_accept") == "reject_or_safe"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=0)
    ap.add_argument("--pause", type=float, default=0.3, help="seconds between calls (free-tier rate limits)")
    args = ap.parse_args()
    ds = json.loads(DS.read_text())
    b = load_bundle(ds["pack_id"])
    ok, misses = 0, []
    for row in ds["prompts"]:
        try:
            d = compile_directive(row["text"], b.pack, b.vocab, known_ids=b.known_ids(row["scope_id"]), use_cache=False)
            got = ("ok", d.type, d.target.kind, d.target.value)
        except DirectiveError as e:
            got = ("reject", e.code, e.detail[:80])
        if score(row, got):
            ok += 1
        else:
            misses.append((row["id"], row["text"], got))
        time.sleep(args.pause)
    print(f"directive eval: {ok}/{len(ds['prompts'])}")
    for m in misses:
        print("  miss", m)
    return 0 if ok >= args.min else 1


if __name__ == "__main__":
    sys.exit(main())
