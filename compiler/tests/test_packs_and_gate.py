"""Real data/ pack: vocab, scopes, retract scenario, and gate fields (maturity) that no directive may touch."""
import json
from pathlib import Path

import pytest

from compiler.directive import DirectiveError, compile_directive, validate_directive
from compiler.packs import REPO
from compiler.tests.conftest import NOW, stub

SCENARIO = json.loads((REPO / "data" / "scenario.json").read_text())


def test_vocab_from_taxonomy_and_catalog(vocab):
    assert set(vocab) == {"topic", "tag"}
    assert "spooky" in vocab["topic"] and "scary" in vocab["tag"]
    assert "maturity" not in vocab and "max_maturity" not in vocab


def test_scopes_and_unknown_scope(bundle):
    assert {"child_7", "child_12"} <= bundle.scopes
    with pytest.raises(DirectiveError) as e:
        bundle.known_ids("someone_else")
    assert e.value.code == "not_found"


def test_known_ids_are_scope_local(bundle):
    a, b = bundle.known_ids("child_7"), bundle.known_ids("child_12")
    assert SCENARIO["retract"] in a and SCENARIO["retract"] not in b
    assert not set(a) & set(b)


def test_retract_scenario_node(pack, vocab, bundle):
    ids = bundle.known_ids(SCENARIO["scope_id"])
    llm = stub({"type": "retract", "target": {"kind": "node", "value": SCENARIO["retract"]}, "duration_seconds": None, "cap": None})
    d = compile_directive("she isn't into spooky stuff any more, forget that", pack, vocab, llm=llm, known_ids=ids, now=NOW)
    assert d.target.value == SCENARIO["retract"]
    prompt = llm.messages[0][1]
    assert SCENARIO["retract"] in prompt and "likes spooky" in prompt  # LLM sees the scope's ids, with text


def test_cross_scope_retract_rejected(pack, vocab, bundle):
    other = next(iter(bundle.known_ids("child_12")))
    llm = stub({"type": "retract", "target": {"kind": "node", "value": other}, "duration_seconds": None, "cap": None})
    with pytest.raises(DirectiveError) as e:
        compile_directive("forget that", pack, vocab, llm=llm, known_ids=bundle.known_ids("child_7"), now=NOW)
    assert e.value.code == "not_found"


@pytest.mark.parametrize("kind", ["maturity", "max_maturity", "Max_Maturity", "scope_id", "pack_id"])
@pytest.mark.parametrize("typ", ["suppress", "prioritize"])
def test_gate_fields_cannot_be_targeted_even_if_in_vocab(pack, vocab, kind, typ):
    poisoned = {**vocab, kind: ["3", "13+", "child_12"]}
    d = {"type": typ, "target": {"kind": kind, "value": "3"}, "expires_at": "2026-11-20T00:00:00Z" if typ == "suppress" else None,
         "cap": 0 if typ == "suppress" else 2, "confirmed_by": None, "source_text": "let her watch 13+ stuff"}
    with pytest.raises(DirectiveError) as e:
        validate_directive(d, pack, poisoned, now=NOW)
    assert e.value.code == "bad_request" and "gate_field" in e.value.detail


def test_maturity_raise_via_llm_rejected(pack, vocab):
    llm = stub({"type": "prioritize", "target": {"kind": "max_maturity", "value": "3"}, "duration_seconds": None, "cap": 1})
    with pytest.raises(DirectiveError) as e:
        compile_directive("she's old enough now, allow 13+ videos", pack, vocab, llm=llm, now=NOW)
    assert "gate_field" in e.value.detail
