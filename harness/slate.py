"""Slate generator: memory -> candidates -> gate > block > boost -> ordered slate.

Pure function over (memory results, catalog, pack, scope profile, directives). Recording the
decisions through the API happens in service.py, and only for items that passed the gate.
"""
import re

from . import data
from .gate import check_gate, split_directives, target_matches

ID_FIELD = "video_id"


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def node_topic(node, topics):
    """The catalog topic a memory node is about, found in its text (longest match wins)."""
    text = " %s " % _norm(node["text"])
    hits = [t for t in topics if " %s " % _norm(t) in text]
    return max(hits, key=len) if hits else None


def supports_for(item, nodes, topics, related):
    """Memory node ids that support this item, strongest first."""
    out = []
    for n in nodes:
        t = node_topic(n, topics)
        if t and (item["topic"] == t or t in item["tags"] or related.get(t, set()) & set(item["tags"])):
            out.append(n["node_id"])
    return out


def build_slate(scope_id, nodes, directives=(), size=6, now=None, previous=()):
    """Return {"slate": [...], "receipt": {"gated", "suppressed", "boosted"}}.

    `previous` is the last slate's item ids. Items from it that still pass the gate and
    directives and still have memory support are kept; only the gaps are refilled.
    Each entry gets status "boosted", "kept" or "new".
    """
    pack, profile = data.pack(), data.scope_profile(scope_id)
    rules = pack.get("gate", [])
    topics = sorted({v["topic"] for v in data.catalog()})
    related = data.related_tags()
    suppress, prioritize = split_directives(list(directives), now)
    strength = {n["node_id"]: n.get("score", 0) for n in nodes}

    gated, suppressed, pool = [], [], []
    for item in data.catalog():
        sup = supports_for(item, nodes, topics, related)
        # 1. gate: restricted items never become candidates, decisions or memory.
        ok, reason = check_gate(item, rules, profile)
        if not ok:
            if sup:
                gated.append({"video_id": item[ID_FIELD], "title": item["title"], "reason": reason})
            continue
        # 2. block: an active suppress directive removes the item, even if a boost names it.
        hit = next((d for d in suppress if target_matches(item, d.get("target"), ID_FIELD)), None)
        if hit:
            if sup:
                suppressed.append({"video_id": item[ID_FIELD], "title": item["title"], "directive_id": hit.get("directive_id")})
            continue
        pool.append((item, sup))

    # 3. boost: each prioritize directive adds up to `cap` matching items, memory-backed ones first.
    picked, boosted = [], []
    for d in prioritize:
        cap = int(d.get("cap") or 0)
        matches = [(it, s) for it, s in pool if target_matches(it, d.get("target"), ID_FIELD)]
        matches.sort(key=lambda p: (-len(p[1]), -sum(strength.get(x, 0) for x in p[1])))
        for it, s in matches:
            if cap <= 0 or len(picked) >= size:
                break
            if any(p[0] is it for p in picked):
                continue
            picked.append((it, s, d.get("directive_id")))
            boosted.append({"video_id": it[ID_FIELD], "title": it["title"], "directive_id": d.get("directive_id")})
            cap -= 1

    # 4. keep previous items that still have support (independent support survives a retraction).
    by_id = {it[ID_FIELD]: (it, s) for it, s in pool}
    for vid in previous:
        if vid in by_id and by_id[vid][1] and not any(p[0][ID_FIELD] == vid for p in picked) and len(picked) < size:
            picked.append((by_id[vid][0], by_id[vid][1], None))

    # 5. fill from memory: items backed by several memories first, then one per memory in turn.
    rest = [(it, s) for it, s in pool if s and not any(p[0] is it for p in picked)]
    multi = [p for p in rest if len(p[1]) > 1]
    queues = {n["node_id"]: [p for p in rest if len(p[1]) == 1 and p[1][0] == n["node_id"]] for n in nodes}
    order = multi[: max(0, min(len(multi), size // 3, size - len(picked)))]
    while len(picked) + len(order) < size and any(queues.values()):
        for nid in [n["node_id"] for n in nodes]:
            if queues[nid] and len(picked) + len(order) < size:
                order.append(queues[nid].pop(0))
    picked += [(it, s, None) for it, s in order]

    prev = set(previous)
    slate = [{
        "video_id": it[ID_FIELD], "title": it["title"], "topic": it["topic"], "maturity": it["maturity"],
        "tags": it["tags"], "duration_s": it.get("duration_s"), "supports": s, "boosted_by": b,
        "status": "boosted" if b else "kept" if it[ID_FIELD] in prev else "new",
    } for it, s, b in picked[:size]]
    return {"slate": slate, "receipt": {"gated": gated, "suppressed": suppressed, "boosted": boosted}}
