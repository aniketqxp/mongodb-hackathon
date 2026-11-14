from fastapi.testclient import TestClient

from mock.app import app

c = TestClient(app)


def test_unconfirmed_directive_is_422():
    r = c.post("/directives", json={"directive": {"type": "suppress"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_confirmed"


def test_confirmed_directive_ok_and_listed():
    assert c.post("/directives", json={"directive": {"confirmed_by": "pin"}}).json()["status"] == "active"
    assert c.get("/directives?pack_id=p&scope_id=s").json()["directives"][0]["status"] == "active"


def test_compiler_key_enforced_when_secret_set(monkeypatch):
    monkeypatch.setenv("COMPILER_SHARED_SECRET", "s3")
    body = {"directive": {"confirmed_by": "pin"}}
    assert c.post("/directives", json=body).status_code == 403
    assert c.post("/directives", json=body, headers={"X-Compiler-Key": "s3"}).status_code == 200
