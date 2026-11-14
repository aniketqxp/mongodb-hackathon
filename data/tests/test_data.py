import json
from collections import Counter
from pathlib import Path

D = Path(__file__).parent.parent
cat = json.loads((D / "catalog.json").read_text())
graph = json.loads((D / "graph.json").read_text())
pack = json.loads((D / "pack_video.json").read_text())
scn = json.loads((D / "scenario.json").read_text())
SCHEMA_SLOTS = {"pack_id", "scope_field", "node_types", "edge_types", "gate", "decay", "directive_vocab", "labels"}


def test_catalog_size_and_ids():
    assert len(cat) == 200
    assert len({v["video_id"] for v in cat}) == 200
    assert all(v["maturity"] in (0, 1, 2, 3) for v in cat)
    assert Counter(v["maturity"] for v in cat)[3] > 0  # something the gate must block


def test_pack_matches_contract_slots():
    assert set(pack) == SCHEMA_SLOTS
    assert set(pack["directive_vocab"]) == {"suppress", "prioritize", "retract"}


def test_graph_integrity():
    ids = {n["_id"] for n in graph["nodes"]} | {d["_id"] for d in graph["decisions"]}
    for e in graph["edges"]:
        assert e["from"] in ids and e["to"] in ids
        assert e["pack_id"] == pack["pack_id"]
    for d in graph["decisions"]:
        assert all(i in ids for i in d["inputs"])
    for c in graph.values():
        assert all(x["pack_id"] == pack["pack_id"] and x["scope_id"] for x in c)


def test_scopes_do_not_share_ids_or_edges():
    nodes = {n["_id"]: n["scope_id"] for n in graph["nodes"]}
    for e in graph["edges"]:
        if e["from"] in nodes and e["to"] in nodes:
            assert nodes[e["from"]] == nodes[e["to"]]
        assert e["scope_id"] == nodes.get(e["from"], e["scope_id"])


def test_scenario_has_dependent_and_independent_cases():
    assert scn["expect_invalidate_and_replay"], "need decisions that depend only on the fault"
    assert scn["expect_preserve_independent_support"], "need an independently supported decision"
    dec = {d["_id"]: d for d in graph["decisions"]}
    for d in scn["expect_invalidate_and_replay"]:
        assert dec[d]["inputs"] == [scn["retract"]]
    for d in scn["expect_preserve_independent_support"]:
        assert scn["retract"] in dec[d]["inputs"] and len(dec[d]["inputs"]) > 1


def test_gate_would_block_something_in_each_scope():
    scopes = {s["scope_id"]: s["max_maturity"] for s in json.loads((D / "scopes.json").read_text())}
    by_id = {v["video_id"]: v for v in cat}
    for sid, mx in scopes.items():
        outs = [by_id[d["output"]["video_id"]]["maturity"] for d in graph["decisions"] if d["scope_id"] == sid]
        assert outs, sid
    assert any(by_id[d["output"]["video_id"]]["maturity"] > scopes["child_7"]
               for d in graph["decisions"] if d["scope_id"] == "child_7")
