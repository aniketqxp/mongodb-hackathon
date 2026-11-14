"""Harness service: glues memory, gate, slate generator and the core API for one process.

Used by ui/server.py. Env:
  API_BASE        core API (mock or real)
  HARNESS_MEMORY  "seed" (default until A3: read data/graph.json for the scope) or "api" (POST /memory/search)
"""
import os

from . import data
from .client import CoreApi
from .gate import check_gate
from .memory import ApiMemory, SeedMemory
from .slate import ID_FIELD, build_slate


class Harness:
    def __init__(self, api=None, memory=None, directives=None):
        self.api = api or CoreApi()
        mode = memory or os.environ.get("HARNESS_MEMORY", "seed")
        self.memory = ApiMemory(self.api) if mode == "api" else SeedMemory()
        self.pack_id = data.pack()["pack_id"]
        # Where active directives come from:
        #   "api"   - GET /directives (CONTRACT v0.2), the source of truth once the real core runs.
        #   "local" - the ones the core accepted in this process. Default while on the mock, whose
        #             GET /directives returns a canned rule for every scope.
        self.directive_source = directives or os.environ.get("HARNESS_DIRECTIVES", "local")
        self.directives = {}
        self.last = {}  # scope_id -> {video_id: decision_id} for the slate currently shown

    # ---------- scopes ----------
    def scopes(self):
        return [{"scope_id": s["scope_id"], "label": s.get("label", s["scope_id"])} for s in data.scopes().values()]

    def _check_scope(self, scope_id):
        if scope_id not in data.scopes():
            raise ValueError("unknown scope %s" % scope_id)

    # ---------- feed ----------
    def feed(self, scope_id, size=6):
        self._check_scope(scope_id)
        nodes = self.memory.search(self.pack_id, scope_id, k=20)
        prev = self.last.get(scope_id, {})
        active = self.active_directives(scope_id)
        out = build_slate(scope_id, nodes, active, size=size, previous=list(prev))
        rules, profile = data.pack().get("gate", []), data.scope_profile(scope_id)
        current = {}
        for entry in out["slate"]:
            item = data.catalog_by_id()[entry[ID_FIELD]]
            # Belt and braces: nothing that fails the gate is ever recorded as a decision.
            if not check_gate(item, rules, profile)[0]:
                raise RuntimeError("gated item reached the slate: %s" % entry[ID_FIELD])
            if entry["status"] == "kept" and prev.get(entry[ID_FIELD]):
                entry["decision_id"] = prev[entry[ID_FIELD]]  # unchanged decision, not re-recorded
            else:
                entry["decision_id"] = self.api.record_decision(
                    self.pack_id, scope_id, entry["supports"],
                    {ID_FIELD: entry[ID_FIELD], "title": entry["title"]},
                )
            current[entry[ID_FIELD]] = entry["decision_id"]
        removed = [v for v in prev if v not in current]
        self.last[scope_id] = current
        out.update({
            "had_previous": bool(prev), "removed": removed,
            "pack_id": self.pack_id, "scope_id": scope_id, "memory_source": self.memory.name,
            "memories": nodes, "directives": active, "directive_source": self.directive_source,
        })
        return out

    def active_directives(self, scope_id):
        if self.directive_source == "api":
            return self.api.list_directives(self.pack_id, scope_id, active_only=True)
        return self.directives.get(scope_id, [])

    # ---------- events ----------
    def watch(self, scope_id, video_id, completion=1.0):
        """Gate first, in code. A rejected item is never sent as a memory-forming event."""
        self._check_scope(scope_id)
        item = data.catalog_by_id().get(video_id)
        if item is None:
            raise ValueError("unknown item %s" % video_id)
        ok, reason = check_gate(item, data.pack().get("gate", []), data.scope_profile(scope_id))
        if not ok:
            return {"admitted": False, "reason": reason, "node_id": None, "enforced_by": "harness"}
        # Send the gate fields with the event so the core gate can evaluate it too.
        payload = {ID_FIELD: video_id, "completion": completion, "topic": item["topic"],
                   "maturity": item["maturity"], "tags": item["tags"]}
        res = self.api.post_event(self.pack_id, scope_id, "watch", payload)
        res["enforced_by"] = "core"
        return res

    # ---------- directives ----------
    def remember_directive(self, scope_id, directive, directive_id):
        self._check_scope(scope_id)
        d = dict(directive, directive_id=directive_id, status="active")
        self.directives.setdefault(scope_id, []).append(d)
        return d

    # ---------- retraction ----------
    def retract(self, scope_id, target_id, reason):
        self._check_scope(scope_id)
        if target_id.startswith("dir_"):
            self.directives[scope_id] = [d for d in self.directives.get(scope_id, []) if d.get("directive_id") != target_id]
        res = self.api.retract(self.pack_id, scope_id, target_id, reason)
        self.memory.apply_retraction(scope_id, target_id, res.get("plan"))
        res["diff"] = self.api.diff(self.pack_id, scope_id, target_id)
        return res

    def reset(self, scope_id):
        self._check_scope(scope_id)
        self.memory.reset(scope_id)
        self.directives.pop(scope_id, None)
        self.last.pop(scope_id, None)
