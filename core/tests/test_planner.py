"""Offline planner tests (no DB): the team scenario plus the shared fixtures for the Rust planner (G3)."""
import json
import os
from pathlib import Path

import pytest

from core import planner

ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
FIX = ROOT / "core" / "fixtures"


def _seed():
    g = json.loads((ROOT / "data" / "graph.json").read_text())
    sc = json.loads((ROOT / "data" / "scenario.json").read_text())
    q = lambda xs: [x for x in xs if x["scope_id"] == sc["scope_id"]]
    return {"nodes": q(g["nodes"]), "edges": q(g["edges"]), "decisions": q(g["decisions"])}, sc


@pytest.mark.parametrize("policy", planner.POLICIES)
def test_scenario(policy):
    g, sc = _seed()
    plan, new, _ = planner.plan(g, sc["retract"], policy)
    acts = {(a["id"], a["action"]) for a in plan["actions"]}
    for d in sc["expect_invalidate_and_replay"]:
        assert (d, "invalidate") in acts and (d, "replay") in acts
    for d in sc["expect_preserve_independent_support"]:
        assert (d, "preserve") in acts
    retracted = [i for i, s in new.items() if s == "retracted"]
    assert bool(retracted) == (policy == "provenance")


def test_creep_back_emerges_only_under_label_only():
    g, sc = _seed()
    for policy, comes_back in (("label_only", True), ("provenance", False)):
        _, new, _ = planner.plan(g, sc["retract"], policy)
        nodes, incoming, _ = planner.index(g)
        on = planner.derive(nodes, incoming, new)  # the next recompute, identical for both policies
        assert on[sc["retract"]] is comes_back


@pytest.mark.parametrize("path", sorted(FIX.glob("plan_*.json")), ids=lambda p: p.stem)
def test_fixture(path):
    f = json.loads(path.read_text())
    for policy, expected in f["expected"].items():
        assert planner.plan(f["graph"], f["fault"], policy)[0] == expected
