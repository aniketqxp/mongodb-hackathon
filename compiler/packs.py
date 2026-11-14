"""Load a pack plus what the compiler needs to validate against it, from the repo's data/ (G2).

- pack:   data/pack_*.json whose pack_id matches (contract section 2)
- vocab:  {"topic": taxonomy topics, "tag": every catalog tag}. Target kinds match catalog fields
          (item.topic == value, value in item.tags), so the planner can apply them directly.
- scopes: data/scopes.json, plus scope_profile events in data/graph.json
- ids:    retractable node ids per scope, id -> text (derived nodes first). Until the real API
          lands this reads graph.json; later swap in core reads.

Gate fields (e.g. the maturity ceiling in each scope_profile) are never part of the vocab, and
directive validation rejects them even if they were.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from compiler.directive import DirectiveError, gate_fields
from compiler.schemas import Pack

REPO = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    return Path(os.getenv("COMPILER_DATA_DIR", REPO / "data"))


@dataclass(frozen=True)
class PackBundle:
    pack: Pack
    vocab: dict[str, list[str]]
    scopes: frozenset[str]
    _ids: dict[str, dict[str, str]] = field(default_factory=dict)

    def known_ids(self, scope_id: str) -> dict[str, str]:
        if scope_id not in self.scopes:
            raise DirectiveError("not_found", f"unknown scope {scope_id!r} for pack {self.pack.pack_id!r}")
        return dict(self._ids.get(scope_id, {}))


def _read(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


@lru_cache(maxsize=8)
def load_bundle(pack_id: str) -> PackBundle:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pack_id or ""):
        raise DirectiveError("bad_request", "bad pack_id")
    root = data_dir()
    raw = next((d for f in sorted(root.glob("pack_*.json")) if (d := _read(f)) and d.get("pack_id") == pack_id), None)
    if raw is None:
        raise DirectiveError("not_found", f"pack {pack_id!r} not found")
    pack = Pack.model_validate(raw)

    taxonomy = _read(root / "taxonomy.json") or {}
    catalog = _read(root / "catalog.json") or []
    vocab = {
        "topic": sorted(set(taxonomy.get("topics", [])) | {i["topic"] for i in catalog if i.get("topic")}),
        "tag": sorted({t for i in catalog for t in i.get("tags", [])}),
    }
    blocked = gate_fields(pack)
    vocab = {k: v for k, v in vocab.items() if v and k not in blocked}

    graph = _read(root / "graph.json") or {}
    scopes = {s["scope_id"] for s in (_read(root / "scopes.json") or [])}
    scopes |= {e["scope_id"] for e in graph.get("events", []) if e.get("type") == "scope_profile" and e.get("pack_id") == pack_id}

    ids: dict[str, dict[str, str]] = {}
    nodes = [n for n in graph.get("nodes", []) if n.get("pack_id") == pack_id and n.get("status") == "active"]
    nodes.sort(key=lambda n: (not n.get("support"), n["_id"]))  # derived nodes (with support) first
    for n in nodes:
        ids.setdefault(n["scope_id"], {})[n["_id"]] = n.get("text", "")
    return PackBundle(pack=pack, vocab=vocab, scopes=frozenset(scopes), _ids=ids)
