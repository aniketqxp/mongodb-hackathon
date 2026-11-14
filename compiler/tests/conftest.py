import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from compiler import directive as dmod
from compiler.schemas import Pack

FIX = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)


@pytest.fixture
def pack():
    return Pack.model_validate(json.loads((FIX / "demo_pack.pack.json").read_text()))


@pytest.fixture
def vocab():
    return json.loads((FIX / "demo_pack.vocab.json").read_text())


@pytest.fixture(autouse=True)
def _clear_cache():
    dmod._cache.clear()
    yield
    dmod._cache.clear()


def stub(output):
    """Fake LLM that returns `output` and records the prompt it received."""

    def call(messages):
        call.messages = messages
        call.n += 1
        return output

    call.n = 0
    return call
