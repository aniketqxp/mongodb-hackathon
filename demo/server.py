"""Split-screen demo server (Aniket). Left: the feed. Right: the core's own responses, step by step.

  CORE_ENV_FILE=../atlas-credentials.env python -m uvicorn demo.server:app --port 8090

Everything shown comes from the real core routes (core/api.py, called in-process) on Atlas. The feed is built by
the J2 harness slate generator (harness/slate.py, used unmodified) from active memory returned by /memory/search.
The prompt box fills a typed retract request: the LLM (shared/llm.py, Groq) picks one value from an enum of the
scope's own memory keys, code checks it again, and a keyword matcher takes over if the LLM is unavailable. The LLM
only fills the slot; the core decides and enforces.
"""
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient

from core.api import app as core_app
from core.db import get_db, now
from core.demo import reseed
from harness import data as hdata
from harness.slate import build_slate

ROOT = Path(__file__).resolve().parent.parent
SC = json.loads((ROOT / "data" / "scenario.json").read_text())
PACK = json.loads((ROOT / "data" / "pack_video.json").read_text())["pack_id"]
SCOPE = SC["scope_id"]
FEED_SIZE = 6

app = FastAPI(title="governed-memory split demo")
core = TestClient(core_app)
state = {"policy": "provenance", "previous": [], "target": None, "t0": None, "session": 0}


def _post(path, body):
    r = core.post(path, json=body)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.json())
    return r.json()


def _get(path, params):
    r = core.get(path, params=params)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.json())
    return r.json()


def memory():
    r = _post("/memory/search", {"pack_id": PACK, "scope_id": SCOPE, "query": "what this viewer likes", "k": 20})
    nodes = [x for x in r["results"] if x["kind"] == "interest"]
    return nodes, r.get("mode")


def feed(fresh=False):
    """fresh=True is a new session: the slate is rebuilt from memory alone, nothing carried over."""
    nodes, mode = memory()
    out = build_slate(SCOPE, nodes, size=FEED_SIZE, previous=[] if fresh else state["previous"])
    by_id = {n["node_id"]: n["text"] for n in nodes}
    slate = [{**it, "because": [by_id.get(s, s) for s in it["supports"]],
              "from_forgotten": bool(state["target"]) and state["target"] in it["supports"]} for it in out["slate"]]
    before = state["previous"]
    state["previous"] = [it["video_id"] for it in slate]
    return {"slate": slate, "memory": [{"node_id": n["node_id"], "text": n["text"]} for n in nodes],
            "search_mode": mode, "removed": [v for v in before if v not in state["previous"]],
            "catalog_titles": {v: hdata.catalog_by_id()[v]["title"] for v in before if v not in state["previous"]}}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.on_event("startup")
def _warm():
    """Import the LLM client once at startup so the first live prompt is not slowed by cold imports."""
    try:
        import langchain_groq  # noqa: F401
        from shared import llm  # noqa: F401
    except Exception:
        pass


THUMBS = Path(__file__).parent / "thumbs"


@app.get("/thumbs/{slug}")
def thumb(slug: str):
    """Optional artwork: demo/thumbs/<subject>.(jpg|png|webp). Missing files 404 and the page keeps its CSS card."""
    if re.fullmatch(r"[a-z0-9-]+", slug):
        for ext in ("jpg", "png", "webp"):
            if (THUMBS / f"{slug}.{ext}").exists():
                return FileResponse(THUMBS / f"{slug}.{ext}")
    raise HTTPException(404, "no thumbnail")


@app.post("/demo/reset")
def reset(body: dict):
    pol = body.get("policy", "provenance")
    if pol not in ("provenance", "label_only"):
        raise HTTPException(400, "policy must be provenance or label_only")
    os.environ["RETRACTION_POLICY"] = pol
    reseed()
    state.update(policy=pol, previous=[], target=None, t0=None, session=0)
    return {"policy": pol, "scope_id": SCOPE, "pack_id": PACK, "feed": feed()}


@app.get("/demo/feed")
def get_feed():
    return {"policy": state["policy"], "feed": feed()}


