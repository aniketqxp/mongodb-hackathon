"""The film's numbers are computed, not typed: check them against the scenario in data/scenario.json."""
import json

from demo import film_data
from harness import data


def test_film_data_matches_scenario():
    sc = json.loads((data.DATA / "scenario.json").read_text())
    d = film_data.build()
    assert d["retracted"]["id"] == sc["retract"]
    assert d["proof"]["recalled"] == sorted(sc["expect_invalidate_and_replay"])
    assert d["proof"]["replayed"] == sorted(sc["expect_invalidate_and_replay"])
    assert d["proof"]["preserved"] == sorted(sc["expect_preserve_independent_support"])
    assert d["proof"]["stays_forgotten"] is True
    assert d["proof"]["naive_comes_back"] is True  # the label-only baseline re-derives it
    assert all(s["fault_items"] == 0 and not s["fault_active"] for s in d["sessions"])
    assert d["removed"] and d["kept_independent"]
    assert set(d["removed"]).isdisjoint(d["kept_independent"])


def test_committed_snapshot_is_current():
    from demo.film_data import HERE, js
    assert (HERE / "film_data.js").read_text() == js(), "run: python -m demo.film_data"
