"""Conformance (A4): the 5 contract checks, run against any pack. A pack activates only on 5/5 under provenance.

The fixture is synthesised from the pack definition (edge_types, gate, decay) in throwaway scopes, so a new pack
needs no test code. Fixture graph in scope A (E = evidence kind, D = derived kind):
    e1, e2 -> T        target, retracted in check 1
    e2, e3 -> S        sibling: shares e2, keeps e3 of its own
    e4     -> U
    e5     -> V        e5 expires (check 4)
    d1 [T]   d2 [T, U]   d3 [U]   d4 [V]
Scope B holds its own evidence for check 3.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

from core import engine
from core.db import now
from core.engine import CoreError

NAMES = ["retraction_recalls_dependents", "independent_support_preserved", "no_cross_scope_reads",
         "expiry_removes_memory_and_dependents", "gated_content_never_enters_memory"]
SESSIONS = 3
COLLS = ("events", "nodes", "edges", "decisions", "directives")


def _values(rule):
    """(scope_value, pass_value, fail_value) for a gate rule, from its operator alone."""
    op, fixed = rule["op"], rule.get("value")
    num = {"lt": (5, 1, 9), "lte": (5, 1, 9), "gt": (5, 9, 1), "gte": (5, 9, 1)}
    if op in num:
        if fixed is not None and not rule.get("value_from_scope"):
            return fixed, (fixed - 1 if op in ("lt", "lte") else fixed + 1), (fixed + 1 if op in ("lt", "lte") else fixed - 1)
        return num[op]
    if op in ("eq", "ne"):
        v = fixed if fixed is not None and not rule.get("value_from_scope") else "x"
        return (v, v, f"{v}_other") if op == "eq" else (v, f"{v}_other", v)
    v = fixed if fixed is not None and not rule.get("value_from_scope") else ["x"]
    return (v, v[0], f"{v[0]}_other") if op == "in" else (v, f"{v[0]}_other", v[0])


def _cleanup(db, pid, scopes):
    for c in COLLS:
        db[c].delete_many({"pack_id": pid, "scope_id": {"$in": scopes}})


def run(db, pack_id, pol="provenance", record=True):
    pack = engine.get_pack(db, pack_id)
    et = engine._evidence_edge(pack)
    if not et:
        raise CoreError("bad_request", "pack needs an edge_type between two node types")
    run_id = uuid.uuid4().hex[:6]
    A, B = f"conf_{run_id}_a", f"conf_{run_id}_b"
    gates = pack.get("gate") or []
    profile = {r["value_from_scope"]: _values(r)[0] for r in gates if r.get("value_from_scope")}
    ok_fields = {r["field"]: _values(r)[1] for r in gates}
    D = et["to"]
    marker = f"zq{run_id}gated"
    checks = []

    def ev(scope, label, derives, ts=None, extra=None):
        payload = {**ok_fields, "text": f"{label} {run_id}", "derives": [{"kind": D, "key": k} for k in derives],
                   **(extra or {})}
        body = {"pack_id": pack_id, "scope_id": scope, "type": "fixture", "payload": payload}
        if ts:
            body["ts"] = ts
        r = engine.add_event(db, body)
        assert r["admitted"], r
        return r["node_id"]

    def nid(scope, key):
        return f"node_{engine.slug(scope)}_{engine.slug(D)}_{key}"

    def st(i):
        return (db.nodes.find_one({"_id": i}, {"status": 1}) or {}).get("status")

    def dec(scope, keys):
        return engine.create_decision(db, {"pack_id": pack_id, "scope_id": scope, "inputs": [nid(scope, k) for k in keys],
                                           "output": {"fixture": "+".join(keys)}}, actor="conformance")["decision_id"]

    try:
        for s in (A, B):
            engine.add_event(db, {"pack_id": pack_id, "scope_id": s, "type": "scope_profile", "payload": profile})
        decay = pack.get("decay") or {}
        old_ts = None
        if decay.get("kind") in ("ttl", "linear") and decay.get("seconds"):
            old_ts = (datetime.now(timezone.utc) - timedelta(seconds=decay["seconds"] + 3600)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ev(A, "e1", ["t"]), ev(A, "e2", ["t", "s"]), ev(A, "e3", ["s"]), ev(A, "e4", ["u"])
        e5 = ev(A, "e5", ["v"])
        if old_ts is None:  # pack has no decay: exercise the sweep with an explicit expiry on e5
            db.nodes.update_one({"_id": e5}, {"$set": {"expires_at": "2000-01-01T00:00:00Z"}})
        ev(B, "b1", ["t"])
        d1, d2, d3 = dec(A, ["t"]), dec(A, ["t", "u"]), dec(A, ["u"])
        # d4 is created on V before the sweep runs, so expiry has a dependent to recall
        db.nodes.update_one({"_id": nid(A, "v")}, {"$set": {"status": "active"}})
        d4 = engine.create_decision(db, {"pack_id": pack_id, "scope_id": A, "inputs": [nid(A, "v")],
                                         "output": {"fixture": "v"}}, actor="conformance")["decision_id"]
        if old_ts:  # make e5 old enough to have expired under the pack's own decay
            db.nodes.update_one({"_id": e5}, {"$set": {"expires_at": old_ts}})

        # 1 retraction recalls dependents, and the target stays retracted over sessions
        T = nid(A, "t")
        out = engine.retract(db, {"pack_id": pack_id, "scope_id": A, "target_id": T, "reason": "conformance"}, pol,
                             actor="conformance")
        t0 = now()
        seen, modes = [], set()
        for _ in range(SESSIONS):
            sr = engine.search(db, {"pack_id": pack_id, "scope_id": A, "query": f"{D} t", "k": 10})
            res = sr["results"]
            modes.add(sr["mode"])
            seen.append(st(T) == "active" or any(r["node_id"] == T for r in res))
        rederived = db.history.count_documents({"scope_id": A, "action": "rederived", "target": T, "ts": {"$gte": t0}})
        d1_doc = db.decisions.find_one({"_id": d1})
        ok1 = d1 in out["replayed"] and d1_doc["status"] == "replayed" and not any(seen) and rederived == 0
        checks.append((ok1, f"policy={pol}; d1 replayed={d1 in out['replayed']}; target active in "
                            f"{sum(seen)}/{SESSIONS} sessions; re-derived {rederived}x; evidence retracted "
                            f"{len(out['trace']['evidence']) if pol == 'provenance' else 0}; search {'/'.join(sorted(modes))}"))

        # 2 independent support preserved: d2 keeps U; sibling S keeps its own evidence e3
        acts = {(a["id"], a["action"]) for a in out["plan"]["actions"]}
        S, U = nid(A, "s"), nid(A, "u")
        ok2 = ((d2, "preserve") in acts and db.decisions.find_one({"_id": d2})["status"] == "active"
               and st(S) == "active" and st(U) == "active" and (d3, "invalidate") not in acts)
        checks.append((ok2, f"d2 preserved={(d2, 'preserve') in acts}; sibling {st(S)}; untouched d3 "
                            f"{db.decisions.find_one({'_id': d3})['status']}"))

        # 3 no cross-scope reads
        bnode = nid(B, "t")
        leaks = [r["node_id"] for r in engine.search(db, {"pack_id": pack_id, "scope_id": A, "query": f"b1 {run_id}",
                                                           "k": 20})["results"] if not r["node_id"].startswith(f"node_{engine.slug(A)}")]
        refused = 0
        for fn in (lambda: engine.create_decision(db, {"pack_id": pack_id, "scope_id": A, "inputs": [bnode]}),
                   lambda: engine.retract(db, {"pack_id": pack_id, "scope_id": A, "target_id": bnode}, pol),
                   lambda: engine.why(db, d3, pack_id, B)):
            try:
                fn()
            except CoreError as e:
                refused += e.code == "scope_violation"
        prov = engine.why(db, d2, pack_id, A)["provenance"]
        foreign = [p for p in prov if p["node_id"].startswith(f"node_{engine.slug(B)}") or "_b_" in p["node_id"]]
        ok3 = not leaks and refused == 3 and not foreign and st(bnode) == "active"
        checks.append((ok3, f"{len(leaks)} foreign search hits; {refused}/3 cross-scope calls refused; "
                            f"{len(foreign)} foreign provenance; B memory {st(bnode)} after A's retraction"))

        # 4 expiry removes memory and dependents (status sweep, recorded in the ledger)
        engine.refresh(db, pack_id, A)
        d4_doc = db.decisions.find_one({"_id": d4})
        ok4 = st(e5) == "expired" and st(nid(A, "v")) != "active" and d4_doc["status"] == "replayed"
        checks.append((ok4, f"evidence {st(e5)}; dependent memory {st(nid(A, 'v'))}; decision {d4_doc['status']}; "
                            f"ledger expired={db.history.count_documents({'scope_id': A, 'action': 'expired'})}"))

        # 5 gated content never enters memory (fail closed on a failing or missing gate field)
        if not gates:
            checks.append((True, "pack has no gate rules"))
        else:
            r = gates[0]
            bad = engine.add_event(db, {"pack_id": pack_id, "scope_id": A, "type": "fixture",
                                        "payload": {**ok_fields, r["field"]: _values(r)[2], "text": marker}})
            missing = engine.add_event(db, {"pack_id": pack_id, "scope_id": A, "type": "fixture",
                                            "payload": {k: v for k, v in ok_fields.items() if k != r["field"]}
                                            | {"text": marker}})
            stored = sum(db[c].count_documents({"$or": [{"text": {"$regex": marker}}, {"payload.text": marker},
                                                        {"after": {"$regex": marker}}]}) for c in ("events", "nodes", "history"))
            ok5 = not bad["admitted"] and not missing["admitted"] and stored == 0
            checks.append((ok5, f"failing value admitted={bad['admitted']}; missing field admitted={missing['admitted']}; "
                                f"{stored} stored traces of gated content"))
    finally:
        _cleanup(db, pack_id, [A, B])

    result = {"passed": sum(c[0] for c in checks), "total": 5, "policy": pol,
              "checks": [{"id": i + 1, "name": NAMES[i], "passed": c[0], "detail": c[1]} for i, c in enumerate(checks)]}
    if record:
        key = "conformance" if pol == "provenance" else "conformance_baseline"
        db.packs.update_one({"pack_id": pack_id}, {"$set": {key: {**result, "ts": now()}}})
    return result


def main():
    import argparse
    import json
    from pathlib import Path

    from core.db import ensure, get_db

    ap = argparse.ArgumentParser()
    ap.add_argument("packs", nargs="*", help="pack JSON files to install as drafts before running")
    ap.add_argument("--pack-id", action="append", default=[])
    ap.add_argument("--activate", action="store_true")
    a = ap.parse_args()
    db = get_db()
    ensure(db, vector=False)
    ids = list(a.pack_id)
    for f in a.packs:
        p = json.loads(Path(f).read_text())
        db.packs.update_one({"pack_id": p["pack_id"]}, {"$set": {"slots": {k: v for k, v in p.items() if k != "pack_id"},
                                                                  "status": "draft"}}, upsert=True)
        ids.append(p["pack_id"])
    lines = []
    for pid in ids:
        for pol in ("provenance", "label_only"):
            r = run(db, pid, pol)
            lines.append(f"[{pid}] policy={pol}: {r['passed']}/5")
            lines += [f"  {c['id']} {'PASS' if c['passed'] else 'FAIL'} {c['name']}: {c['detail']}" for c in r["checks"]]
            if pol == "provenance" and a.activate and r["passed"] == 5:
                db.packs.update_one({"pack_id": pid}, {"$set": {"status": "active"}})
                lines.append(f"  -> {pid} ACTIVE")
    print("\n".join(lines))
    out = Path(os.path.dirname(os.path.abspath(__file__))) / "fixtures" / "runs"
    out.mkdir(exist_ok=True)
    (out / "conformance_log.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
