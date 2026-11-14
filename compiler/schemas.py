"""Typed slots from OPS/CONTRACT.md sections 2 and 3. Extra fields are rejected everywhere."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DirectiveType = Literal["suppress", "prioritize", "retract"]
RETRACT_KINDS = ("node", "directive")
MAX_CAP = 10
MAX_DURATION_SECONDS = 365 * 24 * 3600


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- Contract section 3: Directive ----------
class Target(_Strict):
    kind: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=128)


class Directive(_Strict):
    """Exactly the contract shape. All six fields are required (null allowed where the contract allows)."""

    type: DirectiveType
    target: Target
    expires_at: str | None
    cap: int = Field(ge=0, le=MAX_CAP)
    confirmed_by: Literal["pin", "builder"] | None
    source_text: str = Field(max_length=2000)

    @field_validator("expires_at")
    @classmethod
    def _iso_utc(cls, v: str | None) -> str | None:
        if v is None:
            return v
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("expires_at must carry a timezone (UTC)")
        return v

    @model_validator(mode="after")
    def _type_rules(self) -> "Directive":
        if self.type == "suppress":
            if self.expires_at is None:
                raise ValueError("suppress requires expires_at")
            if self.cap != 0:
                raise ValueError("suppress must have cap 0")
        elif self.type == "prioritize":
            if self.cap < 1:
                raise ValueError("prioritize requires cap >= 1")
        elif self.type == "retract":
            if self.target.kind not in RETRACT_KINDS:
                raise ValueError(f"retract target.kind must be one of {RETRACT_KINDS}")
            if self.cap != 0 or self.expires_at is not None:
                raise ValueError("retract takes no cap and no expires_at")
        return self


# ---------- What the LLM is allowed to fill (no confirmation, no dates, no source text) ----------
class DraftTarget(_Strict):
    kind: str
    value: str


class DirectiveDraft(_Strict):
    """LLM output slot. Code turns duration into expires_at and sets source_text. confirmed_by is absent on purpose."""

    type: DirectiveType
    target: DraftTarget
    duration_seconds: int | None
    cap: int | None


# ---------- Contract section 2: Pack ----------
class EdgeType(_Strict):
    rel: str
    from_: str = Field(alias="from")
    to: str

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GateRule(_Strict):
    field: str
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in"]
    value: Any
    value_from_scope: str | None = None


class Decay(_Strict):
    kind: Literal["none", "ttl", "linear"]
    seconds: int = Field(ge=0)


class Labels(_Strict):
    item: str
    scope: str
    directive: str


class Pack(_Strict):
    pack_id: str = Field(min_length=1)
    scope_field: str
    node_types: list[str]
    edge_types: list[EdgeType]
    gate: list[GateRule]
    decay: Decay
    directive_vocab: list[DirectiveType]
    labels: Labels
