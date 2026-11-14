"""Real numbers for the film (demo/film.html). Offline and deterministic: no database, no LLM, no network.

It replays the team's own pieces on the seed data in data/:
  memory   harness.memory.SeedMemory         (the interest nodes the feed is built from)
  feed     harness.slate.build_slate         (the same slate generator the live UI uses)
  recall   core.planner.plan / derive        (the same planner the core runs, provenance policy)
so every title, count and "stays forgotten" tick in the film comes from the same code as the live demo.

  python -m demo.film_data          write demo/film_data.js (the film also works from disk with that file)
Served live at /film_data.js by demo.split.
"""
import json
from pathlib import Path

from core import planner
from harness import data
from harness.memory import SeedMemory
from harness.slate import build_slate, node_topic

HERE = Path(__file__).resolve().parent
SIZE = 6
SESSIONS = (2, 3, 4)


def _scope_graph(scope_id):
    g = data.graph()
    q = lambda xs: [x for x in xs if x["scope_id"] == scope_id]
    return {"nodes": q(g["nodes"]), "edges": q(g["edges"]), "decisions": q(g["decisions"])}


def build(scope_id=None, size=SIZE):
    sc = json.loads((data.DATA / "scenario.json").read_text())
    scope_id = scope_id or sc["scope_id"]
    fault = sc["retract"]
    pack_id = data.pack()["pack_id"]
    graph = _scope_graph(scope_id)
    topics = sorted({v["topic"] for v in data.catalog()})

    nodes = SeedMemory().search(pack_id, scope_id, k=50)
    by_id = {n["node_id"]: n for n in nodes}
    topic_of = {n["node_id"]: node_topic(n, topics) for n in nodes}
    nidx, incoming, _ = planner.index(graph)

    memories = [{"id": n["node_id"], "topic": topic_of[n["node_id"]], "text": n["text"],
                 "watches": len(planner.ancestors(n["node_id"], incoming)), "score": n["score"]} for n in nodes]

    before = build_slate(scope_id, nodes, [], size)["slate"]

    plan, new, trace = planner.plan(graph, fault, "provenance")
    nodes_after = [n for n in nodes if new.get(n["node_id"], "active") == "active"]
    after = build_slate(scope_id, nodes_after, [], size, previous=[e["video_id"] for e in before])["slate"]
    before_ids, after_ids = {e["video_id"] for e in before}, {e["video_id"] for e in after}

    def row(e):
        return {"video_id": e["video_id"], "title": e["title"], "topic": e["topic"],
                "mem": [topic_of[s] for s in e["supports"] if s in topic_of],
                "via_fault": fault in e["supports"]}

    # the next sessions: re-derive from the evidence that is left, then rebuild the feed (nothing is scripted)
    on = planner.derive(nidx, incoming, new)
    fault_topic = topic_of[fault]
    sessions = []
    for n in SESSIONS:
        feed = build_slate(scope_id, nodes_after, [], size, previous=[e["video_id"] for e in after])["slate"]
        sessions.append({"n": n, "fault_active": bool(on.get(fault)),
                         "fault_items": sum(1 for e in feed if fault in e["supports"])})
    naive_plan, naive_new, _ = planner.plan(graph, fault, "label_only")
    naive_on = planner.derive(nidx, incoming, naive_new)

    acts = plan["actions"]
    ids = lambda a: sorted({x["id"] for x in acts if x["action"] == a and x["id"] in {d["_id"] for d in graph["decisions"]}})
    return {
        "scope": {"id": scope_id, "label": data.scopes()[scope_id]["label"],
                  "max_maturity": data.scope_profile(scope_id).get("max_maturity")},
        "memories": memories,
        "retracted": {"id": fault, "topic": fault_topic, "evidence": len(trace["evidence"])},
        "before": [row(e) for e in before],
        "after": [row(e) for e in after],
        "removed": [e["video_id"] for e in before if e["video_id"] not in after_ids],
        "kept_independent": [e["video_id"] for e in before if fault in e["supports"] and e["video_id"] in after_ids],
        "added": [e["video_id"] for e in after if e["video_id"] not in before_ids],
        "sessions": sessions,
        "proof": {"recalled": ids("invalidate"), "replayed": ids("replay"), "preserved": ids("preserve"),
                  "evidence_retracted": len(trace["evidence"]),
                  "stays_forgotten": not on.get(fault), "naive_comes_back": bool(naive_on.get(fault))},
    }


def js(payload=None):
    return "window.FILM_DATA = " + json.dumps(payload or build(), indent=1) + ";\n"


if __name__ == "__main__":
    (HERE / "film_data.js").write_text(js())
    d = build()
    print("wrote demo/film_data.js:", d["scope"]["label"], "| removed", d["removed"], "| kept", d["kept_independent"],
          "| added", d["added"], "| proof", d["proof"])
