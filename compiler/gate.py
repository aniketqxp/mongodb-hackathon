"""Domain-neutral gate maths shared by the pack compiler and the conformance suite.

evaluate(): does a payload pass the pack's gate? synthesize(): build payloads that pass the gate,
and for each rule one payload that fails it. A pack whose gate cannot be passed is rejected.
"""
from __future__ import annotations

from typing import Any

from compiler.schemas import GateRule

NUMERIC_OPS = {"gt", "gte", "lt", "lte"}
OUT_SENTINEL = "__conformance_out__"
DEFAULT_NUM_REF = 2


def ref_value(rule: GateRule, profile: dict) -> Any:
    return profile.get(rule.value_from_scope) if rule.value_from_scope else rule.value


def check(rule: GateRule, x: Any, profile: dict) -> bool:
    v = ref_value(rule, profile)
    try:
        if rule.op == "eq":
            return x == v
        if rule.op == "ne":
            return x != v
        if rule.op == "in":
            return x in v
        if rule.op == "not_in":
            return x not in v
        if not isinstance(x, (int, float)) or not isinstance(v, (int, float)) or isinstance(x, bool):
            return False
        return {"gt": x > v, "gte": x >= v, "lt": x < v, "lte": x <= v}[rule.op]
    except TypeError:
        return False


def evaluate(gate: list[GateRule], payload: dict, profile: dict) -> bool:
    return all(r.field in payload and check(r, payload[r.field], profile) for r in gate)


def default_profile(gate: list[GateRule]) -> dict:
    """Scope-profile values the suite sets for rules that read their threshold from the scope."""
    prof: dict = {}
    for r in gate:
        if r.value_from_scope and r.value_from_scope not in prof:
            if r.op in ("in", "not_in"):
                prof[r.value_from_scope] = ["conf_ref_a", "conf_ref_b"]
            elif r.op in ("eq", "ne"):
                prof[r.value_from_scope] = "conf_ref_a"
            else:
                prof[r.value_from_scope] = DEFAULT_NUM_REF
    return prof


def _candidates(rule: GateRule, profile: dict) -> list:
    v = ref_value(rule, profile)
    if isinstance(v, list):
        return [*v, OUT_SENTINEL]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [v - 1, v, v + 1]
    return [v, f"{v}_x" if v is not None else OUT_SENTINEL]


def synthesize(gate: list[GateRule], profile: dict) -> tuple[dict | None, list[tuple[int, dict]]]:
    """Return (passing payload or None, [(rule index, payload failing that rule), ...])."""
    fields: dict[str, list[GateRule]] = {}
    for r in gate:
        fields.setdefault(r.field, []).append(r)
    passing: dict = {}
    for f, rules in fields.items():
        cands = [c for r in rules for c in _candidates(r, profile)]
        ok = next((c for c in cands if all(check(r, c, profile) for r in rules)), None)
        if ok is None and not any(c is None for c in cands):
            return None, []
        passing[f] = ok
    failing = []
    for i, r in enumerate(gate):
        bad = next((c for c in _candidates(r, profile) if not check(r, c, profile)), None)
        if bad is not None:
            failing.append((i, {**passing, r.field: bad}))
    return passing, failing
