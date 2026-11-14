"""Five domain-neutral conformance checks (CONTRACT section 5). A pack activates only at 5/5.

The suite talks to core only through contract routes, so it tests the real system end to end. It builds
its own data from the pack's slots in two fresh scopes (conf_<run>_a / _b), never touching real scopes.

Conventions it relies on (proposed to the contract owner, see OPS/BLOCKERS.md):
  - POST /events with type = a pack node_type and payload {text, <gate fields>, expires_at?} creates a node
    of that kind when the gate admits it.
  - type "scope_profile" with payload {<value_from_scope keys>: value} sets the scope's gate thresholds.
  - POST /expire {pack_id, scope_id} sweeps nodes past expires_at and recalls their dependents. If the
    route is missing, the suite still checks the outcome (core may sweep on read).

Run: python -m compiler.conformance --pack data/pack_video.json --core http://localhost:8001
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from compiler.gate import default_profile, synthesize
from compiler.schemas import Pack

CHECKS = [
    "retraction_recalls_dependents",
    "independent_support_preserved",
    "no_cross_scope_reads",
    "expiry_removes_memory_and_dependents",
    "gated_content_never_enters_memory",
]
RECALLED = {"invalidate", "replay"}


class CheckFailed(Exception):
    pass


class Core:
    """Thin client over the contract routes. Returns (status, body); never raises on HTTP errors."""

    def __init__(self, base_url: str | None = None, client: Any = None):
        import httpx

        self.base = (base_url or os.getenv("CORE_API_URL", "http://localhost:8001")).rstrip("/")
        self.http = client or httpx.Client(timeout=20)

    def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> tuple[int, dict]:
        r = self.http.request(method, self.base + path, json=body, params=params)
        try:
            data = r.json()
        except ValueError:
            data = {}
        status = r.status_code
        if status < 400 and isinstance(data, dict) and "error" in data:  # tolerate errors sent with 200
            status = 400
        return status, data if isinstance(data, dict) else {"_": data}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Suite:
    def __init__(self, pack: Pack, core: Core, *, now_fn: Callable[[], datetime] | None = None,
                 sleep_fn: Callable[[float], None] = time.sleep, expiry_wait_s: float = 2.0):
        self.pack = pack
        self.core = core
        self.now = now_fn or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep_fn
        self.wait = expiry_wait_s
        self.run = uuid.uuid4().hex[:8]
        self.profile = default_profile(pack.gate)
        self.passing, self.failing = synthesize(pack.gate, self.profile)
        self.kind = pack.node_types[0]
        self._profiled: set[str] = set()
        self._n = 0

    # ---- helpers over contract routes
    def scope(self, tag: str) -> str:
        return f"conf_{self.run}_{tag}"

    def base(self, scope: str) -> dict:
        return {"pack_id": self.pack.pack_id, "scope_id": scope}

    def _ensure_profile(self, scope: str) -> None:
        if self.profile and scope not in self._profiled:
            st, body = self.core.call("POST", "/events", {**self.base(scope), "type": "scope_profile", "payload": dict(self.profile)})
            if st >= 400:
                raise CheckFailed(f"scope_profile event rejected: HTTP {st} {body.get('error')}")
            self._profiled.add(scope)

    def text(self, label: str) -> str:
        self._n += 1
        return f"conformance {self.run} {label} {self._n}"

    def event(self, scope: str, payload: dict) -> tuple[int, dict]:
        self._ensure_profile(scope)
        return self.core.call("POST", "/events", {**self.base(scope), "type": self.kind, "payload": payload})

    def node(self, scope: str, label: str, **extra) -> str:
        st, body = self.event(scope, {**(self.passing or {}), "text": self.text(label), **extra})
        if st >= 400 or not body.get("admitted") or not body.get("node_id"):
            raise CheckFailed(f"gate-passing item was not stored: HTTP {st} {body}")
        return body["node_id"]

    def decision(self, scope: str, inputs: list[str]) -> tuple[int, dict]:
        return self.core.call("POST", "/decisions", {**self.base(scope), "inputs": inputs, "output": {"conformance": self.run}})

    def new_decision(self, scope: str, inputs: list[str]) -> str:
        st, body = self.decision(scope, inputs)
        if st >= 400 or not body.get("decision_id"):
            raise CheckFailed(f"decision not created: HTTP {st} {body}")
        return body["decision_id"]

    def status_of(self, scope: str, decision_id: str) -> str | None:
        st, body = self.core.call("GET", f"/why/{decision_id}", params=self.base(scope))
        if st >= 400:
            return None
        return (body.get("decision") or {}).get("status")

    def search_ids(self, scope: str, query: str) -> list[str]:
        st, body = self.core.call("POST", "/memory/search", {**self.base(scope), "query": query, "k": 20})
        if st >= 400:
            raise CheckFailed(f"search failed: HTTP {st}")
        return [r.get("node_id") for r in body.get("results", [])]

    def retract(self, scope: str, target: str) -> dict:
        st, body = self.core.call("POST", "/retract", {**self.base(scope), "target_id": target, "reason": "conformance"})
        if st >= 400:
            raise CheckFailed(f"retract failed: HTTP {st} {body.get('error')}")
        return body

    @staticmethod
    def actions_for(plan: dict, ident: str) -> set[str]:
        return {a.get("action") for a in (plan.get("plan") or {}).get("actions", []) if a.get("id") == ident}

    # ---- the five checks
    def _retract_setup(self):
        s = self.scope("r")
        fault, other = self.node(s, "fault"), self.node(s, "other")
        only = self.new_decision(s, [fault])
        both = self.new_decision(s, [fault, other])
        return s, fault, only, both, self.retract(s, fault)

    def check_1(self) -> str:
        s, fault, only, _, plan = self._retract_setup()
        acts = self.actions_for(plan, only)
        if not acts & RECALLED:
            raise CheckFailed(f"decision depending only on the fault was not recalled (plan actions: {sorted(acts) or 'none'})")
        st = self.status_of(s, only)
        if st == "active":
            raise CheckFailed("dependent decision is still active after retraction")
        return f"dependent recalled ({', '.join(sorted(acts & RECALLED))}); status {st}"

    def check_2(self) -> str:
        s, fault, _, both, plan = self._retract_setup()
        acts = self.actions_for(plan, both)
        if "invalidate" in acts:
            raise CheckFailed("decision with independent support was invalidated")
        st = self.status_of(s, both)
        if st != "active":
            raise CheckFailed(f"decision with independent support has status {st!r}, expected active")
        return "independently supported decision preserved" + (" (marked preserve)" if "preserve" in acts else "")

    def check_3(self) -> str:
        a, b = self.scope("a"), self.scope("b")
        shared = f"conformance {self.run} shared secret phrase"
        self.node(a, "mine", text=shared)
        theirs = self.node(b, "theirs", text=shared)
        their_dec = self.new_decision(b, [theirs])
        leaks = []
        if theirs in self.search_ids(a, shared):
            leaks.append("search in scope A returned a scope B node")
        st, _ = self.decision(a, [theirs])
        if st < 400:
            leaks.append("scope A decision accepted a scope B node as input")
        if self.status_of(a, their_dec) is not None:
            leaks.append("why/ in scope A returned a scope B decision")
        st, body = self.core.call("GET", "/ledger", params={**self.base(a), "limit": 200})
        if st < 400 and any(e.get("target") in (theirs, their_dec) for e in body.get("entries", [])):
            leaks.append("scope A ledger shows scope B records")
        if leaks:
            raise CheckFailed("; ".join(leaks))
        return "search, decisions, why and ledger stay inside their scope"

    def check_4(self) -> str:
        s = self.scope("e")
        exp = _iso(self.now() + timedelta(seconds=self.wait))
        text = self.text("expiring")
        n = self.node(s, "expiring", text=text, expires_at=exp)
        d = self.new_decision(s, [n])
        self.sleep(self.wait + 1.0)
        st, _ = self.core.call("POST", "/expire", self.base(s))
        swept = "sweep route" if st < 400 else "no /expire route, relied on read-time expiry"
        if n in self.search_ids(s, text):
            raise CheckFailed(f"expired node still returned by search ({swept})")
        ds = self.status_of(s, d)
        if ds == "active":
            raise CheckFailed(f"decision depending on an expired node is still active ({swept})")
        return f"expired node gone, dependent decision {ds} ({swept})"

    def check_5(self) -> str:
        if self.passing is None or not self.failing:
            raise CheckFailed("pack gate cannot be exercised (no passing or failing item)")
        s = self.scope("g")
        for i, payload in self.failing:
            text = self.text(f"gated_{i}")
            st, body = self.event(s, {**payload, "text": text})
            if st < 400 and (body.get("admitted") or body.get("node_id")):
                raise CheckFailed(f"item failing gate rule {i} ({self.pack.gate[i].field} {self.pack.gate[i].op}) was admitted")
            hits = self.search_ids(s, text)
            if hits:
                raise CheckFailed(f"gated item text is searchable in memory: {hits[:3]}")
        return f"{len(self.failing)} gate-failing item(s) rejected, nothing stored"

    def run_all(self) -> dict:
        checks = []
        for i, name in enumerate(CHECKS, start=1):
            try:
                detail, ok = getattr(self, f"check_{i}")(), True
            except CheckFailed as e:
                detail, ok = str(e), False
            except Exception as e:  # core down, bad JSON, etc.
                detail, ok = f"error: {type(e).__name__}: {e}", False
            checks.append({"id": i, "name": name, "passed": ok, "detail": detail})
        return {"passed": sum(c["passed"] for c in checks), "total": len(CHECKS), "checks": checks}


def run_conformance(pack: Pack | dict, core: Core | None = None, **kw) -> dict:
    """-> contract shape {passed, total: 5, checks: [{id, name, passed, detail}]}"""
    p = pack if isinstance(pack, Pack) else Pack.model_validate(pack)
    return Suite(p, core or Core(), **kw).run_all()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", required=True, help="path to a pack JSON file")
    ap.add_argument("--core", default=None, help="core base URL (default CORE_API_URL or :8001)")
    args = ap.parse_args()
    with open(args.pack) as f:
        result = run_conformance(json.load(f), Core(args.core))
    print(json.dumps(result, indent=1))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
