"""Demo path and creep-back measurement on the team seed (data/graph.json, data/scenario.json), via the real routes.

  python -m core.demo            reseed, run both policies, write core/fixtures/runs/creep_back_seed.json

For each policy: reseed the pack, retract the scenario target, then run 3 sessions. Each session is one
POST /memory/search for the target's own text; search runs refresh() first (expiry sweep + recompute), the
same code under both policies. Nothing in this file marks the target active again.
"""
import json
import os
import runpy
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from core.db import _load_env, ensure, get_db, now

ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
SESSIONS = 3


def reseed():
    _load_env()
    ensure(get_db(), vector=False)  # contract validators first, so the team seed is accepted
    argv = sys.argv
    sys.argv = ["seed.py"]
    try:
        runpy.run_path(str(ROOT / "data" / "seed.py"), run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            raise
    finally:
        sys.argv = argv
    db = get_db()
    ensure(db, vector=False)
    from core.engine import backfill_embeddings
    pack_id = json.loads((ROOT / "data" / "pack_video.json").read_text())["pack_id"]
    backfill_embeddings(db, pack_id)  # seed nodes carry no embeddings; no-op without VOYAGE_API_KEY
    return db


def run_policy(client, db, sc, pack_id, pol):
    os.environ["RETRACTION_POLICY"] = pol
    reseed()
    sid, target = sc["scope_id"], sc["retract"]
    text = db.nodes.find_one({"_id": target})["text"]

    def probe():
        r = client.post("/memory/search", json={"pack_id": pack_id, "scope_id": sid, "query": text, "k": 5}).json()
        ids = [x["node_id"] for x in r["results"]]
        return {"status": db.nodes.find_one({"_id": target})["status"],
                "rank": ids.index(target) + 1 if target in ids else None, "mode": r.get("mode")}

    before = probe()
    t0 = now()  # the ledger is append-only across runs; count only this run's entries
    r = client.post("/retract", json={"pack_id": pack_id, "scope_id": sid, "target_id": target, "reason": "demo"})
    r.raise_for_status()
    out = r.json()
    sessions = [probe() for _ in range(SESSIONS)]
    d = client.get("/diff", params={"pack_id": pack_id, "scope_id": sid, "retract": target}).json()
    first = out["replay_map"].get(sc["expect_invalidate_and_replay"][0])
    w = client.get(f"/why/{first}", params={"pack_id": pack_id, "scope_id": sid}).json() if first else None
    rederived = db.history.count_documents({"scope_id": sid, "action": "rederived", "target": target,
                                      "ts": {"$gte": t0}})
    acts = out["plan"]["actions"]
    return {"policy": pol, "before": before, "sessions": sessions, "rederived_events": rederived,
            "evidence_retracted": sorted(a["id"] for a in acts if a["action"] == "retract"),
            "invalidated": sorted({a["id"] for a in acts if a["action"] == "invalidate"}),
            "preserved": sorted({a["id"] for a in acts if a["action"] == "preserve" and a["id"].startswith("dec")}),
            "replayed": out["replayed"], "plan": out["plan"], "diff": d, "why_first_replay": w}


def main():
    from core.api import app
    sc = json.loads((ROOT / "data" / "scenario.json").read_text())
    pack_id = json.loads((ROOT / "data" / "pack_video.json").read_text())["pack_id"]
    db = reseed()
    client = TestClient(app)
    res = [run_policy(client, db, sc, pack_id, p) for p in ("label_only", "provenance")]
    reseed()  # leave the shared seed clean for teammates
    ok = {r["policy"]: (r["invalidated"] == sorted(sc["expect_invalidate_and_replay"]) and
                        set(sc["expect_preserve_independent_support"]) <= set(r["preserved"])) for r in res}
    print(f"target {sc['retract']} in scope {sc['scope_id']}; {SESSIONS} sessions after retract\n")
    print(f"{'policy':<12} {'before':<14} " + " ".join(f"{'+' + str(i + 1):<16}" for i in range(SESSIONS))
          + " evidence retracted  scenario match")
    for r in res:
        cell = lambda p: f"{p['status']}/rank {p['rank'] or '-'}"
        print(f"{r['policy']:<12} {cell(r['before']):<14} " + " ".join(f"{cell(s):<16}" for s in r["sessions"])
              + f" {len(r['evidence_retracted']):<19} {ok[r['policy']]}  (re-derived {r['rederived_events']}x)")
    modes = sorted({p["mode"] for r in res for p in [r["before"], *r["sessions"]]})
    print(f"\nsearch mode: {', '.join(m or '?' for m in modes)}")
    out = ROOT / "core" / "fixtures" / "runs"
    out.mkdir(exist_ok=True)
    name = f"creep_back_seed{'_vector' if modes == ['vector'] else ''}.json"
    (out / name).write_text(json.dumps(res, indent=2, default=str) + "\n")
    print(f"wrote core/fixtures/runs/{name}")
    return 0 if all(ok.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
