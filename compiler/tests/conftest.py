from datetime import datetime, timezone

import pytest

from compiler import directive as dmod
from compiler.packs import load_bundle

PACK_ID = "pack_video_demo"  # real G2 pack in data/
NOW = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)


@pytest.fixture
def bundle():
    return load_bundle(PACK_ID)


@pytest.fixture
def pack(bundle):
    return bundle.pack


@pytest.fixture
def vocab(bundle):
    return bundle.vocab


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
