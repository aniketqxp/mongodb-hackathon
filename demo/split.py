"""Split-screen demo (Aniket). Left: Jasmine's feed UI (ui/static, served unmodified). Right: how memory moves the feed.

  demo/run.sh [--reseed]        (or: python -m uvicorn demo.split:app --port 8090, from the repo root)

One process, no other services. The left page talks to /ui/* and /api/* exactly as it does with ui/server.py; here
those routes run the team's own code in-process:
  - feed, watch, retract:  harness.service.Harness (J2), memory and rules read from the core API
  - core API:              core.api (A), called through a TestClient instead of HTTP
  - sentence -> rule:      compiler.directive (D1): the LLM fills typed slots, code validates them
Each call also updates a small "story" (what was said, memory before/after, feed before/after) that the right
panel polls. The story only reads what those routes returned; it never decides anything.

Demo simplification: the parent PIN is dropped. The UI is parent-only, so the "Save rule" click is the
confirmation (confirmed_by "pin", as ui/server.py sets it after its own PIN check).
"""
import os
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from compiler.directive import DirectiveError, compile_directive, describe, validate_directive, submit_directive
from compiler.packs import load_bundle
from core.api import app as core_app
from core.db import get_db
from core.demo import reseed
from harness import data as hdata
from harness.client import ApiError, CoreApi
from harness.service import Harness
from harness.slate import node_topic

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("RETRACTION_POLICY", "provenance")

core = TestClient(core_app)


class InProcessCore(CoreApi):
    """harness.client.CoreApi with the HTTP hop replaced by the in-process core app. Same error envelope."""

    def __init__(self):
        self.base, self.timeout = "in-process core.api", 15

    def _call(self, method, path, body=None, query=None):
        r = core.request(method, path, json=body, params=query)
        try:
            obj = r.json()
        except ValueError:
            obj = {}
        if isinstance(obj, dict) and isinstance(obj.get("error"), dict):
            raise ApiError(obj["error"].get("code", "internal"), obj["error"].get("detail", ""), r.status_code)
        if r.status_code >= 400:
            raise ApiError("internal", str(obj.get("detail") if isinstance(obj, dict) else obj), r.status_code)
        return obj


API = InProcessCore()
HARNESS = Harness(api=API, memory="api", directives="api")
PACK = HARNESS.pack_id
TOPICS = sorted({v["topic"] for v in hdata.catalog()})
LOCK = threading.Lock()

app = FastAPI(title="governed-memory split demo")


def _err(code, detail, status=400):
    return JSONResponse(status_code=status, content={"error": {"code": code, "detail": detail}})


def _run(fn):
    try:
        return fn()
    except ApiError as e:
        return _err(e.code, e.detail, e.status if e.status and e.status >= 400 else 502)
    except DirectiveError as e:
        return _err(e.code, e.detail, 422 if e.code == "not_confirmed" else 400)
    except (ValueError, KeyError) as e:
        return _err("bad_request", str(e))


# ---------------------------------------------------------------- story (read-only view of what the routes did)
def _blank():
    return {"v": 0, "scope": None, "event": "start", "said": None, "focus": None, "pending": None,
            "memory": [], "memory_before": None, "rules": [], "rules_before": None,
            "slate": [], "slate_before": None}


STORY = _blank()


def _bump(**kw):
    with LOCK:
        STORY.update(kw)
        STORY["v"] += 1


def _memory_view(scope_id, nodes):
    """Each active memory with its search score, its topic, and how many watches it was derived from."""
    ids = [n["node_id"] for n in nodes]
    support = {d["_id"]: len(d.get("support") or []) for d in get_db().nodes.find({"_id": {"$in": ids}}, {"support": 1})}
    return [{"node_id": n["node_id"], "text": n["text"], "score": round(float(n.get("score") or 0), 3),
             "topic": node_topic(n, TOPICS), "from_watches": support.get(n["node_id"], 0)} for n in nodes]


def _rule_view(directives):
    return [{"directive_id": d.get("directive_id") or d.get("_id"), "type": d["type"], "target": d["target"],
             "cap": d.get("cap"), "expires_at": d.get("expires_at"), "source_text": d.get("source_text")}
            for d in directives]


def _slate_view(slate):
    return [{"video_id": e["video_id"], "title": e["title"], "topic": e["topic"], "status": e["status"],
             "supports": e["supports"], "boosted_by": e.get("boosted_by"), "decision_id": e.get("decision_id")}
            for e in slate]


def _on_feed(scope_id, out, reset=False):
    mem, rules, slate = _memory_view(scope_id, out["memories"]), _rule_view(out["directives"]), _slate_view(out["slate"])
    with LOCK:
        pending = STORY["pending"] if STORY["scope"] == scope_id and not reset else None
        if pending:
            STORY.update(event=pending["event"], memory_before=pending["memory"], rules_before=pending["rules"],
                         slate_before=pending["slate"], pending=None)
        else:
            STORY.update(event="start", said=None, memory_before=None, rules_before=None, slate_before=None, pending=None)
        STORY.update(scope=scope_id, memory=mem, rules=rules, slate=slate, focus=None,
                     suppressed=out["receipt"].get("suppressed", []))
        STORY["v"] += 1


def _expect_change(event):
    """Snapshot 'before'. The next /ui/feed (the left page always reloads after a change) becomes 'after'."""
    with LOCK:
        STORY["pending"] = {"event": event, "memory": STORY["memory"], "rules": STORY["rules"], "slate": STORY["slate"]}


@app.get("/demo/story")
def story():
    with LOCK:
        return {k: v for k, v in STORY.items() if k != "pending"}


