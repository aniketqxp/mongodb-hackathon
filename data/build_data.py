"""Deterministic synthetic data for the demo pack. Run: python data/build_data.py
Writes catalog.json, taxonomy.json, scopes.json, pack_video.json, graph.json (events, nodes, edges, decisions).
All data is synthetic. No real people or children's data.
"""
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).parent
PACK_ID = "pack_video_demo"
rng = random.Random(1114)
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

TOPICS = {
    "animals": (["Funny", "Tiny", "Brave", "Sleepy", "Clever"], ["Penguins", "Otters", "Puppies", "Pandas"]),
    "space": (["Amazing", "Giant", "Distant", "Bright", "Secret"], ["Planets", "Rockets", "Comets", "Moons"]),
    "science": (["Easy", "Messy", "Fizzy", "Quick", "Wild"], ["Experiments", "Volcanoes", "Magnets", "Slime"]),
    "music": (["Happy", "Slow", "Loud", "Silly", "Cozy"], ["Drums", "Piano Songs", "Sing-Alongs", "Guitar Tricks"]),
    "art_craft": (["Simple", "Colorful", "Cute", "Recycled", "Big"], ["Paper Crafts", "Drawings", "Clay Models", "Painting"]),
    "cooking": (["Easy", "Sweet", "Cheesy", "Five-Minute", "Rainbow"], ["Pancakes", "Smoothies", "Cookies", "Pizza"]),
    "gaming": (["Epic", "Cozy", "Speedy", "Pixel", "Mystery"], ["Builders", "Puzzles", "Adventures", "Racers"]),
    "nature": (["Quiet", "Hidden", "Misty", "Golden", "Wild"], ["Forests", "Rivers", "Mountains", "Gardens"]),
    "history": (["Strange", "Ancient", "Famous", "Lost", "Little-Known"], ["Pyramids", "Knights", "Inventors", "Maps"]),
    "comedy": (["Goofy", "Awkward", "Silly", "Surprise", "Backwards"], ["Skits", "Pranks", "Bloopers", "Impressions"]),
    "spooky": (["Creepy", "Midnight", "Haunted", "Shadowy", "Whispering"], ["Stories", "Mazes", "Castles", "Woods"]),
    "action": (["Fast", "Explosive", "Final", "Heroic", "Ultimate"], ["Chases", "Battles", "Stunts", "Showdowns"]),
}
# maturity: 0 all ages, 1 ages 7+, 2 ages 10+, 3 ages 13+
MATURITY_WEIGHTS = {
    "animals": [6, 3, 0, 0], "space": [4, 4, 1, 0], "science": [4, 4, 1, 0], "music": [5, 3, 1, 0],
    "art_craft": [6, 3, 0, 0], "cooking": [5, 3, 1, 0], "gaming": [1, 4, 3, 1], "nature": [5, 3, 1, 0],
    "history": [2, 4, 3, 0], "comedy": [3, 3, 2, 1], "spooky": [0, 3, 4, 2], "action": [0, 2, 4, 3],
}
EXTRA_TAGS = {"spooky": ["scary", "dark"], "action": ["violence", "loud"]}
GENERIC_TAGS = ["calm", "funny", "educational", "music", "hands-on"]


def build_catalog():
    vids, i = [], 0
    names = list(TOPICS)
    counters = Counter()
    while len(vids) < 200:
        topic = names[i % len(names)]
        i += 1
        adjs, nouns = TOPICS[topic]
        n = counters[topic]
        counters[topic] += 1
        title = f"{adjs[n % len(adjs)]} {nouns[(n // len(adjs)) % len(nouns)]}"
        if n >= len(adjs) * len(nouns):
            title += f" Part {n // (len(adjs) * len(nouns)) + 1}"
        mat = rng.choices([0, 1, 2, 3], MATURITY_WEIGHTS[topic])[0]
        tags = [topic] + EXTRA_TAGS.get(topic, []) + rng.sample(GENERIC_TAGS, 1)
        vids.append({
            "video_id": f"vid_{len(vids):03d}", "title": title, "topic": topic, "maturity": mat,
            "tags": tags, "duration_s": rng.choice([90, 180, 240, 420, 600]),
            "description": f"Synthetic video about {topic.replace('_', ' ')}: {title.lower()}.",
        })
    # planted video: independently supported by an animals interest while also tagged scary
    vids[-1].update(title="Haunted Zoo Night", topic="animals", maturity=1,
                    tags=["animals", "scary", "funny"], description="Synthetic video: animals at a spooky zoo.")
    return vids


SCOPES = [
    {"scope_id": "child_7", "label": "Child A (7)", "max_maturity": 1},
    {"scope_id": "child_12", "label": "Child B (12)", "max_maturity": 2},
]

PACK = {
    "pack_id": PACK_ID,
    "scope_field": "scope_id",
    "node_types": ["watch_fact", "interest", "decision_input"],
    "edge_types": [
        {"rel": "supports", "from": "watch_fact", "to": "interest"},
        {"rel": "used_in", "from": "interest", "to": "decision"},
    ],
    "gate": [{"field": "maturity", "op": "lte", "value": None, "value_from_scope": "max_maturity"}],
    "decay": {"kind": "ttl", "seconds": 1209600},
    "directive_vocab": ["suppress", "prioritize", "retract"],
    "labels": {"item": "video", "scope": "child", "directive": "parent rule"},
}


def ts(days_ago, hour):
    return (NOW - timedelta(days=days_ago)).replace(hour=hour).isoformat().replace("+00:00", "Z")


