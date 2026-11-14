"""Governed-memory engine (A2/A3): events, derivation, refresh, decisions, retraction, why, diff.

Domain-neutral: every meaning comes from the pack (node_types, edge_types, gate, decay, directive_vocab).

Derivation. Provenance edges are the source of truth: a derived node is active iff at least one supporter is active
(core/planner.derive). The core writes the edges itself:
  - an admitted event becomes an evidence node (kind = the pack's first edge_type `from` kind), support=[event id],
    plus a provenance edge event -> evidence node;
  - the evidence node is linked to existing derived nodes of the edge_type's `to` kind whose key appears among the
    payload's string values (node id `node_{scope}_{kind}_{key}`), and to `payload.derives` [{kind,key,text}] if given.
Seed graphs that already carry evidence -> derived edges need nothing else.

RETRACTION_POLICY (env, default provenance) selects the planner policy; refresh() is identical under both, so the
naive policy's creep-back falls out of recompute and is never scripted.
"""
import hashlib
import json
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from core import planner
from core.db import ledger, now

PROV_REL = "provenance"  # event -> evidence node


class CoreError(Exception):
    def __init__(self, code, detail, http=400):
        super().__init__(detail)
        self.code, self.detail, self.http = code, detail, http


def policy():
    p = os.getenv("RETRACTION_POLICY", "provenance")
    if p not in planner.POLICIES:
        raise CoreError("bad_request", f"RETRACTION_POLICY must be one of {planner.POLICIES}")
    return p


def _req(body, *fields):
    missing = [f for f in fields if body.get(f) in (None, "")]
    if missing:
        raise CoreError("bad_request", f"missing fields: {missing}")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def get_pack(db, pack_id):
    doc = db.packs.find_one({"pack_id": pack_id})
    if not doc:
        raise CoreError("not_found", f"pack {pack_id}", 404)
    slots = dict(doc.get("slots") or {})
    slots["pack_id"] = pack_id
    return slots


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- graph

def scope_graph(db, pack_id, scope_id):
    q = {"pack_id": pack_id, "scope_id": scope_id}
    return {"nodes": list(db.nodes.find(q, {"embedding": 0})),
            "edges": list(db.edges.find(q, {"_id": 0, "from": 1, "to": 1, "rel": 1})),
            "decisions": list(db.decisions.find(q))}


def _set_status(db, pack_id, scope_id, ids, status, action, reason=None, actor="core"):
    for i in ids:
        old = db.nodes.find_one_and_update({"_id": i, "pack_id": pack_id, "scope_id": scope_id},
                                           {"$set": {"status": status}}, projection={"status": 1})
        if old and old.get("status") != status:
            ledger(db, pack_id, scope_id, action, i, {"status": old.get("status")},
                   {"status": status, "reason": reason}, actor)


# ---------------------------------------------------------------- gate

_OPS = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "gt": lambda a, b: a > b, "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b, "in": lambda a, b: a in b,
        "not_in": lambda a, b: a not in b}


def scope_profile(db, pack_id, scope_id):
    ev = db.events.find_one({"pack_id": pack_id, "scope_id": scope_id, "type": "scope_profile"}, sort=[("ts", -1)])
    return (ev or {}).get("payload") or {}


def gate_check(db, pack, scope_id, payload):
    """Fail closed: a missing field or a missing scope value rejects the event."""
    profile = None
    for rule in pack.get("gate") or []:
        field, op = rule["field"], rule["op"]
        if field not in payload:
            return f"gate:{field}:missing"
        limit = rule.get("value")
        if rule.get("value_from_scope"):
            profile = profile if profile is not None else scope_profile(db, pack["pack_id"], scope_id)
            limit = profile.get(rule["value_from_scope"])
            if limit is None:
                return f"gate:{field}:no_scope_value"
        try:
            if not _OPS[op](payload[field], limit):
                return f"gate:{field}"
        except (KeyError, TypeError):
            return f"gate:{field}:invalid"
    return None


# ---------------------------------------------------------------- events

