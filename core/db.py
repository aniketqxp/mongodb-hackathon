"""Atlas connection, validators and indexes (A1). Contract v0.3: expiry is a status change done by the engine's
sweep, so there are no TTL indexes (a TTL delete is silent, unauditable, and cannot trigger replay)."""
import os
from datetime import datetime, timezone
from pathlib import Path

from pymongo import ASCENDING, DESCENDING, MongoClient

ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
COLLECTIONS = ("events", "nodes", "edges", "decisions", "directives", "history", "packs")
VECTOR_INDEX = "nodes_embedding"
_client = None


def _load_env():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env", override=False)
    extra = os.getenv("CORE_ENV_FILE")  # optional extra env file outside the repo
    if extra and Path(extra).exists():
        load_dotenv(extra, override=False)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def get_db():
    global _client
    _load_env()
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI not set (see .env.example)")
    if _client is None:
        _client = MongoClient(uri, appname="governed-memory-core", serverSelectionTimeoutMS=15000)
    return _client[os.getenv("MONGODB_DB", "governed_memory")]


_S, _N, _O, _A = {"bsonType": "string"}, {"bsonType": "null"}, {"bsonType": "object"}, {"bsonType": "array"}
_SN = {"bsonType": ["string", "null"]}
NODE_STATUS = ["active", "quarantined", "invalidated", "expired", "retracted"]  # retracted: v0.3
DECISION_STATUS = ["active", "invalidated", "replayed"]


def _schema(required, props):
    return {"$jsonSchema": {"bsonType": "object", "required": ["pack_id", "scope_id", *required] if required is not None
                            else [], "properties": props}}


SCHEMAS = {  # contract v0.3 section 1; additional fields allowed (seed and replay metadata)
    "events": _schema(["type", "payload", "ts"], {"pack_id": _S, "scope_id": _S, "type": _S, "payload": _O, "ts": _S,
                                                  "source": _SN}),
    "nodes": _schema(["kind", "text", "status"], {"pack_id": _S, "scope_id": _S, "kind": _S, "text": _S,
                                                 "embedding": {"bsonType": ["array", "null"]},
                                                 "status": {"enum": NODE_STATUS}, "expires_at": _SN, "support": _A}),
    "edges": _schema(["from", "to", "rel"], {"pack_id": _S, "scope_id": _S, "from": _S, "to": _S, "rel": _S}),
    "decisions": _schema(["inputs", "status", "ts"], {"pack_id": _S, "scope_id": _S, "inputs": _A,
                                                     "status": {"enum": DECISION_STATUS}, "replay_of": _SN, "ts": _S}),
    "directives": _schema(["type", "target", "confirmed_by", "status"], {
        "pack_id": _S, "scope_id": _S, "type": {"enum": ["suppress", "prioritize", "retract"]},
        "target": {"bsonType": "object", "required": ["kind", "value"]}, "expires_at": _SN,
        "confirmed_by": {"enum": ["pin", "builder"]}, "status": {"enum": ["active", "expired", "retracted"]}}),
    "history": _schema(["actor", "action", "target", "ts"], {"actor": _S, "action": _S, "target": _SN, "ts": _S}),
    "packs": {"$jsonSchema": {"bsonType": "object", "required": ["pack_id", "slots", "status"], "properties": {
        "pack_id": _S, "slots": _O, "status": {"enum": ["draft", "active"]}}}},
}


def ensure(db, vector=True):
    """Create collections with contract validators. Replaces the prototype's validators (same owner, A1).
    moderate: new and valid docs are checked; legacy prototype docs are left as they are (nothing deleted)."""
    existing = set(db.list_collection_names())
    for c in COLLECTIONS:
        if c not in existing:
            db.create_collection(c, validator=SCHEMAS[c], validationLevel="moderate")
        else:
            db.command("collMod", c, validator=SCHEMAS[c], validationLevel="moderate")
    db.events.create_index([("pack_id", ASCENDING), ("scope_id", ASCENDING), ("ts", ASCENDING)])
    db.nodes.create_index([("pack_id", ASCENDING), ("scope_id", ASCENDING), ("status", ASCENDING)])
    db.nodes.create_index([("expires_at", ASCENDING)])
    db.edges.create_index([("from", ASCENDING)])
    db.edges.create_index([("to", ASCENDING)])
    db.decisions.create_index([("scope_id", ASCENDING), ("ts", ASCENDING)])
    db.directives.create_index([("scope_id", ASCENDING), ("type", ASCENDING)])
    db.directives.create_index([("expires_at", ASCENDING)])
    db.history.create_index([("scope_id", ASCENDING), ("ts", DESCENDING)])
    db.packs.create_index([("pack_id", ASCENDING)], unique=True)
    if vector:
        try:
            names = {i["name"] for i in db.nodes.list_search_indexes()}
            if VECTOR_INDEX not in names:
                db.nodes.create_search_index({"name": VECTOR_INDEX, "type": "vectorSearch", "definition": {"fields": [
                    {"type": "vector", "path": "embedding", "numDimensions": int(os.getenv("VOYAGE_DIMS", "1024")),
                     "similarity": "cosine"},
                    {"type": "filter", "path": "pack_id"}, {"type": "filter", "path": "scope_id"},
                    {"type": "filter", "path": "status"}, {"type": "filter", "path": "kind"}]}})
        except Exception as e:  # search indexes unavailable: lexical fallback still works
            print("vector index not created:", e)


def ledger(db, pack_id, scope_id, action, target, before=None, after=None, actor="core"):
    db.history.insert_one({"actor": actor, "action": action, "target": target, "before": before, "after": after,
                          "ts": now(), "pack_id": pack_id, "scope_id": scope_id})
