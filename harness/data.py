"""Read-only access to the G2 data in data/ (catalog, pack, scopes, seed graph)."""
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name):
    return json.loads((DATA / name).read_text())


@lru_cache(maxsize=None)
def catalog():
    """List of items, in file order. Each has video_id, title, topic, maturity, tags, ..."""
    return _load("catalog.json")


@lru_cache(maxsize=None)
def catalog_by_id():
    return {v["video_id"]: v for v in catalog()}


@lru_cache(maxsize=None)
def pack():
    return _load("pack_video.json")


@lru_cache(maxsize=None)
def scopes():
    """scope_id -> scope profile (label, max_maturity, ...)."""
    return {s["scope_id"]: s for s in _load("scopes.json")}


@lru_cache(maxsize=None)
def graph():
    return _load("graph.json")


def scope_profile(scope_id):
    """Scope values the gate reads (e.g. max_maturity).

    CONTRACT v0.1 has no field for these yet, so they live in the scope's `scope_profile`
    event in the seed graph (per Greatness). scopes.json is the fallback.
    """
    for e in graph()["events"]:
        if e["scope_id"] == scope_id and e["type"] == "scope_profile":
            return dict(e["payload"])
    return dict(scopes().get(scope_id, {}))


@lru_cache(maxsize=None)
def related_tags():
    """topic -> tags carried by at least 80% of that topic's items (e.g. a topic's typical tags).

    Derived from the catalog, not hard-coded, so an interest in a topic also supports
    items from other topics that share its characteristic tags.
    """
    by_topic = {}
    for v in catalog():
        by_topic.setdefault(v["topic"], []).append(v)
    out = {}
    for topic, items in by_topic.items():
        counts = Counter(t for v in items for t in v["tags"] if t != topic)
        out[topic] = {t for t, n in counts.items() if n >= 0.8 * len(items)}
    return out
