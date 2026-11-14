"""Happy paths for the three primitives, PIN gate and submit (mock-shaped core)."""
import httpx
import pytest

from compiler.directive import DirectiveError, PinGate, compile_directive, describe, submit_directive
from compiler.schemas import Directive
from compiler.tests.conftest import NOW, stub


def test_suppress_gets_code_computed_expiry(pack, vocab):
    llm = stub({"type": "suppress", "target": {"kind": "topic", "value": "Scary"}, "duration_seconds": 7 * 86400, "cap": None})
    d = compile_directive("no scary stuff for a week", pack, vocab, llm=llm, now=NOW)
    assert d.type == "suppress"
    assert d.target.value == "scary"  # canonical vocab spelling
    assert d.expires_at == "2026-11-21T19:00:00Z"
    assert d.cap == 0 and d.confirmed_by is None
    assert d.source_text == "no scary stuff for a week"


def test_prioritize_default_cap(pack, vocab):
    llm = stub({"type": "prioritize", "target": {"kind": "topic", "value": "space"}, "duration_seconds": None, "cap": None})
    d = compile_directive("more space please", pack, vocab, llm=llm, now=NOW)
    assert d.type == "prioritize" and d.cap == 1 and d.expires_at is None


def test_prioritize_with_cap(pack, vocab):
    llm = stub({"type": "prioritize", "target": {"kind": "channel", "value": "synthetic science kids"}, "duration_seconds": 3600, "cap": 3})
    d = compile_directive("up to 3 from Synthetic Science Kids today", pack, vocab, llm=llm, now=NOW)
    assert d.cap == 3 and d.target.value == "Synthetic Science Kids" and d.expires_at == "2026-11-14T20:00:00Z"


def test_retract_known_id(pack, vocab):
    llm = stub({"type": "retract", "target": {"kind": "node", "value": "node_123"}, "duration_seconds": None, "cap": None})
    d = compile_directive("forget node_123", pack, vocab, llm=llm, known_ids={"node_123"}, now=NOW)
    assert d.type == "retract" and d.target.value == "node_123" and d.cap == 0 and d.expires_at is None


def test_output_matches_contract_keys(pack, vocab):
    llm = stub({"type": "suppress", "target": {"kind": "topic", "value": "slime"}, "duration_seconds": 86400, "cap": None})
    d = compile_directive("no slime today", pack, vocab, llm=llm, now=NOW)
    assert set(d.model_dump()) == {"type", "target", "expires_at", "cap", "confirmed_by", "source_text"}
    assert set(d.model_dump()["target"]) == {"kind", "value"}


def test_cache_reuses_validated_draft(pack, vocab):
    llm = stub({"type": "suppress", "target": {"kind": "topic", "value": "slime"}, "duration_seconds": 86400, "cap": None})
    compile_directive("no slime today", pack, vocab, llm=llm, now=NOW)
    compile_directive("No  slime today", pack, vocab, llm=llm, now=NOW)
    assert llm.n == 1


def test_describe(pack, vocab):
    llm = stub({"type": "suppress", "target": {"kind": "topic", "value": "slime"}, "duration_seconds": 86400, "cap": None})
    d = compile_directive("no slime today", pack, vocab, llm=llm, now=NOW)
    assert "slime" in describe(d, pack) and "2026-11-15T19:00:00Z" in describe(d, pack)


def test_pin_confirms(pack, vocab, monkeypatch):
    monkeypatch.setenv("DIRECTIVE_PIN", "4821")
    llm = stub({"type": "suppress", "target": {"kind": "topic", "value": "slime"}, "duration_seconds": 86400, "cap": None})
    d = compile_directive("no slime today", pack, vocab, llm=llm, now=NOW)
    c = PinGate().confirm(d, "4821", scope_id="h1")
    assert c.confirmed_by == "pin" and d.confirmed_by is None  # original untouched


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_submit_posts_contract_body(pack, vocab, monkeypatch):
    monkeypatch.setenv("DIRECTIVE_PIN", "4821")
    seen = {}

    def handler(req):
        import json

        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"directive_id": "dir_1", "status": "active"})

    llm = stub({"type": "suppress", "target": {"kind": "topic", "value": "slime"}, "duration_seconds": 86400, "cap": None})
    d = PinGate().confirm(compile_directive("no slime today", pack, vocab, llm=llm, now=NOW), "4821", "h1")
    out = submit_directive(d, pack, "h1", vocab, base_url="http://core", client=_mock_client(handler), now=NOW)
    assert out == {"directive_id": "dir_1", "status": "active"}
    assert seen["url"] == "http://core/directives"
    assert set(seen["body"]) == {"pack_id", "scope_id", "directive"}
    assert seen["body"]["directive"]["confirmed_by"] == "pin"


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(200, json={"error": {"code": "not_confirmed", "detail": "x"}}),  # mock style
        httpx.Response(400, json={"error": {"code": "not_confirmed", "detail": "x"}}),  # contract style
    ],
)
def test_submit_surfaces_core_errors(pack, vocab, resp):
    d = Directive(type="prioritize", target={"kind": "topic", "value": "space"}, expires_at=None, cap=2,
                  confirmed_by="pin", source_text="more space")
    with pytest.raises(DirectiveError) as e:
        submit_directive(d, pack, "h1", vocab, client=_mock_client(lambda r: resp), now=NOW)
    assert e.value.code == "not_confirmed"