def _evidence_edge(pack):
    kinds = set(pack.get("node_types") or [])
    for et in pack.get("edge_types") or []:
        if et["from"] in kinds and et["to"] in kinds:
            return et
    return None


def _decision_rel(pack):
    for et in pack.get("edge_types") or []:
        if et["to"] == "decision":
            return et["rel"]
    return "used_in"


def _text(etype, payload):
    if isinstance(payload.get("text"), str):
        return payload["text"]
    parts = [f"{k}={v}" for k, v in payload.items() if isinstance(v, (str, int, float)) and k != "derives"]
    return f"{etype}: " + ", ".join(parts)


def add_event(db, body):
    _req(body, "pack_id", "scope_id", "type")
    pack_id, scope_id, etype = body["pack_id"], body["scope_id"], body["type"]
    payload = body.get("payload") or {}
    if not isinstance(payload, dict):
        raise CoreError("bad_request", "payload must be an object")
    pack = get_pack(db, pack_id)
    ts = body.get("ts") or now()
    if etype == "scope_profile":  # attributes only; never becomes memory
        eid = f"evt_{slug(scope_id)}_{uuid.uuid4().hex[:10]}"
        db.events.insert_one({"_id": eid, "pack_id": pack_id, "scope_id": scope_id, "type": etype, "payload": payload,
                              "ts": ts, "source": body.get("source", "api")})
        ledger(db, pack_id, scope_id, "scope_profile", eid)
        return {"admitted": True, "reason": None, "node_id": None}
    reason = gate_check(db, pack, scope_id, payload)
    if reason:  # nothing about the content is stored: no event, node, edge, or payload in the ledger
        ledger(db, pack_id, scope_id, "gate_rejected", None, None, {"reason": reason, "type": etype})
        return {"admitted": False, "reason": reason, "node_id": None}

    eid = f"evt_{slug(scope_id)}_{uuid.uuid4().hex[:10]}"
    db.events.insert_one({"_id": eid, "pack_id": pack_id, "scope_id": scope_id, "type": etype, "payload": payload,
                          "ts": ts, "source": body.get("source", "api")})
    et = _evidence_edge(pack)
    kind = et["from"] if et else (pack.get("node_types") or ["evidence"])[0]
    decay = pack.get("decay") or {}
    expires = _iso(_parse(ts) + timedelta(seconds=decay["seconds"])) if decay.get("kind") in ("ttl", "linear") \
        and decay.get("seconds") else None
    nid = f"node_{slug(scope_id)}_{slug(kind)}_{eid[-10:]}"
    text = _text(etype, payload)
    db.nodes.insert_one({"_id": nid, "pack_id": pack_id, "scope_id": scope_id, "kind": kind, "text": text,
                         "embedding": embed([text]), "status": "active", "expires_at": expires, "support": [eid]})
    db.edges.insert_one({"pack_id": pack_id, "scope_id": scope_id, "from": eid, "to": nid, "rel": PROV_REL})
    ledger(db, pack_id, scope_id, "evidence_recorded", nid, None, {"event": eid})

    targets = {}
    if et:  # link to existing derived nodes whose key is named in the payload (no domain knowledge needed)
        prefix = f"node_{slug(scope_id)}_{slug(et['to'])}_"
        values = {slug(v) for v in payload.values() if isinstance(v, str)}
        values |= {slug(x) for v in payload.values() if isinstance(v, list) for x in v if isinstance(x, str)}
        for d in db.nodes.find({"pack_id": pack_id, "scope_id": scope_id, "kind": et["to"]}, {"_id": 1}):
            if d["_id"].startswith(prefix) and d["_id"][len(prefix):] in values:
                targets[d["_id"]] = (et["to"], None, et["rel"])
    for d in payload.get("derives") or []:  # optional explicit convention
        rel = next((e["rel"] for e in pack.get("edge_types") or [] if e["from"] == kind and e["to"] == d["kind"]),
                   "supports")
        targets[f"node_{slug(scope_id)}_{slug(d['kind'])}_{slug(d['key'])}"] = (d["kind"], d.get("text"), rel)
    for did, (dkind, dtext, rel) in targets.items():
        if not db.nodes.find_one({"_id": did}, {"_id": 1}):
            t = dtext or f"{dkind}: {did.rsplit('_' + slug(dkind) + '_', 1)[-1].replace('_', ' ')}"
            db.nodes.insert_one({"_id": did, "pack_id": pack_id, "scope_id": scope_id, "kind": dkind, "text": t,
                                 "embedding": embed([t]), "status": "active", "expires_at": None, "support": []})
            ledger(db, pack_id, scope_id, "derived", did, None, {"from": nid})
        db.nodes.update_one({"_id": did}, {"$addToSet": {"support": nid}})
        db.edges.insert_one({"pack_id": pack_id, "scope_id": scope_id, "from": nid, "to": did, "rel": rel})
    refresh(db, pack_id, scope_id)
    return {"admitted": True, "reason": None, "node_id": nid}


