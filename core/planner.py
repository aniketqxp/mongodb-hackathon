"""Pure retraction planner (A2). No database, no I/O: graph JSON in, plan JSON out (CONTRACT section 6).

The Rust crate (G3) must produce the same plan for the same {graph, fault}; core/fixtures/ holds the shared cases.

Graph shape: {"nodes": [{_id, status}], "edges": [{from, to, rel}], "decisions": [{_id, inputs, status}]}.
A node with no incoming node->node edge is *evidence*; a node with one is *derived*.

Derivation rule: a derived node is active if and only if at least one supporter is active (evidence active, or a
derived supporter active). It is a pure function of evidence, under both policies. That is what makes the naive
policy fail on its own: if the evidence stays active, the next recompute brings the retracted node back.

Policies:
  provenance  retract the fault's upstream evidence (status `retracted`, never deleted), then recompute
  label_only  only mark the fault; its evidence stays active (naive baseline)
"""
from collections import defaultdict

POLICIES = ("provenance", "label_only")


def _act(i, action, reason=None):
    return {"id": i, "action": action, "reason": reason}


def index(graph):
    nodes = {n["_id"]: n for n in graph["nodes"]}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for e in graph["edges"]:
        if e["from"] in nodes and e["to"] in nodes:
            incoming[e["to"]].append(e["from"])
            outgoing[e["from"]].append(e["to"])
    return nodes, incoming, outgoing


def ancestors(x, incoming):
    seen, stack = set(), [x]
    while stack:
        for p in incoming[stack.pop()]:
            if p not in seen:
                seen.add(p)
                stack.append(p)
    return seen


def descendants(xs, outgoing):
    seen, stack = set(), list(xs)
    while stack:
        for c in outgoing[stack.pop()]:
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def derive(nodes, incoming, status, forced_down=()):
    """Which derived nodes are supported, given current statuses. Returns {derived_id: bool}."""
    derived = [i for i in nodes if incoming[i]]
    on = {i: False for i in derived}
    for _ in range(len(derived) + 1):
        changed = False
        for i in derived:
            v = i not in forced_down and any(
                (on[p] if p in on else status.get(p) == "active") for p in incoming[i])
            if v != on[i]:
                on[i], changed = v, True
        if not changed:
            break
    return on


def repair_decisions(decisions, down, status):
    """Decision stage shared by retraction and expiry: independent-support check, then invalidate + replay."""
    actions = []
    for d in sorted(decisions, key=lambda d: d["_id"]):
        if d.get("status", "active") != "active" or not set(d["inputs"]) & down:
            continue
        rest = [i for i in d["inputs"] if i not in down and status.get(i) == "active"]
        if rest:
            actions.append(_act(d["_id"], "preserve", "independent_support"))
        else:
            actions += [_act(d["_id"], "invalidate", "lost_all_support"), _act(d["_id"], "replay", None)]
    return actions


def plan(graph, fault, policy="provenance"):
    """Returns (plan, new_status, trace). new_status maps node id -> status after the plan."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    nodes, incoming, outgoing = index(graph)
    status = {i: n.get("status", "active") for i, n in nodes.items()}
    new = dict(status)
    actions = []
    anc = ancestors(fault, incoming)
    evidence = sorted(a for a in anc if not incoming[a] and status[a] == "active")

    if fault in nodes:
        new[fault] = "invalidated"
        actions.append(_act(fault, "delete", None))
    if policy == "provenance":
        for ev in evidence:
            new[ev] = "retracted"
            actions.append(_act(ev, "retract", "evidence_of_fault"))

    on = derive(nodes, incoming, new, forced_down={fault})
    for i in sorted(on):
        if i != fault and status[i] == "active" and not on[i]:
            new[i] = "quarantined"
            actions.append(_act(i, "quarantine", "no_active_support"))

    # siblings: other derived nodes built from the same evidence that stay active
    siblings = sorted(descendants(evidence, outgoing) - {fault} - anc)
    for s in siblings:
        if new[s] == "active":
            own = [p for p in ancestors(s, incoming) if not incoming[p] and new[p] == "active" and p not in evidence]
            actions.append(_act(s, "preserve", "independent_support" if own else "evidence_still_active"))

    down = {i for i in nodes if status[i] == "active" and new[i] != "active"}
    actions += repair_decisions(graph["decisions"], down, new)
    trace = {"evidence": evidence, "siblings": siblings,
             "down": sorted(down), "decisions": sorted({a["id"] for a in actions} & {d["_id"] for d in graph["decisions"]})}
    return {"fault": fault, "actions": actions}, new, trace
