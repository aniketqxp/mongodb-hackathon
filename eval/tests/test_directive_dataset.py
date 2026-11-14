"""Keeps eval/directive_prompts.json honest: every expected draft compiles to that directive, and every
hostile draft is rejected by code with the expected error code. Offline (the LLM is stubbed by the answer)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from compiler.directive import DirectiveError, compile_directive
from compiler.packs import load_bundle

DS = json.loads((Path(__file__).resolve().parents[1] / "directive_prompts.json").read_text())
NOW = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)
B = load_bundle(DS["pack_id"])


def test_size_and_mix():
    rows = DS["prompts"]
    assert len(rows) == 25
    types = [r["expect"]["type"] for r in rows if "expect" in r]
    assert {"suppress", "prioritize", "retract"} == set(types)
    assert sum("expect_reject" in r for r in rows) >= 5


@pytest.mark.parametrize("row", DS["prompts"], ids=lambda r: r["id"])
def test_row(row):
    draft = row.get("expect") or row["hostile_draft"]
    run = lambda: compile_directive(row["text"], B.pack, B.vocab, llm=lambda _: draft,
                                    known_ids=B.known_ids(row["scope_id"]), now=NOW, use_cache=False)
    if "expect" in row:
        d = run()
        assert d.type == draft["type"] and d.target.model_dump() == draft["target"]
        assert d.confirmed_by is None and d.source_text == row["text"]
    else:
        with pytest.raises(DirectiveError) as e:
            run()
        assert e.value.code == row["expect_reject"]