# ---------------------------------------------------------------- refresh (recompute + expiry sweep)

def refresh(db, pack_id, scope_id):
    """Expiry sweep, then recompute derived nodes from active evidence. Same code under both policies."""
    t = now()
    q = {"pack_id": pack_id, "scope_id": scope_id}
    expired = [n["_id"] for n in db.nodes.find({**q, "status": "active", "expires_at": {"$ne": None, "$lte": t}})]
    _set_status(db, pack_id, scope_id, expired, "expired", "expired")
    for d in db.directives.find({**q, "status": "active", "expires_at": {"$ne": None, "$lte": t}}):
        db.directives.update_one({"_id": d["_id"]}, {"$set": {"status": "expired"}})
        ledger(db, pack_id, scope_id, "directive_expired", d["_id"])

    g = scope_graph(db, pack_id, scope_id)
    nodes, incoming, _ = planner.index(g)
    status = {i: n.get("status", "active") for i, n in nodes.items()}
    on = planner.derive(nodes, incoming, status)
    rederived, down = [], set(expired)
    for i, sup in on.items():
        if sup and status[i] in ("quarantined", "invalidated"):
            rederived.append(i)
        elif not sup and status[i] == "active":
            down.add(i)
    _set_status(db, pack_id, scope_id, rederived, "active", "rederived", "supporter_active")
    _set_status(db, pack_id, scope_id, sorted(down - set(expired)), "quarantined", "quarantine", "no_active_support")
    new = dict(status, **{i: "active" for i in rederived}, **{i: "quarantined" for i in down - set(expired)},
               **{i: "expired" for i in expired})
    acts = planner.repair_decisions(g["decisions"], down, new)
    replayed = apply_decision_actions(db, pack_id, scope_id, acts, g, new, down)
    return {"expired": expired, "rederived": rederived, "down": sorted(down), "replayed": replayed}


# ---------------------------------------------------------------- decisions and replay

def create_decision(db, body, actor="api"):
    _req(body, "pack_id", "scope_id")
    pack_id, scope_id, inputs = body["pack_id"], body["scope_id"], body.get("inputs") or []
    pack = get_pack(db, pack_id)
    found = {n["_id"]: n for n in db.nodes.find({"_id": {"$in": inputs}}, {"scope_id": 1, "pack_id": 1, "status": 1})}
    for i in inputs:
        n = found.get(i)
        if not n:
            raise CoreError("not_found", f"node {i}", 404)
        if n["scope_id"] != scope_id or n["pack_id"] != pack_id:
            raise CoreError("scope_violation", f"node {i} is outside scope {scope_id}", 403)
        if n["status"] != "active":
            raise CoreError("bad_request", f"node {i} is {n['status']}")
    did = body.get("decision_id") or f"dec_{slug(scope_id)}_{uuid.uuid4().hex[:10]}"
    db.decisions.insert_one({"_id": did, "pack_id": pack_id, "scope_id": scope_id, "inputs": inputs,
                             "output": body.get("output"), "status": "active", "replay_of": body.get("replay_of"),
                             "ts": now()})
    rel = _decision_rel(pack)
    if inputs:
        db.edges.insert_many([{"pack_id": pack_id, "scope_id": scope_id, "from": i, "to": did, "rel": rel}
                              for i in inputs])
    ledger(db, pack_id, scope_id, "decision_created", did, None, {"inputs": inputs, "replay_of": body.get("replay_of")},
           actor)
    return {"decision_id": did}