@app.post("/demo/reset")
def demo_reset():
    """Fresh demo: reload the seed for this pack and drop this pack's parent rules. Other packs are untouched."""
    reseed()
    get_db().directives.delete_many({"pack_id": PACK})
    for s in hdata.scopes():
        HARNESS.reset(s)
    with LOCK:
        v = STORY["v"]
        STORY.clear()
        STORY.update(_blank(), v=v + 1)
    return {"ok": True}


# ---------------------------------------------------------------- the left page's routes (same shapes as ui/server.py)
@app.get("/ui/config")
def ui_config():
    cat = hdata.catalog()
    vocab = {"topic": sorted({v["topic"] for v in cat}), "tag": sorted({t for v in cat for t in v["tags"]})}
    return {"pack_id": PACK, "scopes": HARNESS.scopes(), "labels": hdata.pack().get("labels", {}),
            "api_base": API.base, "compiler_url": "in-process compiler.directive",
            "memory_source": HARNESS.memory.name, "directive_source": HARNESS.directive_source, "vocab": vocab}


@app.get("/ui/feed")
def ui_feed(scope_id: str, reset: str = ""):
    def go():
        if reset:
            demo_reset()
        out = HARNESS.feed(scope_id)
        _on_feed(scope_id, out, reset=bool(reset))
        return out
    return _run(go)


@app.post("/ui/watch")
async def ui_watch(req: Request):
    b = await req.json()
    return _run(lambda: HARNESS.watch(b["scope_id"], b["video_id"], b.get("completion", 1.0)))


@app.post("/ui/retract")
async def ui_retract(req: Request):
    b = await req.json()

    def go():
        text = _mem_text(b["target_id"])
        _bump(event="said", said={"text": "Don't recommend", "status": "saved", "by": "menu",
                                  "directive": {"type": "retract", "target": {"kind": "node", "value": b["target_id"]}},
                                  "summary": f"Forget the memory '{text}' and recompute what depended on it."})
        _expect_change("retract")
        return HARNESS.retract(b["scope_id"], b["target_id"], b.get("reason", "parent_retract"))
    return _run(go)


def _mem_text(node_id):
    with LOCK:
        for m in STORY["memory"]:
            if m["node_id"] == node_id:
                return m["text"]
    return node_id


@app.post("/ui/compile")
async def ui_compile(req: Request):
    b = await req.json()

    def go():
        bundle = load_bundle(PACK)
        ids = bundle.known_ids(b["scope_id"])
        try:
            d = compile_directive(b["text"], bundle.pack, bundle.vocab, known_ids=ids)
        except DirectiveError as e:
            _bump(event="said", said={"text": b["text"], "status": "rejected", "by": "llm",
                                      "model": os.getenv("LLM_MODEL", "openai/gpt-oss-120b"), "reason": e.detail})
            raise
        out = {"directive": d.model_dump(), "summary": describe(d, bundle.pack, ids)}
        _bump(event="said", said={"text": b["text"], "status": "draft", "by": "llm",
                                  "model": os.getenv("LLM_MODEL", "openai/gpt-oss-120b"), **out})
        return out
    return _run(go)


@app.post("/ui/confirm-directive")
async def ui_confirm(req: Request):
    b = await req.json()

    def go():
        scope_id = b["scope_id"]
        bundle = load_bundle(PACK)
        ids = bundle.known_ids(scope_id)
        # Whatever the browser sent, code re-validates it; confirmation is set here, never by the client.
        d = validate_directive({**(b.get("directive") or {}), "confirmed_by": None}, bundle.pack, bundle.vocab, known_ids=ids)
        with LOCK:
            said = dict(STORY["said"] or {}, text=d.source_text or (STORY["said"] or {}).get("text"))
        said.update(status="saved", directive=d.model_dump(), summary=describe(d, bundle.pack, ids))
        _bump(event="said", said=said)
        _expect_change(d.type)
        if d.type == "retract":
            # The core's retraction route does the recall (same path as "Don't recommend").
            return {"retract": HARNESS.retract(scope_id, d.target.value, "directive:" + (d.source_text or ""))}
        d = d.model_copy(update={"confirmed_by": "pin"})  # demo: PIN dropped, the parent's Save click confirms
        res = submit_directive(d, bundle.pack, scope_id, bundle.vocab, known_ids=ids,
                               base_url="http://testserver", client=core)
        return res
    return _run(go)


@app.get("/api/why/{decision_id}")
def api_why(decision_id: str, pack_id: str, scope_id: str):
    def go():
        r = API._call("GET", f"/why/{decision_id}", query={"pack_id": pack_id, "scope_id": scope_id})
        vid = next((v for v, did in HARNESS.last.get(scope_id, {}).items() if did == decision_id), None)
        _bump(focus=vid)
        return r
    return _run(go)


@app.get("/api/ledger")
def api_ledger(pack_id: str, scope_id: str, limit: int = 50):
    return _run(lambda: API._call("GET", "/ledger", query={"pack_id": pack_id, "scope_id": scope_id, "limit": limit}))


# ---------------------------------------------------------------- pages
@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "split.html")


@app.get("/film")
def film():
    """The animated explainer. Its numbers come from /film_data.js (real slate generator + planner on the seed data)."""
    return FileResponse(Path(__file__).parent / "film.html")


@app.get("/film_data.js")
def film_data():
    """Fresh film data on every load (demo/film_data.py), so the film always matches data/ and the planner."""
    from fastapi.responses import Response
    from demo import film_data as fd
    return Response(fd.js(), media_type="application/javascript", headers={"Cache-Control": "no-store"})


app.mount("/left", StaticFiles(directory=ROOT / "ui" / "static", html=True), name="left")


@app.on_event("startup")
def _warm():
    try:
        import langchain_groq  # noqa: F401
        from shared import llm  # noqa: F401
    except Exception:
        pass
