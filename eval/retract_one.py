"""Headline test: retract ONE memory, prove only its dependents changed (data/scenario.json).

  python -m eval.retract_one                    offline: seed graph + reference support rule
  python -m eval.retract_one --core URL         live: core POST /retract (A2 planner via A3)

Checks:
  1. decision plan: expected decisions recalled (invalidate/replay), expected ones preserved,
     and no decision that never used the fault changed.
  2. slate diff (harness build_slate): items backed only by the fault leave the slate; items with
     independent support stay; nothing unrelated moves.
Evidence goes to eval/evidence/retract_one.json (and LangSmith when enabled).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval.tracing import enable_for_run, traceable, write_evidence

REPO = Path(__file__).resolve().parents[1]
RECALLED = {"invalidate", "replay"}


def _load(name):
    return json.loads((REPO / "data" / name).read_text())


def reference_plan(graph: dict, scope_id: str, fault: str) -> dict:
    """Support rule, for offline evidence only (A2 owns the real planner): a decision is recalled when
    none of its other inputs is still active, otherwise preserved for independent support."""
    active = {n["_id"] for n in graph["nodes"] if n["scope_id"] == scope_id and n["status"] == "active"} - {fault}
    actions = [{"id": fault, "action": "delete", "reason": None}]
    for d in graph["decisions"]:
        if d["scope_id"] != scope_id or fault not in d["inputs"]:
            continue
        if any(i in active for i in d["inputs"] if i != fault):
            actions.append({"id": d["_id"], "action": "preserve", "reason": "independent_support"})
        else:
            actions += [{"id": d["_id"], "action": "invalidate", "reason": None}, {"id": d["_id"], "action": "replay", "reason": None}]
    return {"fault": fault, "actions": actions}


def live_plan(core_url: str, pack_id: str, scope_id: str, fault: str) -> dict:
    import httpx

    r = httpx.post(core_url.rstrip("/") + "/retract",
                   json={"pack_id": pack_id, "scope_id": scope_id, "target_id": fault, "reason": "eval:retract_one"}, timeout=30)
    r.raise_for_status()
    return r.json()["plan"]


def live_diff(core_url: str, pack_id: str, scope_id: str, fault: str) -> dict:
    """Core's own GET /diff for the same retraction, recorded as evidence next to ours."""
    import httpx

    r = httpx.get(core_url.rstrip("/") + "/diff", params={"pack_id": pack_id, "scope_id": scope_id, "retract": fault}, timeout=30)
    return r.json() if r.status_code < 400 else {"error": r.status_code}


def check_plan(plan: dict, graph: dict, scn: dict) -> dict:
    by_id: dict[str, set] = {}
    for a in plan.get("actions", []):
        by_id.setdefault(a["id"], set()).add(a["action"])
    recalled = {i for i, a in by_id.items() if a & RECALLED}
    preserved = {i for i, a in by_id.items() if "preserve" in a and not a & RECALLED}
    scope_decs = {d["_id"]: d for d in graph["decisions"] if d["scope_id"] == scn["scope_id"]}
    untouched = {i for i, d in scope_decs.items() if scn["retract"] not in d["inputs"]}
    exp_recall, exp_keep = set(scn["expect_invalidate_and_replay"]), set(scn["expect_preserve_independent_support"])
    problems = []
    if recalled & scope_decs.keys() != exp_recall:
        problems.append(f"recalled {sorted(recalled & scope_decs.keys())}, expected {sorted(exp_recall)}")
    if not exp_keep <= preserved and exp_keep & recalled:
        problems.append(f"independently supported {sorted(exp_keep & recalled)} was recalled")
    if untouched & recalled:
        problems.append(f"decisions that never used the fault changed: {sorted(untouched & recalled)}")
    return {"passed": not problems, "problems": problems, "recalled": sorted(recalled & scope_decs.keys()),
            "preserved": sorted(exp_keep - recalled), "untouched": len(untouched)}


def slate_diff(scope_id: str, fault: str) -> dict:
    from harness.memory import SeedMemory
    from harness.slate import build_slate

    mem = SeedMemory()
    pack_id = _load("pack_video.json")["pack_id"]
    nodes = mem.search(pack_id, scope_id, k=20)
    before = build_slate(scope_id, nodes, size=8)["slate"]
    after = build_slate(scope_id, [n for n in nodes if n["node_id"] != fault], size=8,
                        previous=[i["video_id"] for i in before])["slate"]
    a_ids = {i["video_id"] for i in after}
    removed = [i for i in before if i["video_id"] not in a_ids]
    kept = [i for i in before if i["video_id"] in a_ids]
    problems = []
    for i in removed:
        if set(i["supports"]) - {fault}:
            problems.append(f"{i['video_id']} had independent support but left the slate")
    for i in kept:
        if set(i["supports"]) <= {fault}:
            problems.append(f"{i['video_id']} was backed only by the fault but stayed")
    if not any(fault in i["supports"] for i in before):
        problems.append("fault supported nothing on the slate, so the diff proves nothing")
    if any(fault in i["supports"] for i in after):
        problems.append("an item on the new slate still cites the retracted memory")
    return {
        "passed": not problems, "problems": problems,
        "before": [i["video_id"] for i in before], "after": [i["video_id"] for i in after],
        "changed": [i["video_id"] for i in removed],
        "preserved_with_independent_support": [i["video_id"] for i in kept if fault in i["supports"]],
        "unrelated_kept": [i["video_id"] for i in kept if fault not in i["supports"]],
        "added": [i["video_id"] for i in after if i["status"] == "new"],
    }


@traceable("retract_one")
def run(core_url: str | None = None) -> dict:
    graph, scn = _load("graph.json"), _load("scenario.json")
    pack_id = _load("pack_video.json")["pack_id"]
    core_diff = None
    if core_url:
        plan, source = live_plan(core_url, pack_id, scn["scope_id"], scn["retract"]), "core"
        core_diff = live_diff(core_url, pack_id, scn["scope_id"], scn["retract"])
    else:
        plan, source = reference_plan(graph, scn["scope_id"], scn["retract"]), "reference_support_rule"
    out = {"scenario": scn, "planner": source, "plan": plan,
           "decision_check": check_plan(plan, graph, scn), "slate_diff": slate_diff(scn["scope_id"], scn["retract"])}
    if core_diff is not None:
        out["core_diff"] = core_diff
    out["passed"] = out["decision_check"]["passed"] and out["slate_diff"]["passed"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default=None, help="core base URL, e.g. http://localhost:8001")
    ap.add_argument("--trace", action="store_true", help="send this run to LangSmith (needs LANGSMITH_API_KEY)")
    args = ap.parse_args()
    enable_for_run(args.trace)
    out = run(args.core)
    path = write_evidence("retract_one", out)
    dc, sd = out["decision_check"], out["slate_diff"]
    print(f"retract-one ({out['planner']}): {'PASS' if out['passed'] else 'FAIL'}")
    print(f"  decisions recalled {dc['recalled']}, preserved {dc['preserved']}, {dc['untouched']} untouched")
    print(f"  slate changed {sd['changed']} | kept w/ independent support {sd['preserved_with_independent_support']} | unrelated kept {len(sd['unrelated_kept'])}")
    for p in dc["problems"] + sd["problems"]:
        print("  problem:", p)
    print("  evidence:", path.relative_to(REPO))
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