def substitute(g, status, exclude, kinds):
    """Replay basis: the active derived node of the same kind(s) with the most active supporters."""
    nodes, incoming, _ = planner.index(g)
    best = sorted(((sum(status.get(p) == "active" for p in incoming[i]), i) for i in nodes
                   if incoming[i] and status.get(i) == "active" and i not in exclude
                   and (not kinds or nodes[i].get("kind") in kinds)), key=lambda x: (-x[0], x[1]))
    return nodes[best[0][1]] if best else None


def apply_decision_actions(db, pack_id, scope_id, actions, g, status, down, dry_run=False):
    """invalidate + replay -> old decision `replayed`, new decision with replay_of. Returns {old: new}."""
    decs = {d["_id"]: d for d in g["decisions"]}
    kinds_of = {n["_id"]: n.get("kind") for n in g["nodes"]}
    out = {}
    for a in actions:
        d = decs.get(a["id"])
        if not d:
            continue
        if a["action"] == "preserve" and not dry_run:
            ledger(db, pack_id, scope_id, "preserve", d["_id"], None, {"reason": a["reason"]})
        if a["action"] != "replay":
            continue
        sub = substitute(g, status, set(down) | set(d["inputs"]), {kinds_of.get(i) for i in d["inputs"]} - {None})
        output = {"basis": sub["text"] if sub else None, "replaces": d.get("output")}
        if dry_run:
            out[d["_id"]] = {"decision_id": None, "output": output, "inputs": [sub["_id"]] if sub else []}
            continue
        db.decisions.update_one({"_id": d["_id"]}, {"$set": {"status": "replayed"}})
        ledger(db, pack_id, scope_id, "invalidate", d["_id"], {"status": d.get("status")},
               {"status": "replayed", "reason": a.get("reason") or "lost_all_support"})
        new = create_decision(db, {"pack_id": pack_id, "scope_id": scope_id, "inputs": [sub["_id"]] if sub else [],
                                   "output": output, "replay_of": d["_id"]}, actor="core")
        out[d["_id"]] = new["decision_id"]
    return out


# ---------------------------------------------------------------- retraction

def retract(db, body, pol=None, actor="api"):
    _req(body, "pack_id", "scope_id", "target_id")
    pack_id, scope_id, target = body["pack_id"], body["scope_id"], body["target_id"]
    get_pack(db, pack_id)
    n = db.nodes.find_one({"_id": target}, {"pack_id": 1, "scope_id": 1, "status": 1})
    if not n:
        raise CoreError("not_found", f"node {target}", 404)
    if n["scope_id"] != scope_id or n["pack_id"] != pack_id:
        raise CoreError("scope_violation", f"node {target} is outside scope {scope_id}", 403)
    pol = pol or policy()
    g = scope_graph(db, pack_id, scope_id)
    plan, new, trace = planner.plan(g, target, pol)
    old = {x["_id"]: x.get("status", "active") for x in g["nodes"]}
    verb = {"invalidated": "delete", "retracted": "retract", "quarantined": "quarantine"}
    for i, s in new.items():
        if s != old[i]:
            _set_status(db, pack_id, scope_id, [i], s, verb.get(s, s), body.get("reason"), actor)
    replay_map = apply_decision_actions(db, pack_id, scope_id, plan["actions"], g, new, set(trace["down"]))
    ledger(db, pack_id, scope_id, "retract", target, None,
           {"policy": pol, "reason": body.get("reason"), "plan": plan, "replay_map": replay_map, "trace": trace}, actor)
    return {"plan": plan, "replayed": sorted(replay_map), "policy": pol, "trace": trace, "replay_map": replay_map}


# ---------------------------------------------------------------- why, diff, ledger, search

