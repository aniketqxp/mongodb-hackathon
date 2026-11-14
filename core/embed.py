"""Vector mode setup: embed a pack's nodes, warm the cache for extra JSON item lists, wait for the vector index.

  python -m core.embed --pack-id P [--items file.json --fields a,b] [--wait 600]

Embeddings are Voyage (VOYAGE_MODEL, default voyage-4-lite), cached in core/.cache/embeddings.json.
"""
import argparse
import json
import sys
import time

from core import engine
from core.db import VECTOR_INDEX, ensure, get_db


def wait_queryable(db, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        idx = {i["name"]: i for i in db.nodes.list_search_indexes()}
        i = idx.get(VECTOR_INDEX)
        if i and i.get("queryable"):
            return True, round(time.time() - t0, 1)
        time.sleep(5)
    return False, round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack-id", required=True)
    ap.add_argument("--items", action="append", default=[], help="JSON list of objects to embed into the cache")
    ap.add_argument("--fields", default="title,description")
    ap.add_argument("--wait", type=int, default=600)
    a = ap.parse_args()
    db = get_db()
    ensure(db, vector=True)
    ok, secs = wait_queryable(db, a.wait)
    print(f"index {VECTOR_INDEX} queryable={ok} after {secs}s")
    n = engine.backfill_embeddings(db, a.pack_id)
    print(f"nodes embedded: {n}; nodes without embedding: "
          f"{db.nodes.count_documents({'pack_id': a.pack_id, 'embedding': None})}")
    fields = a.fields.split(",")
    for f in a.items:
        items = json.load(open(f, encoding="utf-8"))
        texts = [". ".join(str(it[k]) for k in fields if it.get(k)) for it in items]
        vecs = engine.embed_many(texts)
        print(f"{f}: {len(vecs) if vecs else 0}/{len(texts)} items embedded (cached)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