def _keys():
    """The scope's own interest memories (any status): key -> (node_id, text). The only values a slot may take."""
    return {n["_id"].split("_interest_", 1)[-1]: (n["_id"], n["text"])
            for n in get_db().nodes.find({"pack_id": PACK, "scope_id": SCOPE, "kind": "interest"}, {"text": 1})}


def _keyword(text, keys):
    words = " %s " % re.sub(r"[^a-z0-9]+", " ", text.lower())
    hits = [k for k in keys if " %s " % k.replace("_", " ") in words]
    return max(hits, key=len) if hits else None


def _llm(text, keys):
    """The LLM fills one typed slot, constrained to the scope's keys by the schema enum. It never acts."""
    if not os.getenv("GROQ_API_KEY"):
        return None, "no GROQ_API_KEY"
    from shared.llm import structured
    schema = {"title": "forget_request", "type": "object", "additionalProperties": False, "required": ["value"],
              "properties": {"value": {"type": "string", "enum": sorted(keys) + ["none"],
                                       "description": "the stored interest the user wants forgotten, or none"}}}
    try:
        out = structured(schema).invoke(
            "A user asked a feed to forget something. Stored interests: " + ", ".join(
                f"{k} ({keys[k][1]})" for k in sorted(keys)) + f".\nUser: {text}\nWhich stored interest?")
        return out.get("value"), None
    except Exception as e:  # network, quota, schema: fall back to the keyword matcher
        return None, type(e).__name__


def _match(text):
    """Typed slot fill. The LLM proposes, code validates against the scope's keys; keyword match is the fallback."""
    keys = _keys()
    value, err = _llm(text, keys)
    model = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    if value in keys:
        filled = {"by": "llm", "model": model}
    else:
        value = _keyword(text, keys)
        filled = {"by": "keyword", "llm": "declined" if err is None else err}
    if value not in keys:
        return None
    return keys[value][0], value, keys[value][1], filled


@app.post("/demo/prompt")
def prompt(body: dict):
    text = (body.get("text") or "").strip()
    m = _match(text)
    if not m:
        raise HTTPException(422, "Nothing in this viewer's memory matches that. Name something the feed shows, "
                                 "like the spooky or space videos.")
    nid, key, ntext, filled = m
    request = {"type": "retract", "target": {"kind": "interest", "value": key}, "node_id": nid}
    t0 = now()
    out = _post("/retract", {"pack_id": PACK, "scope_id": SCOPE, "target_id": nid, "reason": text})
    diff = _get("/diff", {"pack_id": PACK, "scope_id": SCOPE, "retract": nid})
    first = next(iter(out["replay_map"].values()), None)
    why = _get(f"/why/{first}", {"pack_id": PACK, "scope_id": SCOPE}) if first else None
    state.update(target=nid, t0=t0, session=0)
    db = get_db()
    evidence = [{"node_id": e, "status": db.nodes.find_one({"_id": e}, {"status": 1})["status"]}
                for e in out["trace"]["evidence"]]
    return {"prompt": text, "request": request, "filled": filled, "target_text": ntext, "policy": out["policy"],
            "trace": out["trace"], "evidence": evidence, "actions": out["plan"]["actions"],
            "replay_map": out["replay_map"], "diff": diff,
            "why_replay": {"decision_id": first, "inputs": (why or {}).get("decision", {}).get("inputs")},
            "target_status": db.nodes.find_one({"_id": nid}, {"status": 1})["status"], "feed": feed()}


@app.post("/demo/session")
def session():
    if not state["target"]:
        raise HTTPException(409, "send a prompt first")
    state["session"] += 1
    f = feed(fresh=True)  # /memory/search runs refresh(): expiry sweep + recompute, the same code under both policies
    db = get_db()
    t = state["target"]
    rederived = db.history.count_documents({"scope_id": SCOPE, "action": "rederived", "target": t,
                                            "ts": {"$gte": state["t0"]}})
    return {"session": state["session"], "target": t, "target_status": db.nodes.find_one({"_id": t})["status"],
            "in_memory": any(n["node_id"] == t for n in f["memory"]), "rederived": rederived,
            "policy": state["policy"], "feed": f}