def pick(catalog, topic, k, max_mat):
    pool = [v for v in catalog if v["topic"] == topic and v["maturity"] <= max_mat and v["title"] != "Haunted Zoo Night"]
    return rng.sample(pool, min(k, len(pool)))


def build_graph(catalog):
    by_id = {v["video_id"]: v for v in catalog}
    events, nodes, edges, decisions = [], [], [], []
    # scope profiles
    for s in SCOPES:
        events.append({"_id": f"evt_{s['scope_id']}_profile", "pack_id": PACK_ID, "scope_id": s["scope_id"],
                       "type": "scope_profile", "payload": {"max_maturity": s["max_maturity"], "label": s["label"]},
                       "ts": ts(14, 8), "source": "seed"})
    plan = {
        "child_7": {"animals": 5, "space": 4, "art_craft": 3, "spooky": 4},   # spooky = the planted fault (recurs)
        "child_12": {"gaming": 5, "science": 4, "comedy": 3, "action": 3},
    }
    for sc in SCOPES:
        sid = sc["scope_id"]
        watches = []
        for topic, k in plan[sid].items():
            if topic == "spooky" and sid == "child_7":
                pool = [v for v in catalog if v["topic"] == "spooky" and v["maturity"] <= 1]
                chosen = (pool + [v for v in catalog if v["topic"] == "spooky"])[:k]  # recurring, includes some above gate
            else:
                chosen = pick(catalog, topic, k, sc["max_maturity"] + 1)
            watches += chosen
        rng.shuffle(watches)
        fact_by_topic = defaultdict(list)
        for n, v in enumerate(watches):
            d = 14 - (n * 14 // max(len(watches), 1))
            events.append({"_id": f"evt_{sid}_{n:02d}", "pack_id": PACK_ID, "scope_id": sid, "type": "watch",
                           "payload": {"video_id": v["video_id"], "completion": round(rng.uniform(0.6, 1.0), 2)},
                           "ts": ts(d, 15 + n % 5), "source": "seed"})
            nid = f"node_{sid}_fact_{n:02d}"
            nodes.append({"_id": nid, "pack_id": PACK_ID, "scope_id": sid, "kind": "watch_fact",
                          "text": f"watched {v['title']} ({v['topic']})", "embedding": None, "status": "active",
                          "expires_at": None, "support": []})
            fact_by_topic[v["topic"]].append(nid)
        interest_ids = {}
        for topic, facts in fact_by_topic.items():
            if len(facts) >= 3:  # recurrence threshold
                iid = f"node_{sid}_interest_{topic}"
                interest_ids[topic] = iid
                nodes.append({"_id": iid, "pack_id": PACK_ID, "scope_id": sid, "kind": "interest",
                              "text": f"likes {topic.replace('_', ' ')}", "embedding": None, "status": "active",
                              "expires_at": None, "support": facts})
                for f in facts:
                    edges.append({"_id": f"edge_{f}_{iid}", "pack_id": PACK_ID, "scope_id": sid,
                                  "from": f, "to": iid, "rel": "supports"})
        # initial slate (pre-directive): top interests, includes the planted fault
        slate = []
        slate_inputs = {}
        for topic in sorted(interest_ids, key=lambda t: -len(fact_by_topic[t])):
            for v in pick(catalog, topic, 2, 3):
                slate.append(v["video_id"])
                slate_inputs[v["video_id"]] = [interest_ids[topic]]
        if sid == "child_7" and "spooky" in interest_ids and "animals" in interest_ids:
            zoo = next(v for v in catalog if v["title"] == "Haunted Zoo Night")
            slate.append(zoo["video_id"])
            slate_inputs[zoo["video_id"]] = [interest_ids["spooky"], interest_ids["animals"]]  # independent support
        for n, vid in enumerate(slate):
            did = f"dec_{sid}_{n:02d}"
            decisions.append({"_id": did, "pack_id": PACK_ID, "scope_id": sid, "inputs": slate_inputs[vid],
                              "output": {"video_id": vid, "title": by_id[vid]["title"]}, "status": "active",
                              "replay_of": None, "ts": ts(0, 9)})
            for inp in slate_inputs[vid]:
                edges.append({"_id": f"edge_{inp}_{did}", "pack_id": PACK_ID, "scope_id": sid,
                              "from": inp, "to": did, "rel": "used_in"})
    return {"events": events, "nodes": nodes, "edges": edges, "decisions": decisions}


def build_scenario(graph):
    """Known answers for the retract-one demo (child_7 / interest spooky)."""
    fault = "node_child_7_interest_spooky"
    dec = [d for d in graph["decisions"] if d["scope_id"] == "child_7"]
    only = [d["_id"] for d in dec if d["inputs"] == [fault]]
    shared = [d["_id"] for d in dec if fault in d["inputs"] and len(d["inputs"]) > 1]
    return {"scope_id": "child_7", "retract": fault, "expect_invalidate_and_replay": only,
            "expect_preserve_independent_support": shared}


def main():
    catalog = build_catalog()
    graph = build_graph(catalog)
    taxonomy = {"topics": list(TOPICS), "maturity": {"0": "all ages", "1": "7+", "2": "10+", "3": "13+"},
                "restricted_tags": ["scary", "violence"]}
    files = {"catalog.json": catalog, "taxonomy.json": taxonomy, "scopes.json": SCOPES, "pack_video.json": PACK,
             "graph.json": graph, "scenario.json": build_scenario(graph)}
    for name, obj in files.items():
        (OUT / name).write_text(json.dumps(obj, indent=2) + "\n")
    print({k: (len(v) if isinstance(v, list) else {kk: len(vv) for kk, vv in v.items()} if k == "graph.json" else "ok")
           for k, v in files.items()})


if __name__ == "__main__":
    main()
