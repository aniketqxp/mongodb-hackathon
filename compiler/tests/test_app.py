"""Service-level tests: client cannot pre-confirm, wrong PIN never reaches core."""
import httpx
import pytest
from fastapi.testclient import TestClient

from compiler import app as appmod
from compiler.tests.conftest import stub


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DIRECTIVE_PIN", "4821")
    appmod.gate = appmod.PinGate()
    llm = stub({"type": "suppress", "target": {"kind": "topic", "value": "spooky"}, "duration_seconds": 86400, "cap": None})
    real = appmod.compile_directive
    monkeypatch.setattr(appmod, "compile_directive", lambda t, p, v, **kw: real(t, p, v, llm=llm, **kw))
    sent = []

    def fake_submit(d, pack, scope_id, vocab, **kw):
        sent.append(d)
        return {"directive_id": "dir_1", "status": "active"}

    monkeypatch.setattr(appmod, "submit_directive", fake_submit)
    c = TestClient(appmod.app)
    c.sent = sent
    return c


def test_compile_then_confirm(client):
    r = client.post("/directives/compile", json={"pack_id": "pack_video_demo", "scope_id": "child_7", "text": "no spooky today"})
    assert r.status_code == 200
    body = r.json()
    assert body["directive"]["confirmed_by"] is None and "spooky" in body["summary"]
    r = client.post("/directives/confirm", json={"pack_id": "pack_video_demo", "scope_id": "child_7", "directive": body["directive"], "pin": "4821"})
    assert r.status_code == 200 and r.json()["directive_id"] == "dir_1"
    assert client.sent[0].confirmed_by == "pin"


def test_client_preconfirmed_directive_still_needs_pin(client):
    d = client.post("/directives/compile", json={"pack_id": "pack_video_demo", "scope_id": "child_7", "text": "no spooky today"}).json()["directive"]
    d["confirmed_by"] = "builder"
    r = client.post("/directives/confirm", json={"pack_id": "pack_video_demo", "scope_id": "child_7", "directive": d, "pin": "0000"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_confirmed"
    assert client.sent == []


def test_unknown_pack_and_path_traversal(client):
    for pid in ("nope", "../../etc/passwd"):
        r = client.post("/directives/compile", json={"pack_id": pid, "scope_id": "child_7", "text": "x"})
        assert r.status_code in (400, 404) and "error" in r.json()


def test_extra_body_fields_rejected(client):
    r = client.post("/directives/compile", json={"pack_id": "pack_video_demo", "scope_id": "child_7", "text": "x", "confirmed_by": "pin"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_unknown_scope_rejected(client):
    r = client.post("/directives/compile", json={"pack_id": "pack_video_demo", "scope_id": "child_99", "text": "no spooky"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
