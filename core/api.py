"""Core API (A3), contract v0.3 shapes. Run: uvicorn core.api:app --port 8001"""
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from core import engine
from core.db import ensure, get_db, ledger
from core.engine import CoreError

app = FastAPI(title="governed-memory-core", version="0.3")
_db = None

PACK_SLOTS = ("pack_id", "scope_field", "node_types", "edge_types", "gate", "decay", "directive_vocab", "labels")


def db():
    global _db
    if _db is None:
        _db = get_db()
        ensure(_db)
    return _db


@app.exception_handler(CoreError)
def _core_error(_: Request, e: CoreError):
    return JSONResponse(status_code=e.http, content={"error": {"code": e.code, "detail": e.detail}})


@app.exception_handler(Exception)
def _internal(_: Request, e: Exception):
    return JSONResponse(status_code=500, content={"error": {"code": "internal", "detail": type(e).__name__}})


# demo routes
@app.post("/events")
def events(body: dict):
    return engine.add_event(db(), body)


@app.post("/decisions")
def decisions(body: dict):
    return engine.create_decision(db(), body)


@app.post("/retract")
def retract(body: dict):
    return engine.retract(db(), body)


@app.get("/diff")
def diff(pack_id: str = "", scope_id: str = "", retract: str = ""):
    return engine.diff(db(), pack_id, scope_id, retract)


@app.get("/why/{decision_id}")
def why(decision_id: str, pack_id: str = "", scope_id: str = ""):
    return engine.why(db(), decision_id, pack_id or None, scope_id or None)


@app.post("/memory/search")
def search(body: dict):
    return engine.search(db(), body)


@app.get("/ledger")
def get_ledger(pack_id: str = "", scope_id: str = "", limit: int = 50):
    return engine.get_ledger(db(), pack_id, scope_id, limit)


@app.post("/directives")
def directives(body: dict, x_compiler_key: str | None = Header(default=None)):
    return engine.add_directive(db(), body, x_compiler_key)


@app.get("/directives")
def list_directives(pack_id: str = "", scope_id: str = "", active_only: bool = True):
    return engine.list_directives(db(), pack_id, scope_id, active_only)


# packs
@app.post("/packs")
def create_pack(body: dict):
    pack = body.get("pack") or {}
    missing = [s for s in PACK_SLOTS if s not in pack]
    extra = [s for s in pack if s not in PACK_SLOTS]
    if missing or extra:
        raise CoreError("bad_request", f"pack slots: missing {missing}, unknown {extra}")
    pid = pack["pack_id"]
    if db().packs.find_one({"pack_id": pid, "status": "active"}):
        raise CoreError("bad_request", f"pack {pid} is active; packs are immutable once active")
    db().packs.update_one({"pack_id": pid}, {"$set": {"slots": {k: v for k, v in pack.items() if k != "pack_id"},
                                                       "status": "draft", "conformance": None}}, upsert=True)
    ledger(db(), pid, "*", "pack_created", pid)
    return {"pack_id": pid, "status": "draft"}


@app.post("/packs/{pack_id}/conformance")
def conformance(pack_id: str):
    from core import conformance as conf
    return conf.run(db(), pack_id)


@app.post("/packs/{pack_id}/activate")
def activate(pack_id: str):
    doc = db().packs.find_one({"pack_id": pack_id})
    if not doc:
        raise CoreError("not_found", f"pack {pack_id}", 404)
    c = doc.get("conformance") or {}
    if c.get("passed") != c.get("total") or not c.get("total") or c.get("policy") != "provenance":
        raise CoreError("conformance_failed", f"pack {pack_id} needs 5/5 conformance under provenance first", 409)
    db().packs.update_one({"pack_id": pack_id}, {"$set": {"status": "active"}})
    ledger(db(), pack_id, "*", "pack_activated", pack_id)
    return {"pack_id": pack_id, "status": "active"}
