"""D3 offline evidence: retract-one matches data/scenario.json, and the with/without-memory eval holds."""
import copy
import json

import pytest

from eval import memory_eval, retract_one


@pytest.fixture(scope="module")
def r1():
    return retract_one.run()


def test_retract_one_matches_scenario(r1):
    scn = r1["scenario"]
    assert r1["passed"], r1["decision_check"]["problems"] + r1["slate_diff"]["problems"]
    assert r1["decision_check"]["recalled"] == sorted(scn["expect_invalidate_and_replay"])
    assert r1["decision_check"]["preserved"] == scn["expect_preserve_independent_support"]


def test_retract_one_slate_only_dependents_move(r1):
    sd = r1["slate_diff"]
    assert sd["changed"] and sd["preserved_with_independent_support"]
    assert set(sd["unrelated_kept"]) <= set(sd["after"])
    assert not set(sd["changed"]) & set(sd["after"])


def test_check_plan_catches_overeager_planner():
    graph, scn = retract_one._load("graph.json"), retract_one._load("scenario.json")
    plan = retract_one.reference_plan(graph, scn["scope_id"], scn["retract"])
    bad = copy.deepcopy(plan)
    for a in bad["actions"]:
        if a["action"] == "preserve":
            a["action"] = "invalidate"
    bad["actions"].append({"id": "dec_child_7_00", "action": "invalidate", "reason": None})
    res = retract_one.check_plan(bad, graph, scn)
    assert not res["passed"] and len(res["problems"]) >= 2


@pytest.fixture(scope="module")
def me():
    return memory_eval.run(live=False)


def test_memory_eval_all_rows_correct_both_modes(me):
    for mode in ("with_memory", "without_memory"):
        assert me["summary"][mode]["gate_respected"] == 1
        assert me["summary"][mode]["effect_correct"] == 1


def test_memory_changes_behaviour(me):
    assert me["summary"]["with_memory"]["personalized"] >= 0.8
    assert me["summary"]["without_memory"]["personalized"] == 0
    assert me["n"] == 25


def test_rejected_prompts_leave_slate_unchanged(me):
    rej = [r for r in me["rows"] if r["outcome"]["kind"] == "rejected"]
    assert len(rej) == 7
    assert all(r["with_memory"]["slate"] == r["with_memory"]["baseline"] for r in rej)


def test_trace_flag_is_noop_without_key(monkeypatch):
    from eval import tracing

    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    assert tracing.enable_for_run(True) is False
    assert tracing.enabled() is False


def test_trace_flag_turns_on_with_key(monkeypatch):
    from eval import tracing

    monkeypatch.setenv("LANGSMITH_API_KEY", "x")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    assert tracing.enable_for_run(True) is True
