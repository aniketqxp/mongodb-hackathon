"""Generic gate evaluator and directive matching. Pure functions, no I/O, no LLM.

The gate rules come from the pack (`gate` slot, CONTRACT section 2); directives follow
CONTRACT section 3. Precedence when they collide: gate > block (suppress) > boost (prioritize).
Everything fails closed: a missing field or an unknown operator rejects the item.
"""
from datetime import datetime, timezone

OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
}


def check_gate(item, rules, scope_profile):
    """Return (admitted, reason). reason is None when admitted."""
    for r in rules:
        field, op = r.get("field"), r.get("op")
        if op not in OPS:
            return False, "gate:unknown_op:%s" % op
        if field not in item:
            return False, "gate:missing_field:%s" % field
        src = r.get("value_from_scope")
        if src:
            if src not in scope_profile:
                return False, "gate:missing_scope_value:%s" % src
            limit = scope_profile[src]
        else:
            limit = r.get("value")
        try:
            ok = OPS[op](item[field], limit)
        except TypeError:
            ok = False
        if not ok:
            return False, "gate:%s %s %s" % (field, op, limit)
    return True, None


def _parse_ts(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def is_active(directive, now=None):
    now = now or datetime.now(timezone.utc)
    if directive.get("status") not in (None, "active"):
        return False
    exp = _parse_ts(directive.get("expires_at"))
    return exp is None or exp > now


def target_matches(item, target, id_field):
    """True if the directive target {kind, value} names this item.

    kind is an item field ('topic'), its plural ('tag' -> 'tags'), or 'item'/'id' for the item id.
    """
    kind = (target or {}).get("kind", "")
    value = str((target or {}).get("value", "")).strip().lower()
    if not kind or not value:
        return False
    if kind in ("item", "id", id_field):
        return str(item.get(id_field, "")).lower() == value
    field = kind if kind in item else kind + "s" if kind + "s" in item else None
    if field is None:
        return False
    got = item[field]
    if isinstance(got, (list, tuple, set)):
        return value in {str(x).lower() for x in got}
    return str(got).lower() == value


def split_directives(directives, now=None):
    """Active suppress and prioritize directives, in that order of precedence."""
    act = [d for d in directives if is_active(d, now)]
    return [d for d in act if d.get("type") == "suppress"], [d for d in act if d.get("type") == "prioritize"]