def why(db, decision_id, pack_id=None, scope_id=None):
    d = db.decisions.find_one({"_id": decision_id})
    if not d:
        raise CoreError("not_found", f"decision {decision_id}", 404)
    if (pack_id and d["pack_id"] != pack_id) or (scope_id and d["scope_id"] != scope_id):
        raise CoreError("scope_violation", f"decision {decision_id} is outside scope {scope_id}", 403)
    q = {"pack_id": d["pack_id"], "scope_id": d["scope_id"]}
    agg = list(db.decisions.aggregate([
        {"$match": {"_id": decision_id}},
        {"$graphLookup": {"from": "edges", "startWith": "$_id", "connectFromField": "from", "connectToField": "to",
                          "as": "up", "depthField": "depth", "restrictSearchWithMatch": q}}]))
    up = agg[0]["up"] if agg else []
    status = {n["_id"]: n for n in db.nodes.find({"_id": {"$in": list({e["from"] for e in up})}},
                                                 {"status": 1, "kind": 1, "text": 1})}
    prov = sorted(({"node_id": e["from"], "rel": e["rel"], "to": e["to"], "depth": e["depth"],
                    "kind": status.get(e["from"], {}).get("kind", "event"),
                    "status": status.get(e["from"], {}).get("status"),
                    "text": status.get(e["from"], {}).get("text")} for e in up), key=lambda x: (x["depth"], x["node_id"]))
    led = list(db.history.find({**q, "target": {"$in": [decision_id, *(d.get("inputs") or [])]}}, {"_id": 0})
               .sort("ts", 1))
    dec = {"decision_id": d["_id"], **{k: d.get(k) for k in ("inputs", "output", "status", "replay_of", "ts")}}
    return {"decision": dec, "provenance": prov, "ledger": led}


def _dview(d):
    return {"decision_id": d["_id"], "output": d.get("output"), "inputs": d.get("inputs")}


def diff(db, pack_id, scope_id, target):
    """Before/after of the decisions a retraction touches. Dry run if the target has not been retracted yet."""
    _req({"pack_id": pack_id, "scope_id": scope_id, "retract": target}, "pack_id", "scope_id", "retract")
    rec = db.history.find_one({"pack_id": pack_id, "scope_id": scope_id, "action": "retract", "target": target},
                             sort=[("ts", -1)])
    if rec:
        plan, rmap, dry = rec["after"]["plan"], rec["after"]["replay_map"], False
    else:
        n = db.nodes.find_one({"_id": target}, {"pack_id": 1, "scope_id": 1})
        if not n:
            raise CoreError("not_found", f"node {target}", 404)
        if n["scope_id"] != scope_id or n["pack_id"] != pack_id:
            raise CoreError("scope_violation", f"node {target} is outside scope {scope_id}", 403)
        g = scope_graph(db, pack_id, scope_id)
        plan, new, trace = planner.plan(g, target, policy())
        rmap = apply_decision_actions(db, pack_id, scope_id, plan["actions"], g, new, set(trace["down"]), dry_run=True)
        dry = True
    changed = sorted({a["id"] for a in plan["actions"] if a["action"] == "invalidate"})
    preserved = sorted({a["id"] for a in plan["actions"] if a["action"] == "preserve" and a["id"] in
                        {x["_id"] for x in db.decisions.find({"_id": {"$in": [a["id"]]}}, {"_id": 1})}})
    olds = {d["_id"]: d for d in db.decisions.find({"_id": {"$in": changed + preserved}})}
    before = [_dview(olds[i]) for i in changed + preserved if i in olds]
    after = []
    for i in changed:
        r = rmap.get(i)
        if isinstance(r, dict):
            after.append({**r, "replay_of": i})
        elif r:
            nd = db.decisions.find_one({"_id": r})
            after.append({**_dview(nd), "replay_of": i})
    after += [_dview(olds[i]) for i in preserved if i in olds]
    return {"before": before, "after": after, "changed": changed, "preserved": preserved, "dry_run": dry}


