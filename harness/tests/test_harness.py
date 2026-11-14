"""J2 harness tests. Run: python3 -m unittest discover -s harness/tests -t ."""
import unittest

from harness import data
from harness.gate import check_gate, is_active, target_matches
from harness.memory import SeedMemory
from harness.service import Harness
from harness.slate import build_slate

PACK = data.pack()["pack_id"]
SPOOKY = "node_child_7_interest_spooky"
FUTURE = "2099-01-01T00:00:00Z"


class FakeApi:
    """Records calls; answers like the mock API."""

    def __init__(self):
        self.decisions, self.events = [], []

    def record_decision(self, pack_id, scope_id, inputs, output):
        self.decisions.append((scope_id, inputs, output))
        return "dec_%d" % len(self.decisions)

    def post_event(self, pack_id, scope_id, type_, payload):
        self.events.append((scope_id, payload))
        return {"admitted": True, "reason": None, "node_id": "node_x"}

    def retract(self, pack_id, scope_id, target_id, reason):
        return {"plan": {"fault": target_id, "actions": [{"id": target_id, "action": "delete"}]}, "replayed": []}

    def diff(self, pack_id, scope_id, retract):
        return {"before": [], "after": [], "changed": [], "preserved": []}

    def list_directives(self, pack_id, scope_id, active_only=True):
        return [{"directive_id": "dir_api", "type": "suppress", "target": {"kind": "tag", "value": "scary"},
                 "expires_at": FUTURE, "cap": None, "confirmed_by": "pin", "status": "active"}]


def slate(scope, directives=(), previous=(), mem=None):
    mem = mem or SeedMemory()
    return build_slate(scope, mem.search(PACK, scope), directives, previous=previous)


class GateTests(unittest.TestCase):
    rules = [{"field": "maturity", "op": "lte", "value": None, "value_from_scope": "max_maturity"}]

    def test_scope_value(self):
        self.assertTrue(check_gate({"maturity": 1}, self.rules, {"max_maturity": 1})[0])
        self.assertFalse(check_gate({"maturity": 2}, self.rules, {"max_maturity": 1})[0])

    def test_fails_closed(self):
        self.assertFalse(check_gate({}, self.rules, {"max_maturity": 1})[0])          # missing item field
        self.assertFalse(check_gate({"maturity": 0}, self.rules, {})[0])              # missing scope value
        self.assertFalse(check_gate({"maturity": 0}, [{"field": "maturity", "op": "zz", "value": 1}], {})[0])

    def test_scope_profile_comes_from_seed_event(self):
        self.assertEqual(data.scope_profile("child_7")["max_maturity"], 1)
        self.assertEqual(data.scope_profile("child_12")["max_maturity"], 2)

    def test_target_matching_and_expiry(self):
        item = {"video_id": "v1", "topic": "spooky", "tags": ["scary", "dark"]}
        self.assertTrue(target_matches(item, {"kind": "tag", "value": "Scary"}, "video_id"))
        self.assertTrue(target_matches(item, {"kind": "topic", "value": "spooky"}, "video_id"))
        self.assertTrue(target_matches(item, {"kind": "item", "value": "v1"}, "video_id"))
        self.assertFalse(target_matches(item, {"kind": "colour", "value": "red"}, "video_id"))
        self.assertFalse(is_active({"expires_at": "2000-01-01T00:00:00Z"}))
        self.assertTrue(is_active({"expires_at": FUTURE}))


