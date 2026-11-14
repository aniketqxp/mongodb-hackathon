"""The suite must pass a correct core at 5/5 and catch each class of bug with exactly the matching check."""
import json
import re
from pathlib import Path

import pytest

from compiler.conformance import CHECKS, Core, run_conformance
from compiler.packs import REPO
from compiler.schemas import Pack
from compiler.tests.fake_core import FakeCore

VIDEO = Pack.model_validate(json.loads((REPO / "data" / "pack_video.json").read_text()))
TEAM = Pack.model_validate(json.loads((REPO / "compiler" / "pack_cache" / "pack_team_notes.json").read_text())["pack"])


def run(pack, broken=frozenset(), **kw):
    fc = FakeCore([pack], broken=broken, **kw)
    return run_conformance(pack, Core("http://core", fc.client()), now_fn=lambda: fc.now, sleep_fn=fc.sleep)


@pytest.mark.parametrize("pack", [VIDEO, TEAM], ids=lambda p: p.pack_id)
def test_correct_core_passes_5_of_5(pack):
    r = run(pack)
    assert r["passed"] == 5 and r["total"] == 5, r
    assert [c["name"] for c in r["checks"]] == CHECKS
    assert all(set(c) == {"id", "name", "passed", "detail"} for c in r["checks"])


@pytest.mark.parametrize("pack", [VIDEO, TEAM], ids=lambda p: p.pack_id)
@pytest.mark.parametrize(
    "broken,failing",
    [
        ("lazy_retract", {1}),
        ("greedy_retract", {2}),
        ("leaky_search", {3}),
        ("no_expiry", {4}),
        ("no_gate", {5}),
    ],
)
def test_each_bug_is_caught_by_its_check(pack, broken, failing):
    r = run(pack, broken={broken})
    failed = {c["id"] for c in r["checks"] if not c["passed"]}
    assert failed == failing, r


def test_missing_expire_route_is_reported(monkeypatch):
    r = run(VIDEO, expire_route=False)
    c4 = r["checks"][3]
    assert not c4["passed"] and "/expire" in c4["detail"]


def test_core_down_fails_every_check_without_raising():
    import httpx

    def down(req):
        raise httpx.ConnectError("down")

    r = run_conformance(VIDEO, Core("http://core", httpx.Client(transport=httpx.MockTransport(down))))
    assert r["passed"] == 0 and all("error" in c["detail"] or c["detail"] for c in r["checks"])


def test_runs_in_fresh_scopes_only():
    fc = FakeCore([VIDEO])
    run_conformance(VIDEO, Core("http://core", fc.client()), now_fn=lambda: fc.now, sleep_fn=fc.sleep)
    scopes = {n["scope_id"] for n in fc.nodes.values()}
    assert scopes and all(re.fullmatch(r"conf_[0-9a-f]{8}_[a-z]", s) for s in scopes)


def test_suite_has_no_domain_words():
    words = (REPO / "scripts" / "domain_words.txt").read_text().split()
    pat = re.compile(r"\b(" + "|".join(words) + r")", re.I)
    for f in ("conformance.py", "gate.py"):
        src = (REPO / "compiler" / f).read_text()
        assert not pat.search(src), f"{f}: {pat.search(src).group(0)}"
