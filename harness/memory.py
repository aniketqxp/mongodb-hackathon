"""Scoped memory sources for the slate generator.

ApiMemory  - POST /memory/search through the core (the real path once A3 lands).
SeedMemory - reads the G2 seed graph for one scope; used while the mock API returns canned
             search results. It never reads another scope's nodes.
Both return the CONTRACT search shape: [{node_id, text, score, kind}].
"""
from . import data


def decision_input_kinds(pack):
    """Node types that may feed a decision, read from the pack's edge types."""
    return {e["from"] for e in pack.get("edge_types", []) if e.get("to") == "decision"}


class SeedMemory:
    name = "seed"

    def __init__(self):
        self.excluded = {}  # scope_id -> set(node_id) retracted this session

    def search(self, pack_id, scope_id, k=10):
        kinds = decision_input_kinds(data.pack())
        gone = self.excluded.get(scope_id, set())
        nodes = [n for n in data.graph()["nodes"]
                 if n["pack_id"] == pack_id and n["scope_id"] == scope_id
                 and n["kind"] in kinds and n["status"] == "active" and n["_id"] not in gone]
        top = max([len(n["support"]) for n in nodes] or [1])
        res = [{"node_id": n["_id"], "text": n["text"], "score": round(len(n["support"]) / top, 3), "kind": n["kind"]}
               for n in nodes]
        return sorted(res, key=lambda r: (-r["score"], r["node_id"]))[:k]

    def apply_retraction(self, scope_id, target_id, plan):
        """Drop the retracted node and anything the core's plan deleted or quarantined."""
        gone = self.excluded.setdefault(scope_id, set())
        gone.add(target_id)
        for a in (plan or {}).get("actions", []):
            if a.get("action") in ("delete", "quarantine"):
                gone.add(a.get("id"))

    def reset(self, scope_id):
        self.excluded.pop(scope_id, None)


class ApiMemory:
    name = "api"

    def __init__(self, api, query="what this scope likes"):
        self.api, self.query = api, query

    def search(self, pack_id, scope_id, k=10):
        kinds = decision_input_kinds(data.pack())
        return [r for r in self.api.search_memory(pack_id, scope_id, self.query, k) if r.get("kind") in kinds]

    def apply_retraction(self, scope_id, target_id, plan):
        pass  # the core removes retracted nodes from search itself

    def reset(self, scope_id):
        pass
