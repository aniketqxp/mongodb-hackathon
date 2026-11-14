"""Optional LangSmith tracing. Everything works (and writes local evidence) without a key.

Enabled only when LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set. LangChain LLM calls made
through shared/llm.py are traced automatically by the same env vars.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = Path(__file__).parent / "evidence"
PROJECT = os.getenv("LANGSMITH_PROJECT", "governed-memory-eval")


def enabled() -> bool:
    return os.getenv("LANGSMITH_TRACING", "false").lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY"))


def traceable(name: str):
    """langsmith.traceable when enabled, else a no-op decorator."""
    if enabled():
        try:
            from langsmith import traceable as _t

            return _t(name=name, project_name=PROJECT)
        except ImportError:
            pass
    return lambda fn: fn


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
