"""Compiler service for the UI's confirmation card. Run: uvicorn compiler.app:app --port 8002

POST /directives/compile  {pack_id, scope_id, text}             -> {directive, summary}
POST /directives/confirm  {pack_id, scope_id, directive, pin}   -> core POST /directives response

The PIN is checked here, server-side, and the directive is re-validated before it reaches core.
Packs and target vocab load from COMPILER_PACK_DIR (default compiler/fixtures):
  <pack_id>.pack.json and <pack_id>.vocab.json
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from compiler.directive import DirectiveError, PinGate, compile_directive, describe, submit_directive, validate_directive
from compiler.schemas import Pack

app = FastAPI(title="directive-compiler", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])
gate = PinGate()

STATUS = {"bad_request": 400, "not_confirmed": 403, "not_found": 404, "scope_violation": 403, "internal": 502}


@app.exception_handler(DirectiveError)
def _err(_, e: DirectiveError):
    return JSONResponse(status_code=STATUS.get(e.code, 400), content=e.to_json())


@app.exception_handler(RequestValidationError)
def _bad(_, e: RequestValidationError):
    detail = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:5])
    return JSONResponse(status_code=400, content={"error": {"code": "bad_request", "detail": detail}})


@lru_cache(maxsize=32)
def load_pack(pack_id: str) -> tuple[Pack, dict]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pack_id):
        raise DirectiveError("bad_request", "bad pack_id")
    root = Path(os.getenv("COMPILER_PACK_DIR", Path(__file__).parent / "fixtures"))
    p, v = root / f"{pack_id}.pack.json", root / f"{pack_id}.vocab.json"
    if not p.exists() or not v.exists():
        raise DirectiveError("not_found", f"pack {pack_id!r} not found")
    return Pack.model_validate(json.loads(p.read_text())), json.loads(v.read_text())


class CompileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack_id: str
    scope_id: str
    text: str


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack_id: str
    scope_id: str
    directive: dict
    pin: str


@app.post("/directives/compile")
def compile_route(body: CompileIn):
    pack, vocab = load_pack(body.pack_id)
    d = compile_directive(body.text, pack, vocab)
    return {"directive": d.model_dump(), "summary": describe(d, pack)}


@app.post("/directives/confirm")
def confirm_route(body: ConfirmIn):
    pack, vocab = load_pack(body.pack_id)
    # Whatever the client sent, confirmation is ours to set.
    d = validate_directive({**body.directive, "confirmed_by": None}, pack, vocab)
    d = gate.confirm(d, body.pin, scope_id=body.scope_id)
    return submit_directive(d, pack, body.scope_id, vocab)