def get_ledger(db, pack_id=None, scope_id=None, limit=50):
    q = {k: v for k, v in (("pack_id", pack_id), ("scope_id", scope_id)) if v}
    return {"entries": list(db.history.find(q, {"_id": 0}).sort("ts", -1).limit(int(limit)))}


_VOYAGE_OK = None
_CACHE = None
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "embeddings.json")


def _cache():
    global _CACHE
    if _CACHE is None:
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                _CACHE = json.load(f)
        except (OSError, ValueError):
            _CACHE = {}
    return _CACHE


def _save_cache():
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(_CACHE, f)


def _ckey(model, input_type, text):
    return hashlib.sha256(f"{model}|{input_type}|{text}".encode()).hexdigest()


def embed_many(texts, input_type="document"):
    """Voyage embeddings (cached on disk by model, input_type and text). None when no key or Voyage fails, and
    search then falls back to lexical."""
    global _VOYAGE_OK
    key = os.getenv("VOYAGE_API_KEY")
    if not key or _VOYAGE_OK is False:
        return None
    model = os.getenv("VOYAGE_MODEL", "voyage-4-lite")
    cache = _cache()
    keys = [_ckey(model, input_type, t) for t in texts]
    todo = sorted({(k, t) for k, t in zip(keys, texts) if k not in cache})
    base = (os.getenv("VOYAGE_API_BASE") or os.getenv("VOYAGE_BASE_URL") or "https://ai.mongodb.com/v1").rstrip("/")
    url = base if base.endswith("/embeddings") else base + "/embeddings"
    try:
        import requests
        for i in range(0, len(todo), 64):
            batch = todo[i:i + 64]
            r = requests.post(url, headers={"Authorization": f"Bearer {key}"}, timeout=60,
                              json={"input": [t for _, t in batch], "model": model, "input_type": input_type})
            r.raise_for_status()
            for (k, _), d in zip(batch, sorted(r.json()["data"], key=lambda d: d["index"])):
                cache[k] = d["embedding"]
        if todo:
            _save_cache()
        _VOYAGE_OK = True
        return [cache[k] for k in keys]
    except Exception as e:
        _VOYAGE_OK = False
        print("embedding unavailable, lexical fallback:", type(e).__name__, getattr(getattr(e, "response", None),
                                                                                    "status_code", ""))
        return None


def embed(texts, input_type="document"):
    v = embed_many(texts[:1], input_type)
    return v[0] if v else None


def backfill_embeddings(db, pack_id, scope_id=None):
    """Embed every node of a pack (optionally one scope) that has no embedding. Returns the count written."""
    q = {"pack_id": pack_id, "$or": [{"embedding": None}, {"embedding": {"$exists": False}}]}
    if scope_id:
        q["scope_id"] = scope_id
    docs = list(db.nodes.find(q, {"text": 1}))
    vecs = embed_many([d["text"] for d in docs]) if docs else []
    if not vecs:
        return 0
    for d, v in zip(docs, vecs):
        db.nodes.update_one({"_id": d["_id"]}, {"$set": {"embedding": v}})
    return len(docs)


