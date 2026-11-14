"""In-memory reference core speaking the contract routes, for testing the conformance suite.

Correct by default. Each `broken` flag disables exactly one guarantee so tests can prove that the
matching check (and only that one) fails:
  lazy_retract | greedy_retract | leaky_search | no_expiry | no_gate
Test double only, not a second core.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from compiler.gate import evaluate
from compiler.schemas import Pack


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class FakeCore:
    def __init__(self, packs: list[Pack], broken: set[str] = frozenset(), expire_route: bool = True):
        self.packs = {p.pack_id: p for p in packs}
        self.broken = set(broken)
        self.expire_route = expire_route
        self.now = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)
        self.profiles: dict[tuple, dict] = {}
        self.nodes: dict[str, dict] = {}
        self.decisions: dict[str, dict] = {}
        self.ledger: list[dict] = []
        self._id = 0

    # ---- plumbing
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle), base_url="http://core")

    def sleep(self, s: float) -> None:
        from datetime import timedelta

        self.now += timedelta(seconds=s)

    def _new(self, prefix: str) -> str:
        self._id += 1
        return f"{prefix}_{self._id}"

    @staticmethod
    def _err(status: int, code: str, detail: str = "") -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": code, "detail": detail}})

    def _log(self, pid, sid, action, target):
        self.ledger.append({"actor": "core", "action": action, "target": target, "pack_id": pid, "scope_id": sid})

    def _handle(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        q = dict(req.url.params)
        path = req.url.path
        if req.method == "POST" and path == "/events":
            return self.events(body)
        if req.method == "POST" and path == "/memory/search":
            return self.search(body)
        if req.method == "POST" and path == "/decisions":
            return self.decide(body)
        if req.method == "POST" and path == "/retract":
            return self.retract(body)
        if req.method == "POST" and path == "/expire" and self.expire_route:
            return self.expire(body)
        if req.method == "GET" and path.startswith("/why/"):
            return self.why(path.split("/", 2)[2], q)
        if req.method == "GET" and path == "/ledger":
            return httpx.Response(200, json={"entries": [e for e in self.ledger if e["scope_id"] == q.get("scope_id")]})
        return self._err(404, "not_found", path)

    # ---- routes
    def events(self, b):
        pack = self.packs.get(b.get("pack_id"))
        if not pack:
            return self._err(404, "not_found", "pack")
        key = (pack.pack_id, b["scope_id"])
        if b["type"] == "scope_profile":
            self.profiles.setdefault(key, {}).update(b["payload"])
            return httpx.Response(200, json={"admitted": True, "reason": None, "node_id": None})
        if b["type"] not in pack.node_types:
            return self._err(400, "bad_request", "unknown node type")
        p = b.get("payload", {})
        if "no_gate" not in self.broken and not evaluate(pack.gate, p, self.profiles.get(key, {})):
            return httpx.Response(200, json={"admitted": False, "reason": "gate", "node_id": None})
        nid = self._new("node")
        self.nodes[nid] = {"pack_id": pack.pack_id, "scope_id": b["scope_id"], "kind": b["type"], "text": p.get("text", ""),
                           "status": "active", "expires_at": p.get("expires_at")}
        self._log(pack.pack_id, b["scope_id"], "node_created", nid)
        return httpx.Response(200, json={"admitted": True, "reason": None, "node_id": nid})

    def _live(self, n) -> bool:
        if n["status"] != "active":
            return False
        if n["expires_at"] and "no_expiry" not in self.broken and _parse(n["expires_at"]) <= self.now:
            return False
        return True

    def search(self, b):
        words = set(b["query"].lower().split())
        hits = []
        for nid, n in self.nodes.items():
            if n["pack_id"] != b["pack_id"] or not self._live(n):
                continue
            if n["scope_id"] != b["scope_id"] and "leaky_search" not in self.broken:
                continue
            score = len(words & set(n["text"].lower().split())) / (len(words) or 1)
            if score > 0.5:
                hits.append({"node_id": nid, "text": n["text"], "score": score, "kind": n["kind"]})
        hits.sort(key=lambda h: -h["score"])
        return httpx.Response(200, json={"results": hits[: b.get("k", 10)]})

    def decide(self, b):
        for i in b["inputs"]:
            n = self.nodes.get(i)
            if not n or n["pack_id"] != b["pack_id"]:
                return self._err(404, "not_found", i)
            if n["scope_id"] != b["scope_id"]:
                return self._err(403, "scope_violation", i)
        did = self._new("dec")
        self.decisions[did] = {"decision_id": did, "pack_id": b["pack_id"], "scope_id": b["scope_id"],
                               "inputs": list(b["inputs"]), "status": "active"}
        self._log(b["pack_id"], b["scope_id"], "decision_created", did)
        return httpx.Response(200, json={"decision_id": did})

    def _recall(self, fault: str, scope: str, via_retract: bool = False) -> list[dict]:
        actions = []
        for did, d in self.decisions.items():
            if d["scope_id"] != scope or d["status"] != "active" or fault not in d["inputs"]:
                continue
            if via_retract and "lazy_retract" in self.broken:
                continue
            others = [i for i in d["inputs"] if i != fault and self._live(self.nodes[i])]
            if others and "greedy_retract" not in self.broken:
                actions.append({"id": did, "action": "preserve", "reason": "independent_support"})
            else:
                d["status"] = "invalidated"
                actions += [{"id": did, "action": "invalidate", "reason": None}, {"id": did, "action": "replay", "reason": None}]
        return actions

    def retract(self, b):
        n = self.nodes.get(b["target_id"])
        if not n or n["scope_id"] != b["scope_id"]:
            return self._err(404, "not_found", b["target_id"])
        n["status"] = "invalidated"
        actions = [{"id": b["target_id"], "action": "delete", "reason": None}] + self._recall(b["target_id"], b["scope_id"], via_retract=True)
        self._log(b["pack_id"], b["scope_id"], "retract", b["target_id"])
        return httpx.Response(200, json={"plan": {"fault": b["target_id"], "actions": actions},
                                         "replayed": [a["id"] for a in actions if a["action"] == "replay"]})

    def expire(self, b):
        if "no_expiry" in self.broken:
            return httpx.Response(200, json={"expired": []})
        gone = []
        for nid, n in self.nodes.items():
            if n["scope_id"] == b["scope_id"] and n["status"] == "active" and n["expires_at"] and _parse(n["expires_at"]) <= self.now:
                n["status"] = "expired"
                self._recall(nid, b["scope_id"])
                gone.append(nid)
        return httpx.Response(200, json={"expired": gone})

    def why(self, did, q):
        d = self.decisions.get(did)
        if not d or d["scope_id"] != q.get("scope_id") or d["pack_id"] != q.get("pack_id"):
            return self._err(404, "not_found", did)
        return httpx.Response(200, json={"decision": d, "provenance": [{"node_id": i} for i in d["inputs"]], "ledger": []})
