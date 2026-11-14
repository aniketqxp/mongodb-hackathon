"""Mock core API: canned JSON matching OPS/CONTRACT.md. Run: uvicorn mock.app:app --port 8001"""
import os

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

app = FastAPI(title="core-mock", version="0.1")

PLAN = {
    "fault": "node_123",
    "actions": [
        {"id": "node_123", "action": "delete", "reason": None},
        {"id": "node_201", "action": "quarantine", "reason": None},
        {"id": "dec_77", "action": "invalidate", "reason": None},
        {"id": "dec_77", "action": "replay", "reason": None},
        {"id": "dec_80", "action": "preserve", "reason": "independent_support"},
    ],
}
CHECKS = [
    {"id": i + 1, "name": n, "passed": True, "detail": ""}
    for i, n in enumerate(
        [
            "retraction_recalls_dependents",
            "independent_support_preserved",
            "no_cross_scope_reads",
            "expiry_removes_memory_and_dependents",
            "gated_content_never_enters_memory",
        ]
    )
]


@app.post("/packs")
def create_pack(body: dict):
    return {"pack_id": body.get("pack", {}).get("pack_id", "pack_mock"), "status": "draft"}


@app.post("/packs/{pack_id}/conformance")
def conformance(pack_id: str):
    return {"passed": 5, "total": 5, "checks": CHECKS}


@app.post("/packs/{pack_id}/activate")
def activate(pack_id: str):
    return {"pack_id": pack_id, "status": "active"}


@app.post("/events")
def events(body: dict):
    blocked = body.get("payload", {}).get("restricted") is True
    if blocked:
        return {"admitted": False, "reason": "gate:restricted", "node_id": None}
    return {"admitted": True, "reason": None, "node_id": "node_mock_1"}


@app.post("/memory/search")
def search(body: dict):
    return {"results": [{"node_id": "node_201", "text": "mock memory", "score": 0.91, "kind": "preference"}]}


@app.post("/decisions")
def decisions(body: dict):
    return {"decision_id": "dec_mock_1"}


@app.post("/directives")
def directives(body: dict, x_compiler_key: str | None = Header(default=None)):
    secret = os.getenv("COMPILER_SHARED_SECRET")
    if secret and x_compiler_key != secret:
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "detail": "compiler key required"}})
    if not body.get("directive", {}).get("confirmed_by"):
        return JSONResponse(status_code=422, content={"error": {"code": "not_confirmed", "detail": "directive needs confirmed_by"}})
    return {"directive_id": "dir_mock_1", "status": "active"}


@app.get("/directives")
def list_directives(pack_id: str = "", scope_id: str = "", active_only: bool = True):
    return {"directives": [{"directive_id": "dir_mock_1", "type": "suppress", "target": {"kind": "tag", "value": "scary"},
                            "expires_at": "2026-11-21T18:00:00Z", "cap": None, "confirmed_by": "pin", "status": "active"}]}


@app.post("/retract")
def retract(body: dict):
    return {"plan": PLAN, "replayed": ["dec_77"]}


@app.get("/why/{decision_id}")
def why(decision_id: str, pack_id: str = "", scope_id: str = ""):
    return {
        "decision": {"decision_id": decision_id, "status": "active"},
        "provenance": [{"node_id": "node_201", "rel": "supports"}],
        "ledger": [{"action": "decision_created", "ts": "2026-11-14T18:00:00Z"}],
    }


@app.get("/diff")
def diff(pack_id: str = "", scope_id: str = "", retract: str = ""):
    return {
        "before": ["item_a", "item_b", "item_c"],
        "after": ["item_a", "item_d", "item_c"],
        "changed": ["item_b"],
        "preserved": ["item_a", "item_c"],
    }


@app.get("/ledger")
def ledger(pack_id: str = "", scope_id: str = "", limit: int = 50):
    return {"entries": [{"actor": "system", "action": "retract", "target": "node_123", "ts": "2026-11-14T18:05:00Z"}]}