def _tokens(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def search(db, body):
    _req(body, "pack_id", "scope_id", "query")
    pack_id, scope_id, k = body["pack_id"], body["scope_id"], int(body.get("k") or 5)
    refresh(db, pack_id, scope_id)
    q = {"pack_id": pack_id, "scope_id": scope_id, "status": "active"}
    vec = embed([body["query"]], "query")
    if vec is not None:
        try:
            res = list(db.nodes.aggregate([
                {"$vectorSearch": {"index": "nodes_embedding", "path": "embedding", "queryVector": vec,
                                   "numCandidates": max(50, k * 10), "limit": k, "filter": q}},
                {"$project": {"text": 1, "kind": 1, "score": {"$meta": "vectorSearchScore"}}}]))
            if res:
                return {"results": [{"node_id": r["_id"], "text": r["text"], "score": round(r["score"], 4),
                                     "kind": r["kind"]} for r in res], "mode": "vector"}
        except Exception:
            pass
    qt = _tokens(body["query"])
    scored = []
    for n in db.nodes.find(q, {"text": 1, "kind": 1}):
        nt = _tokens(n["text"])
        s = len(qt & nt) / max(1, len(qt))
        if s > 0:
            scored.append((s, n))
    scored.sort(key=lambda x: (-x[0], x[1]["_id"]))
    return {"results": [{"node_id": n["_id"], "text": n["text"], "score": round(s, 4), "kind": n["kind"]}
                        for s, n in scored[:k]], "mode": "lexical"}


# ---------------------------------------------------------------- directives

DIRECTIVE_FIELDS = {"type", "target", "expires_at", "cap", "confirmed_by", "source_text"}


def add_directive(db, body, key_header=None, actor="compiler"):
    secret = os.getenv("COMPILER_SHARED_SECRET")
    if secret and key_header != secret:
        raise CoreError("forbidden", "compiler key required", 403)
    _req(body, "pack_id", "scope_id", "directive")
    pack_id, scope_id, d = body["pack_id"], body["scope_id"], body["directive"]
    pack = get_pack(db, pack_id)
    if not isinstance(d, dict) or set(d) - DIRECTIVE_FIELDS or not {"type", "target"} <= set(d):
        raise CoreError("bad_request", f"directive fields must be within {sorted(DIRECTIVE_FIELDS)}")
    if not d.get("confirmed_by"):
        raise CoreError("not_confirmed", "directive needs confirmed_by", 422)
    if d["confirmed_by"] not in ("pin", "builder"):
        raise CoreError("bad_request", "confirmed_by must be pin or builder")
    if d["type"] not in (pack.get("directive_vocab") or []):
        raise CoreError("bad_request", f"directive type {d['type']} not in pack vocabulary")
    t = d.get("target") or {}
    if not isinstance(t, dict) or set(t) != {"kind", "value"}:
        raise CoreError("bad_request", "target must be {kind, value}")
    if t["kind"] in {r["field"] for r in pack.get("gate") or []}:
        raise CoreError("bad_request", "gate fields cannot be targeted by a directive")
    if d["type"] == "suppress" and not d.get("expires_at"):
        raise CoreError("bad_request", "suppress requires expires_at")
    if d["type"] == "prioritize" and not isinstance(d.get("cap"), int):
        raise CoreError("bad_request", "prioritize requires an integer cap")
    did = f"dir_{slug(scope_id)}_{uuid.uuid4().hex[:10]}"
    if d["type"] == "retract":
        if db.directives.find_one({"_id": t["value"], "scope_id": scope_id}):
            db.directives.update_one({"_id": t["value"]}, {"$set": {"status": "retracted"}})
            ledger(db, pack_id, scope_id, "directive_retracted", t["value"], None, {"by": did}, actor)
        else:
            retract(db, {"pack_id": pack_id, "scope_id": scope_id, "target_id": t["value"],
                         "reason": d.get("source_text") or "directive"}, actor=actor)
    doc = {"_id": did, "pack_id": pack_id, "scope_id": scope_id, "type": d["type"], "target": t,
           "expires_at": d.get("expires_at"), "cap": d.get("cap"), "confirmed_by": d["confirmed_by"],
           "source_text": d.get("source_text"), "status": "active", "ts": now()}
    db.directives.insert_one(doc)
    ledger(db, pack_id, scope_id, "directive_created", did, None, {"type": d["type"], "target": t}, actor)
    return {"directive_id": did, "status": "active"}


def list_directives(db, pack_id, scope_id, active_only=True):
    if pack_id and scope_id:
        refresh(db, pack_id, scope_id)
    q = {k: v for k, v in (("pack_id", pack_id), ("scope_id", scope_id)) if v}
    if active_only:
        q["status"] = "active"
    out = []
    for d in db.directives.find(q).sort("ts", 1):
        out.append({"directive_id": d.pop("_id"), **{k: d.get(k) for k in
                    ("type", "target", "expires_at", "cap", "confirmed_by", "source_text", "status")}})
    return {"directives": out}
