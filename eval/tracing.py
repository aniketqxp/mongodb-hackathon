"""Optional LangSmith tracing. Everything works (and writes local evidence) without a key.

Keep LANGSMITH_TRACING=false in .env (free-tier quota). D3 commands take --trace, which turns tracing
on for that process only, and only when LANGSMITH_API_KEY is set. LangChain LLM calls made through
shared/llm.py are then traced automatically too.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = Path(__file__).parent / "evidence"
PROJECT = os.getenv("LANGSMITH_PROJECT", "memory-governance-eval")


def enable_for_run(on: bool) -> bool:
    """Called by --trace before any LLM call. Returns whether tracing is actually on."""
    if on:
        if not os.getenv("LANGSMITH_API_KEY"):
            print("--trace ignored: LANGSMITH_API_KEY is not set")
            return False
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ.setdefault("LANGSMITH_PROJECT", PROJECT)
    return enabled()


def enabled() -> bool:
    return os.getenv("LANGSMITH_TRACING", "false").lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY"))


def traceable(name: str):
    """langsmith.traceable when tracing is on at call time, else a plain call."""
    import functools

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if enabled():
                try:
                    from langsmith import traceable as _t

                    return _t(name=name, project_name=os.getenv("LANGSMITH_PROJECT", PROJECT))(fn)(*a, **kw)
                except ImportError:
                    pass
            return fn(*a, **kw)

        return wrapper

    return deco


def write_evidence(name: str, payload: dict) -> Path:
    """Local copy of every run, so the proof does not depend on LangSmith retention (14 days)."""
    EVIDENCE.mkdir(exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "langsmith": enabled(), **payload}
    path = EVIDENCE / f"{name}.json"
    path.write_text(json.dumps(payload, indent=1) + "\n")
    return path


def upload_dataset(name: str, rows: list[dict]) -> str | None:
    """Create or reuse a LangSmith dataset of {inputs, outputs} rows. Returns its id, or None if disabled."""
    if not enabled():
        return None
    from langsmith import Client

    c = Client()
    ds = next(iter(c.list_datasets(dataset_name=name)), None) or c.create_dataset(name, description="governed-memory eval")
    if not any(True for _ in c.list_examples(dataset_id=ds.id, limit=1)):
        c.create_examples(inputs=[r["inputs"] for r in rows], outputs=[r["outputs"] for r in rows], dataset_id=ds.id)
    return str(ds.id)
