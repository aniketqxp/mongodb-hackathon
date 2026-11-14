"""Stage runner: sentence -> pack -> conformance -> activate, against a mocked core."""
import json
import shutil

import httpx
import pytest

from compiler import demo_pack, pack as pk


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    shutil.copytree(pk.REPO / "compiler" / "pack_cache", tmp_path / "c")
    monkeypatch.setenv("PACK_CACHE_DIR", str(tmp_path / "c"))
    pk._calls["n"] = 0


def core(passed=5, active=False):
    calls = []

    def h(req):
        calls.append(req.url.path)
        if req.url.path == "/packs":
            if active:
                return httpx.Response(400, json={"error": {"code": "bad_request", "detail": "pack x is active; packs are immutable once active"}})
            return httpx.Response(200, json={"pack_id": json.loads(req.content)["pack"]["pack_id"], "status": "draft"})
        if req.url.path.endswith("/conformance"):
            return httpx.Response(200, json={"passed": passed, "total": 5, "checks": [
                {"id": i, "name": f"c{i}", "passed": i <= passed, "detail": "" if i <= passed else "broke"} for i in range(1, 6)]})
        if req.url.path.endswith("/activate"):
            if passed < 5:
                return httpx.Response(409, json={"error": {"code": "conformance_failed", "detail": "needs 5/5"}})
            return httpx.Response(200, json={"pack_id": req.url.path.split("/")[2], "status": "active"})
        return httpx.Response(404, json={})

    c = httpx.Client(transport=httpx.MockTransport(h))
    c.calls = calls
    return c


def test_happy_path_cached(capsys):
    c = core()
    assert demo_pack.run("team notes memory", "http://core", cached=True, client=c) == 0
    out = capsys.readouterr().out
    assert "LLM skipped" in out and "conformance 5/5" in out and "is active" in out
    assert c.calls == ["/packs", "/packs/pack_team_notes/conformance", "/packs/pack_team_notes/activate"]


def test_four_of_five_is_not_activated(capsys):
    assert demo_pack.run("team notes memory", "http://core", cached=True, client=core(passed=4)) == 1
    out = capsys.readouterr().out
    assert "FAIL  c5" in out and "not activated: conformance_failed" in out


def test_already_active_is_fine_on_rerun(capsys):
    c = core(active=True)
    assert demo_pack.run("team notes memory", "http://core", cached=True, client=c) == 0
    assert "already active" in capsys.readouterr().out and c.calls == ["/packs"]
