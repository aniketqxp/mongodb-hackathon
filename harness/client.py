"""Minimal client for the core API routes in OPS/CONTRACT.md. Stdlib only."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class ApiError(Exception):
    def __init__(self, code, detail, status=None):
        super().__init__("%s: %s" % (code, detail))
        self.code, self.detail, self.status = code, detail, status


class CoreApi:
    def __init__(self, base=None, timeout=15):
        self.base = (base or os.environ.get("API_BASE", "http://127.0.0.1:8001")).rstrip("/")
        self.timeout = timeout

    def _call(self, method, path, body=None, query=None):
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status, obj = r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                obj = json.loads(e.read() or b"{}")
            except ValueError:
                obj = {}
        except (urllib.error.URLError, OSError) as e:
            raise ApiError("internal", "API unreachable at %s (%s)" % (self.base, e))
        # Contract error envelope; the mock sometimes sends it with HTTP 200.
        if isinstance(obj, dict) and "error" in obj:
            err = obj["error"] or {}
            raise ApiError(err.get("code", "internal"), err.get("detail", ""), status)
        if status >= 400:
            raise ApiError("internal", "HTTP %d" % status, status)
        return obj

    # --- routes (every request carries pack_id + scope_id) ---
    def post_event(self, pack_id, scope_id, type_, payload):
        return self._call("POST", "/events", {"pack_id": pack_id, "scope_id": scope_id, "type": type_, "payload": payload})

    def search_memory(self, pack_id, scope_id, query, k=10):
        return self._call("POST", "/memory/search", {"pack_id": pack_id, "scope_id": scope_id, "query": query, "k": k})["results"]

    def record_decision(self, pack_id, scope_id, inputs, output):
        return self._call("POST", "/decisions", {"pack_id": pack_id, "scope_id": scope_id, "inputs": inputs, "output": output})["decision_id"]

    def retract(self, pack_id, scope_id, target_id, reason):
        return self._call("POST", "/retract", {"pack_id": pack_id, "scope_id": scope_id, "target_id": target_id, "reason": reason})

    def diff(self, pack_id, scope_id, retract):
        return self._call("GET", "/diff", query={"pack_id": pack_id, "scope_id": scope_id, "retract": retract})
