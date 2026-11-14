"""J1 UI server: serves ui/static, runs the J2 harness, and proxies /api/* to the core API.

Run:  python3 ui/server.py            (UI on :8080, core API at http://127.0.0.1:8001)
Env:  API_BASE, UI_PORT, DEMO_PIN, HARNESS_MEMORY (seed|api)

Stdlib only. The browser talks only to this server, which avoids CORS and lets us swap
mock -> real API with one env var.
"""
import json
import os
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for `import harness`

from harness import data  # noqa: E402
from harness.client import ApiError, CoreApi  # noqa: E402
from harness.service import Harness  # noqa: E402

STATIC = os.path.join(HERE, "static")
UI_PORT = int(os.environ.get("UI_PORT", "8080"))
# Demo gate only, not real authentication (see docs/TECHNICAL_DOCUMENTATION.md, section 8).
DEMO_PIN = os.environ.get("DEMO_PIN", "1234")

API = CoreApi()
HARNESS = Harness(api=API)


def _error(code, detail):
    return {"error": {"code": code, "detail": detail}}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC, **kwargs)

    def log_message(self, fmt, *args):
        print("[ui] " + fmt % args)

    def _send(self, status, obj):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def _run(self, fn):
        try:
            self._send(200, fn())
        except ApiError as e:
            self._send(e.status if e.status and e.status >= 400 else 502, _error(e.code, e.detail))
        except (ValueError, KeyError) as e:
            self._send(400, _error("bad_request", str(e)))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/ui/config":
            cat = data.catalog()
            vocab = {"topic": sorted({v["topic"] for v in cat}), "tag": sorted({t for v in cat for t in v["tags"]})}
            return self._send(200, {"pack_id": HARNESS.pack_id, "scopes": HARNESS.scopes(), "labels": data.pack().get("labels", {}),
                                    "api_base": API.base, "memory_source": HARNESS.memory.name, "vocab": vocab})
        if url.path == "/ui/feed":
            def feed():
                if q.get("reset"):
                    HARNESS.reset(q["scope_id"])
                return HARNESS.feed(q["scope_id"])
            return self._run(feed)
        if url.path.startswith("/api/"):  # read-only core routes: /why, /ledger
            return self._run(lambda: API._call("GET", url.path[len("/api"):], query=q))
        return super().do_GET()

    def do_POST(self):
        try:
            body = self._body()
        except ValueError:
            return self._send(400, _error("bad_request", "body is not JSON"))

        if self.path == "/ui/watch":
            return self._run(lambda: HARNESS.watch(body["scope_id"], body["video_id"], body.get("completion", 1.0)))

        if self.path == "/ui/retract":
            return self._run(lambda: HARNESS.retract(body["scope_id"], body["target_id"], body.get("reason", "parent_retract")))

        # PIN-gated write: the browser never sets confirmed_by itself.
        if self.path == "/ui/confirm-directive":
            if str(body.get("pin", "")) != DEMO_PIN:
                return self._send(403, _error("not_confirmed", "wrong PIN"))

            def confirm():
                scope_id = body["scope_id"]
                directive = dict(body.get("directive") or {}, confirmed_by="pin")
                if directive.get("type") == "retract":
                    res = HARNESS.retract(scope_id, directive["target"]["value"], "directive:" + directive.get("source_text", ""))
                    return {"directive_id": None, "status": "retracted", "retract": res}
                res = API._call("POST", "/directives", {"pack_id": HARNESS.pack_id, "scope_id": scope_id, "directive": directive})
                HARNESS.remember_directive(scope_id, directive, res["directive_id"])
                return res
            return self._run(confirm)

        return self._send(404, _error("not_found", self.path))


if __name__ == "__main__":
    print("[ui] http://127.0.0.1:%d  ->  API %s  (pack=%s, memory=%s)" % (UI_PORT, API.base, HARNESS.pack_id, HARNESS.memory.name))
    ThreadingHTTPServer(("127.0.0.1", UI_PORT), Handler).serve_forever()