class SlateTests(unittest.TestCase):
    def test_gate_never_reaches_slate(self):
        for scope in data.scopes():
            mx = data.scope_profile(scope)["max_maturity"]
            out = slate(scope)
            self.assertTrue(out["slate"])
            self.assertTrue(all(e["maturity"] <= mx for e in out["slate"]))
            self.assertTrue(all(g["video_id"] not in {e["video_id"] for e in out["slate"]} for g in out["receipt"]["gated"]))

    def test_slate_only_uses_own_scope_memory(self):
        out = slate("child_7")
        self.assertTrue(all(s.startswith("node_child_7_") for e in out["slate"] for s in e["supports"]))

    def test_block_beats_boost(self):
        d = [{"type": "prioritize", "target": {"kind": "topic", "value": "spooky"}, "cap": 2, "expires_at": None, "directive_id": "b"},
             {"type": "suppress", "target": {"kind": "tag", "value": "scary"}, "expires_at": FUTURE, "directive_id": "s"}]
        out = slate("child_7", d)
        self.assertFalse([e for e in out["slate"] if "scary" in e["tags"]])
        self.assertFalse(out["receipt"]["boosted"])
        self.assertTrue(out["receipt"]["suppressed"])

    def test_boost_respects_cap_and_gate(self):
        d = [{"type": "prioritize", "target": {"kind": "topic", "value": "science"}, "cap": 2, "expires_at": None, "directive_id": "b"}]
        out = slate("child_7", d)
        boosted = [e for e in out["slate"] if e["boosted_by"] == "b"]
        self.assertEqual(len(boosted), 2)
        self.assertTrue(all(e["maturity"] <= 1 for e in boosted))

    def test_expired_suppress_is_ignored(self):
        d = [{"type": "suppress", "target": {"kind": "tag", "value": "scary"}, "expires_at": "2000-01-01T00:00:00Z"}]
        self.assertTrue([e for e in slate("child_7", d)["slate"] if "scary" in e["tags"]])

    def test_retraction_keeps_independently_supported_items(self):
        mem = SeedMemory()
        before = slate("child_7", mem=mem)["slate"]
        both = [e for e in before if SPOOKY in e["supports"] and len(e["supports"]) > 1]
        only = [e for e in before if e["supports"] == [SPOOKY]]
        self.assertTrue(both and only, "fixture should have dependent and independent items")
        mem.apply_retraction("child_7", SPOOKY, None)
        after = slate("child_7", previous=[e["video_id"] for e in before], mem=mem)["slate"]
        ids = {e["video_id"]: e for e in after}
        for e in both:
            self.assertEqual(ids[e["video_id"]]["status"], "kept")
        for e in only:
            self.assertNotIn(e["video_id"], ids)
        self.assertTrue(all(SPOOKY not in e["supports"] for e in after))


class ServiceTests(unittest.TestCase):
    def test_directives_from_api(self):
        out = Harness(api=FakeApi(), memory="seed", directives="api").feed("child_7")
        self.assertFalse([e for e in out["slate"] if "scary" in e["tags"]])
        self.assertTrue(all(s["directive_id"] == "dir_api" for s in out["receipt"]["suppressed"]))

    def test_local_directives_by_default(self):
        out = Harness(api=FakeApi(), memory="seed").feed("child_7")
        self.assertTrue([e for e in out["slate"] if "scary" in e["tags"]])

    def test_feed_records_decisions_with_supports(self):
        api = FakeApi()
        out = Harness(api=api, memory="seed").feed("child_7")
        self.assertEqual(len(api.decisions), len(out["slate"]))
        self.assertTrue(all(inputs for _, inputs, _ in api.decisions))

    def test_gated_watch_is_not_sent(self):
        api = FakeApi()
        h = Harness(api=api, memory="seed")
        res = h.watch("child_7", "vid_058")  # maturity 3
        self.assertFalse(res["admitted"])
        self.assertEqual(api.events, [])
        self.assertTrue(h.watch("child_7", "vid_000")["admitted"])
        self.assertEqual(api.events[0][1]["maturity"], 0)

    def test_kept_items_reuse_decisions(self):
        api = FakeApi()
        h = Harness(api=api, memory="seed")
        h.feed("child_7")
        n = len(api.decisions)
        h.retract("child_7", SPOOKY, "test")
        out = h.feed("child_7")
        new = [e for e in out["slate"] if e["status"] == "new"]
        self.assertEqual(len(api.decisions), n + len(new))
        self.assertTrue(out["removed"])


if __name__ == "__main__":
    unittest.main()
