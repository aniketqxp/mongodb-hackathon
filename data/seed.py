"""Load the demo pack + seed graph into MongoDB. Idempotent: replaces only this pack's documents.

  python data/seed.py --dry-run          validate files, print counts (no DB, no keys)
  python data/seed.py                    load into MONGODB_URI / MONGODB_DB (default governed_memory)
  python data/seed.py --embed            also add Voyage embeddings to nodes (needs VOYAGE_API_KEY)

Only documents with pack_id == pack_video_demo are deleted and re-inserted.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
COLLECTIONS = ["events", "nodes", "edges", "decisions"]


def load():
    pack = json.loads((HERE / "pack_video.json").read_text())
    graph = json.loads((HERE / "graph.json").read_text())
    return pack, graph


def embed_nodes(nodes):
    import requests

    url = os.getenv("VOYAGE_BASE_URL", "https://ai.mongodb.com/v1/embeddings")
    key = os.environ["VOYAGE_API_KEY"]
    model = os.getenv("VOYAGE_MODEL", "voyage-4-lite")
    for i in range(0, len(nodes), 64):
        batch = nodes[i : i + 64]
        r = requests.post(url, headers={"Authorization": f"Bearer {key}"},
                          json={"input": [n["text"] for n in batch], "model": model}, timeout=60)
        r.raise_for_status()
        for n, d in zip(batch, r.json()["data"]):
            n["embedding"] = d["embedding"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--embed", action="store_true")
    args = ap.parse_args()
    pack, graph = load()
    counts = {c: len(graph[c]) for c in COLLECTIONS}
    print("pack:", pack["pack_id"], "| docs:", counts)
    if args.embed:
        embed_nodes(graph["nodes"])
        print("embedded", len(graph["nodes"]), "nodes")
    if args.dry_run:
        return 0
    from pymongo import MongoClient

    uri = os.environ.get("MONGODB_URI")
    if not uri:
        sys.exit("MONGODB_URI not set (see .env.example)")
    db = MongoClient(uri)[os.getenv("MONGODB_DB", "governed_memory")]
    pid = pack["pack_id"]
    db.packs.delete_many({"pack_id": pid})
    db.packs.insert_one({"_id": pid, "pack_id": pid, "slots": {k: v for k, v in pack.items() if k != "pack_id"},
                         "status": "draft", "conformance": None})
    for c in COLLECTIONS:
        db[c].delete_many({"pack_id": pid})
        if graph[c]:
            db[c].insert_many(graph[c])
    print("loaded into", db.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
